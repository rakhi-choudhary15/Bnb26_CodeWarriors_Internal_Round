"""`clip.generate` (AI-SKILLS.md algorithm, VIDEO-PIPELINE.md §3).

The documented pipeline is: candidate windows aligned to boundaries -> weighted
scoring -> non-max suppression -> reasons -> validation. Everything except the
human-readable `reason` is computed here in code, because a score the model
invents is not a score.

REAL, with one honest degradation: with no speech the transcript weight is
redistributed to visual signals, confidence is capped at 0.7 and the result is
flagged `visual_only`.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.ai.gateway.base import Message
from app.core.config import settings
from app.core.ids import stable_hash
from app.core.logging import get_logger
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.clip_generate.schemas import (
    ClipCandidate,
    ClipGenerateInput,
    ClipGenerateOutput,
    ScoreBreakdown,
)
from app.modules.skills.platform_specs import get_spec
from app.modules.skills.spec import ModelRequirement, SkillSpec

logger = get_logger(__name__)

#: Windows scored before the expensive hook call; keeps one LLM round-trip.
PRE_HOOK_LIMIT = 8
#: Windows sent to the reason writer.
REASON_LIMIT = 5

SPEC = SkillSpec(
    id="clip.generate",
    name="Generate clip candidates",
    purpose="Score candidate windows and propose clips for creator review.",
    input_schema=ClipGenerateInput,
    output_schema=ClipGenerateOutput,
    model_requirements=ModelRequirement(capability="mixed", json_mode=True, temperature=0.3),
    dependencies=("video.understand", "video.transcribe", "match.script_footage"),
    permissions=("r:assets", "r:transcript", "w:clips"),
    failure_conditions=(
        "no candidate above threshold -> empty clips, confidence 0.0",
        "no speech -> weights redistributed, confidence capped at 0.7",
        "range outside the asset -> clamped",
    ),
    validation_rules=(
        "clip_ranges_within_asset",
        "clip_durations_within_platform",
        "clips_do_not_overlap",
        "clips_above_threshold",
        "clip_ids_unique",
        "visual_only_confidence_capped",
        "reasons_present",
    ),
    status="real",
    async_job=True,
)

PROMPT_BODY = """Give a hook strength and a review reason for each candidate.

{intent}

{candidates}

Score only. Do not change any range or duration."""


class ClipGenerateSkill(SkillModule):
    spec = SPEC

    def run(self, payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
        data = ClipGenerateInput.model_validate(payload)
        platform = get_spec(data.platform)
        has_speech = bool(data.transcript)
        warnings: list[str] = []

        windows = _candidate_windows(data.duration_s, data.transcript, data.scenes)
        if not windows:
            return SkillResult.ok(
                ClipGenerateOutput(
                    asset_id=data.asset_id,
                    candidates_considered=0,
                    visual_only=not has_speech,
                    confidence=0.0,
                    warnings=["no_candidate_windows"],
                )
            )

        intent_vector = _embed(ctx, data.intent or data.asset_id)
        relevance_is_mock = ctx.gateway.provider_name == "dev"
        if relevance_is_mock:
            warnings.append("relevance_embedding_mocked")

        pool = windows[:PRE_HOOK_LIMIT]
        relevance = _relevances(ctx, data, pool, intent_vector, relevance_is_mock)

        scored: list[tuple[float, ClipCandidate]] = []
        for index, window in enumerate(pool):
            breakdown, mock = _score_window(
                window, data, relevance.get(index, 0.0), has_speech
            )
            warnings.extend(mock)
            scored.append(
                (
                    breakdown.total,
                    ClipCandidate(
                        id=_clip_id(data.asset_id, window),
                        asset_id=data.asset_id,
                        start_s=window["start_s"],
                        end_s=window["end_s"],
                        confidence=round(breakdown.total, 3),
                        target_platform=platform.key,
                        score_breakdown=breakdown,
                        visual_only=not has_speech,
                    ),
                )
            )

        scored.sort(key=lambda pair: pair[0], reverse=True)
        kept = _suppress([clip for _, clip in scored])[: settings.clip_max_candidates]
        hook_scores, hook_warnings = self._hook_strengths(kept, data, ctx)
        warnings.extend(hook_warnings)

        for clip in kept:
            hook = hook_scores.get(clip.id)
            if hook is None:
                continue
            clip.score_breakdown.hook_strength = hook
            clip.confidence = round(_weighted(clip.score_breakdown, has_speech), 3)

        kept = [clip for clip in kept if clip.confidence >= settings.clip_min_confidence]
        kept = _suppress(kept)[: settings.clip_max_candidates]
        warnings.extend(self._write_reasons(kept, data, ctx))

        visual_only = not has_speech
        if visual_only:
            warnings.append("no_speech_visual_weighting_applied")
        confidence = round(
            min((clip.confidence for clip in kept), default=0.0)
            * (0.6 + 0.4 * _coverage(kept, windows)),
            3,
        )
        return SkillResult.ok(
            ClipGenerateOutput(
                asset_id=data.asset_id,
                clips=kept,
                candidates_considered=len(windows),
                visual_only=visual_only,
                confidence=confidence,
                warnings=warnings,
            )
        )

    def _hook_strengths(
        self, clips: list[ClipCandidate], data: ClipGenerateInput, ctx: SkillContext
    ) -> tuple[dict[str, float], list[str]]:
        """Ask the model how strong each opening is; fall back to a measurement.

        A failed call must not lose the scoring stage, so the deterministic
        `speech in the first platform hook window` proxy is used instead.
        """
        if not clips:
            return {}, []
        spec = get_spec(clips[0].target_platform)
        body = PROMPT_BODY.format(
            intent=ctx.data_block("intent", {"text": data.intent, "platform": spec.key}),
            candidates=ctx.data_block(
                "candidates",
                [
                    {
                        "id": clip.id,
                        "start_s": clip.start_s,
                        "end_s": clip.end_s,
                        "speech": _speech_in(data.transcript, clip.start_s, spec.hook_window_s),
                        "scene": _scene_at(data.scenes, clip.start_s),
                    }
                    for clip in clips
                ],
            ),
        )
        messages: list[Message] = ctx.messages(f"[subtask:hook_strength]\n{body}")
        try:
            scored, _ = ctx.gateway.generate_structured(
                messages,
                schema=HookScores,
                namespace=f"clip.generate.hooks:{data.asset_id}",
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 - degrade to the proxy
            logger.warning("clip.generate: hook scoring failed, using proxy: %s", exc)
            return (
                {clip.id: _hook_proxy(data.transcript, clip, spec.hook_window_s) for clip in clips},
                ["hook_strength_model_unavailable_used_proxy"],
            )
        values = {entry.id: _clamp01(entry.hook_strength) for entry in scored.scores}
        return values, ["hook_strength_model_proxy_used"] if not values else []

    def _write_reasons(
        self, clips: list[ClipCandidate], data: ClipGenerateInput, ctx: SkillContext
    ) -> list[str]:
        if not clips:
            return []
        top = clips[:REASON_LIMIT]
        body = PROMPT_BODY.format(
            intent=ctx.data_block("intent", {"text": data.intent}),
            candidates=ctx.data_block(
                "candidates",
                [
                    {
                        "id": clip.id,
                        "start_s": clip.start_s,
                        "end_s": clip.end_s,
                        "speech": _speech_in(data.transcript, clip.start_s, clip.duration_s),
                        "scene": _scene_at(data.scenes, clip.start_s),
                    }
                    for clip in top
                ],
            ),
        )
        try:
            reasons, _ = ctx.gateway.generate_structured(
                ctx.messages(f"[subtask:reason]\n{body}"),
                schema=ClipReasons,
                namespace=f"clip.generate.reasons:{data.asset_id}",
                temperature=0.3,
            )
        except Exception as exc:  # noqa: BLE001 - a missing reason is a warning
            logger.warning("clip.generate: reason writing failed: %s", exc)
            return ["clip_reasons_unavailable"]
        mapping = {entry.id: entry.reason.strip() for entry in reasons.reasons}
        for clip in top:
            if clip.id in mapping:
                clip.reason = mapping[clip.id][:600]
        return []


class HookScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    hook_strength: float = Field(default=0.0, ge=0.0, le=1.0)


class ClipReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=600)


class HookScores(BaseModel):
    """Structured output for the hook-strength call."""

    model_config = ConfigDict(extra="forbid")

    scores: list[HookScore] = Field(default_factory=list)


class ClipReasons(BaseModel):
    """Structured output for the review-reason call."""

    model_config = ConfigDict(extra="forbid")

    reasons: list[ClipReason] = Field(default_factory=list)


def _weighted(breakdown: ScoreBreakdown, has_speech: bool) -> float:
    """Apply the documented weights, redistributing when there is no speech."""
    relevance, hook = breakdown.relevance, breakdown.hook_strength
    visual, completeness, dna = (
        breakdown.visual_quality,
        breakdown.completeness,
        breakdown.dna_fit,
    )
    if has_speech:
        return (
            settings.clip_weight_relevance * relevance
            + settings.clip_weight_hook * hook
            + settings.clip_weight_visual_quality * visual
            + settings.clip_weight_completeness * completeness
            + settings.clip_weight_dna_fit * dna
        )
    # No transcript to be relevant to: the speech weights move to visual signals
    # and completeness, then the whole score is capped downstream.
    relevance_share = settings.clip_weight_relevance
    speech_share = settings.clip_weight_hook + relevance_share
    return (
        relevance_share * (visual * 0.5 + completeness * 0.5)
        + speech_share * (visual * 0.5 + hook * 0.5)
        + settings.clip_weight_visual_quality * visual
        + settings.clip_weight_completeness * completeness
        + settings.clip_weight_dna_fit * dna
    ) / (1.0 + speech_share)


def _candidate_windows(
    duration_s: float, transcript: list[dict[str, Any]], scenes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Sliding windows of the documented size, aligned to real boundaries."""
    boundaries = {0.0, round(duration_s, 3)}
    for segment in transcript:
        start, end = _numbers(segment, "start_s", "start", "start_time")
        if start is not None:
            boundaries.add(round(min(max(start, 0.0), duration_s), 3))
        if end is not None:
            boundaries.add(round(min(max(end, 0.0), duration_s), 3))
    for scene in scenes:
        start, end = _numbers(scene, "start_s", "start", "start_time")
        if start is not None:
            boundaries.add(round(min(max(start, 0.0), duration_s), 3))
        if end is not None:
            boundaries.add(round(min(max(end, 0.0), duration_s), 3))

    points = sorted(boundaries)
    windows: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()
    for start in points:
        for end in points:
            if end <= start:
                continue
            length = round(end - start, 3)
            if length < settings.clip_window_min_s or length > settings.clip_window_max_s:
                continue
            key = (start, end)
            if key in seen:
                continue
            seen.add(key)
            windows.append({"start_s": start, "end_s": end})
    windows.sort(key=lambda w: (w["start_s"], -w["end_s"]))
    return windows


def _score_window(
    window: dict[str, Any],
    data: ClipGenerateInput,
    relevance: float,
    has_speech: bool,
) -> tuple[ScoreBreakdown, list[str]]:
    """The five documented components for one window."""
    warnings: list[str] = []
    breakdown = ScoreBreakdown(
        relevance=round(_clamp01(relevance), 4),
        visual_quality=_visual_quality(data.scenes, window),
        completeness=_completeness(data, window),
        dna_fit=_dna_fit(data.reference_dna, window["end_s"] - window["start_s"]),
    )
    if not has_speech:
        warnings.append("window_scored_without_transcript")
    return breakdown, warnings


def _relevances(
    ctx: SkillContext,
    data: ClipGenerateInput,
    windows: list[dict[str, Any]],
    intent_vector: list[float] | None,
    is_mock: bool,
) -> dict[int, float]:
    """0.35-weight component: embedding cosine between intent and window speech.

    One batched embedding call. With the dev provider the vectors are hash-based
    and carry no semantics, so a flat neutral score is returned rather than a
    meaningless similarity.
    """
    if is_mock or intent_vector is None:
        return {index: 0.5 for index in range(len(windows))}
    texts = [
        _speech_in(data.transcript, window["start_s"], window["end_s"] - window["start_s"])
        for window in windows
    ]
    speakable = [(index, text) for index, text in enumerate(texts) if text.strip()]
    if not speakable:
        return {index: 0.0 for index in range(len(windows))}
    try:
        embedded = ctx.gateway.embed(
            [text for _, text in speakable], namespace=f"clip.generate.rel:{data.asset_id}"
        )
        vectors = embedded.vectors
    except Exception as exc:  # noqa: BLE001 - relevance degrades, not fatal
        logger.warning("clip.generate: relevance embedding failed: %s", exc)
        return {index: 0.5 for index in range(len(windows))}
    scores: dict[int, float] = {index: 0.0 for index in range(len(windows))}
    for (index, _), vector in zip(speakable, vectors, strict=False):
        scores[index] = _cosine(intent_vector, vector)
    return scores


def _cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity mapped to 0..1, since the raw range is -1..1."""
    size = min(len(left), len(right))
    if size == 0:
        return 0.0
    dot = sum(float(left[i]) * float(right[i]) for i in range(size))
    norm_left = math.sqrt(sum(float(v) ** 2 for v in left[:size]))
    norm_right = math.sqrt(sum(float(v) ** 2 for v in right[:size]))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return (dot / (norm_left * norm_right) + 1.0) / 2.0


def _visual_quality(scenes: list[dict[str, Any]], window: dict[str, Any]) -> float:
    """Mean quality of the scenes the window covers."""
    covering = [
        scene
        for scene in scenes
        if float(scene.get("end_s", scene.get("end", 0.0)) or 0.0) > window["start_s"]
        and float(scene.get("start_s", scene.get("start", 0.0)) or 0.0) < window["end_s"]
    ]
    scores = [
        float(((scene.get("quality") or {}) if isinstance(scene, dict) else {}).get("score", 0.5))
        for scene in covering
    ]
    if not scores:
        return 0.5
    return round(_clamp01(sum(scores) / len(scores)), 4)


def _completeness(data: ClipGenerateInput, window: dict[str, Any]) -> float:
    """1.0 when the window both starts and ends on a sentence boundary."""
    starts_clean = _is_boundary(data, window["start_s"], data.transcript, scenes_only=False)
    ends_clean = _is_boundary(data, window["end_s"], data.transcript, scenes_only=False)
    if starts_clean and ends_clean:
        return 1.0
    return 0.5 if (starts_clean or ends_clean) else 0.0


def _is_boundary(
    data: ClipGenerateInput, at_s: float, transcript: list[dict[str, Any]], *, scenes_only: bool
) -> bool:
    for segment in transcript:
        for key in ("start_s", "start", "start_time"):
            value = segment.get(key) if isinstance(segment, dict) else None
            if isinstance(value, (int, float)) and abs(float(value) - at_s) < 0.05:
                return True
    for scene in data.scenes:
        for key in ("start_s", "start", "start_time"):
            value = scene.get(key) if isinstance(scene, dict) else None
            if isinstance(value, (int, float)) and abs(float(value) - at_s) < 0.05:
                return True
    return False


def _dna_fit(reference_dna: dict[str, Any], duration_s: float) -> float:
    """Fit to a preferred clip length when the DNA states one."""
    target = reference_dna.get("preferred_clip_duration_s") or reference_dna.get(
        "target_clip_duration_s"
    )
    if not isinstance(target, (int, float)) or target <= 0:
        return 0.5
    ratio = min(duration_s, float(target)) / max(duration_s, float(target))
    return round(_clamp01(ratio), 4)


def _suppress(clips: list[ClipCandidate]) -> list[ClipCandidate]:
    """Non-max suppression: drop candidates overlapping a stronger one."""
    kept: list[ClipCandidate] = []
    for clip in sorted(clips, key=lambda c: c.confidence, reverse=True):
        if any(_overlap_ratio(clip, other) > settings.clip_nms_overlap for other in kept):
            continue
        kept.append(clip)
    return kept


def _overlap_ratio(left: ClipCandidate, right: ClipCandidate) -> float:
    overlap = min(left.end_s, right.end_s) - max(left.start_s, right.start_s)
    if overlap <= 0:
        return 0.0
    shortest = min(left.duration_s, right.duration_s) or 1.0
    return round(overlap / shortest, 4)


def _coverage(clips: list[ClipCandidate], windows: list[dict[str, Any]]) -> float:
    if not windows:
        return 0.0
    return round(min(1.0, len(clips) / len(windows)), 4)


def _speech_in(transcript: list[dict[str, Any]], start_s: float, window_s: float) -> str:
    end_s = start_s + max(window_s, 0.0)
    parts = [
        str(segment.get("text") or "").strip()
        for segment in transcript
        if _overlaps(segment, start_s, end_s) and str(segment.get("text") or "").strip()
    ]
    return " ".join(parts)


def _overlaps(segment: dict[str, Any], start_s: float, end_s: float) -> bool:
    start, end = _numbers(segment, "start_s", "start", "start_time")
    if start is None:
        return False
    stop = end if end is not None else start + 2.0
    return stop > start_s and start < end_s


def _scene_at(scenes: list[dict[str, Any]], at_s: float) -> dict[str, Any]:
    for scene in scenes:
        start = float(scene.get("start_s", scene.get("start", 0.0)) or 0.0)
        end = float(scene.get("end_s", scene.get("end", 0.0)) or 0.0)
        if start <= at_s < end:
            return {"caption": scene.get("caption", ""), "tags": scene.get("tags", [])}
    return {}


def _numbers(entry: dict[str, Any], *keys: str) -> tuple[float | None, float | None]:
    values: list[float | None] = []
    for key in keys:
        raw = entry.get(key) if isinstance(entry, dict) else None
        values.append(float(raw) if isinstance(raw, (int, float)) else None)
    while len(values) < 2:
        values.append(None)
    return values[0], values[1]


def _clip_id(asset_id: str, window: dict[str, Any]) -> str:
    """Stable, derived id: no timestamps or uuids invented by a model."""
    digest = stable_hash({"asset": asset_id, **window})[:12]
    return f"clip_{digest}"


def _embed(ctx: SkillContext, text: str) -> list[float] | None:
    try:
        return ctx.gateway.embed_one(text)
    except Exception as exc:  # noqa: BLE001 - relevance degrades, not fatal
        logger.warning("clip.generate: embedding failed: %s", exc)
        return None


def _hook_proxy(
    transcript: list[dict[str, Any]], clip: ClipCandidate, hook_window_s: float
) -> float:
    """Deterministic stand-in: speech present in the opening seconds."""
    opening = _speech_in(transcript, clip.start_s, hook_window_s)
    return 0.6 if opening.strip() else 0.3


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


registry.register(SPEC, ClipGenerateSkill)
