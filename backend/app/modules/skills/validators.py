"""Named rule validators (AI-ARCHITECTURE.md §8, AI-SKILLS.md).

Skills declare validator names in `SkillSpec.validation_rules`; the router
resolves them here. A validator returns a mutated dict (to clamp, drop or fill
values) or a warning string. It never raises for a data problem — only genuine
bugs propagate, and the router converts those into warnings.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

Validator = Callable[[dict[str, Any], Any], dict[str, Any] | str | None]
_REGISTRY: dict[str, Validator] = {}


def register(name: str) -> Callable[[Validator], Validator]:
    def decorator(fn: Validator) -> Validator:
        _REGISTRY[name] = fn
        return fn

    return decorator


def get(name: str) -> Validator | None:
    return _REGISTRY.get(name)


def names() -> list[str]:
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Platform limits
# ---------------------------------------------------------------------------
def platform_limit(platform: str | None) -> dict[str, Any]:
    """Duration/caption limits for a platform.

    Delegates to the single spec table in `platform_specs` so there is never a
    second place where a platform limit is written down.
    """
    from app.modules.skills.platform_specs import PLATFORMS

    spec = PLATFORMS.get((platform or "").strip().lower())
    if spec is None:
        spec = PLATFORMS["other"]
    return {
        "max_s": spec.max_duration_s,
        "min_s": spec.min_duration_s,
        "aspect": spec.aspect,
        "caption_chars": spec.caption_chars,
        "hook_s": spec.hook_window_s,
    }


# ---------------------------------------------------------------------------
# Timing / duration
# ---------------------------------------------------------------------------
@register("duration_within_target")
def _duration_within_target(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """AI-SKILLS.md `script.generate`: estimated duration within ±10% of target."""
    target = data.get("target_duration_s")
    estimated = data.get("estimated_duration_s")
    if target in (None, 0) or estimated is None:
        return None
    drift = abs(float(estimated) - float(target)) / float(target)
    if drift <= 0.10:
        return None
    # Clamp toward the target by scaling spoken lines rather than rejecting.
    scale = float(target) / max(float(estimated), 0.001)
    for line in data.get("lines") or []:
        if isinstance(line, dict) and line.get("estimated_seconds") is not None:
            line["estimated_seconds"] = round(float(line["estimated_seconds"]) * scale, 2)
    data["estimated_duration_s"] = round(float(estimated) * scale, 2)
    data["confidence"] = round(min(float(data.get("confidence", 0.6)), 0.55), 2)
    return f"duration_clamped_from_{round(float(estimated), 1)}s"


@register("hook_spoken_length")
def _hook_spoken_length(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """AI-SKILLS.md `hook.generate`: ≤12 spoken words / ≤3s estimated."""
    warnings: list[str] = []
    limit = 12 if float(data.get("target_duration_s") or 30) <= 60 else 20
    for hook in data.get("hooks") or []:
        if not isinstance(hook, dict):
            continue
        words = str(hook.get("text", "")).split()
        if len(words) > limit:
            hook["text"] = " ".join(words[:limit])
            hook["score"] = round(min(float(hook.get("score", 0.6)), 0.5), 2)
            warnings.append("hook_truncated")
    return ", ".join(warnings) if warnings else None


@register("timestamps_within_media")
def _timestamps_within_media(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """D-009: never emit a timestamp outside the analysed media."""
    duration = ctx.context.get("media_duration_s") if ctx else None
    if not duration:
        duration = data.get("media_duration_s")
    if not duration:
        return None
    limit = float(duration) + 0.75
    warnings: list[str] = []
    for key in ("start_s", "end_s"):
        value = data.get(key)
        if isinstance(value, (int, float)) and value > limit:
            data[key] = round(limit, 2)
            warnings.append(f"{key}_clamped_to_media")
    if float(data.get("end_s", 0)) <= float(data.get("start_s", 0)):
        data["end_s"] = round(float(data.get("start_s", 0)) + 1.0, 2)
        warnings.append("end_before_start_fixed")
    return ", ".join(warnings) if warnings else None


@register("shots_sum_to_target")
def _shots_sum_to_target(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """AI-SKILLS.md `shot.plan`: Σduration >= target; fields complete."""
    shots = data.get("shots") or []
    if not shots:
        return "no_shots_returned"
    required = ("n", "start_s", "end_s", "framing", "action", "lighting")
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        for field in required:
            if not shot.get(field):
                shot[field] = "unspecified"
    total = round(
        sum(float(s.get("end_s", 0)) - float(s.get("start_s", 0)) for s in shots if isinstance(s, dict)),
        2,
    )
    data["total_duration_s"] = total
    target = ctx.context.get("target_duration_s") if ctx else None
    if target and total < float(target) * 0.9:
        # Extend the last shot rather than dropping plan detail.
        last = shots[-1]
        if isinstance(last, dict):
            last["end_s"] = round(float(last["end_s"]) + (float(target) - total), 2)
        data["total_duration_s"] = round(total + (float(target) - total), 2)
        return "shots_extended_to_target"
    return None


@register("confidence_bounded")
def _confidence_bounded(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Clamp confidence into 0..1 and guarantee a warnings list.

    Two shapes are in use: a scalar for single-output skills, and a per-field
    object (with an ``overall`` roll-up) for the Intent Engine, so both are
    clamped here rather than in each skill.
    """
    raw = data.get("confidence", 0.5)
    if isinstance(raw, dict):
        for key, value in list(raw.items()):
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = 0.5
            if not math.isfinite(number):
                number = 0.5
            raw[key] = round(max(0.0, min(1.0, number)), 2)
        if "overall" not in raw:
            values = list(raw.values())
            raw["overall"] = round(sum(values) / len(values), 2) if values else 0.5
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.5
        if not math.isfinite(value):
            value = 0.5
        data["confidence"] = round(max(0.0, min(1.0, value)), 2)
    data.setdefault("warnings", [])
    if not isinstance(data["warnings"], list):
        data["warnings"] = []
    return data


@register("no_speech_confidence_cap")
def _no_speech_confidence_cap(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """D-017: dance footage without speech caps confidence at 0.7 and flags it."""
    transcript_empty = bool(ctx.context.get("transcript_segments") or []) is False
    if not transcript_empty:
        return data
    data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.7), 2)
    warnings = data.setdefault("warnings", [])
    for flag in ("no_speech_visual_only", "confidence_capped_0.7"):
        if flag not in warnings:
            warnings.append(flag)
    return data


@register("clip_ranges_valid")
def _clip_ranges_valid(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """AI-SKILLS.md `clip.generate`: 0 <= start < end <= duration, platform bounds.

    Bounds come from `platform_specs` so there is exactly one place where a
    platform's limits are written down.
    """
    from app.modules.skills.platform_specs import clamp_duration, get_spec

    warnings: list[str] = []
    clips: list[Any] = [c for c in (data.get("clips") or []) if isinstance(c, dict)]
    kept: list[Any] = []
    for clip in clips:
        start = max(0.0, round(float(clip.get("start_s", 0)), 3))
        end = round(float(clip.get("end_s", 0)), 3)
        if end <= start:
            warnings.append("clip_dropped_empty_range")
            continue
        platform = str(clip.get("target_platform") or "instagram_reels")
        wanted = round(end - start, 3)
        clamped = clamp_duration(platform, wanted)
        if abs(clamped - wanted) > 1e-6:
            # Shrink from the tail: the head carries the hook.
            end = round(start + clamped, 3)
            warnings.append("clip_clamped_to_platform_bounds")
        clip["start_s"] = start
        clip["end_s"] = end
        kept.append(clip)
    data["clips"] = kept
    if kept:
        get_spec(str(kept[0].get("target_platform") or "instagram_reels"))
    return ", ".join(warnings) if warnings else None


@register("edl_ranges_within_clip")
def _edl_ranges_within_clip(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """VIDEO-PIPELINE.md §3: EDL in/out must sit inside the clip's source range."""
    clip = ctx.context.get("clip") if ctx else None
    if not clip:
        return None
    clip_start = float(clip.get("start_s", 0))
    clip_end = float(clip.get("end_s", 0))
    edl = data.get("edl") or {}
    warnings: list[str] = []
    for track in edl.get("tracks", {}).values():
        if not isinstance(track, list):
            continue
        for item in track:
            if not isinstance(item, dict) or "in_s" not in item:
                continue
            in_s = max(clip_start, float(item["in_s"]))
            out_s = min(clip_end, float(item.get("out_s", clip_end)))
            if out_s <= in_s:
                out_s = in_s + 0.5
                warnings.append("edl_range_collapsed")
            item["in_s"] = round(in_s, 2)
            item["out_s"] = round(out_s, 2)
    data["edl"] = edl
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("platform_caption_limits")
def _platform_caption_limits(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    platform = platform_limit(data.get("platform"))
    limit = int(platform["caption_chars"])
    warnings: list[str] = []
    if len(data.get("caption") or "") > limit:
        data["caption"] = data["caption"][: limit - 1] + "…"
        warnings.append("caption_truncated")
    title_limit = 100 if data.get("platform") == "youtube" else 200
    if len(data.get("title") or "") > title_limit:
        data["title"] = data["title"][:title_limit]
        warnings.append("title_truncated")
    return ", ".join(warnings) if warnings else None


@register("dna_timestamps_from_detector")
def _dna_timestamps_from_detector(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """REFERENCE-DNA.md §3: structural facts come from ffprobe/PySceneDetect.

    The model may label and summarise, but it may not introduce numbers that the
    deterministic metrics stage did not measure. Numeric drift beyond a tolerance
    is a real failure and is surfaced, not silently accepted.
    """
    measured = ctx.context.get("measured_metrics") if ctx else None
    if not measured:
        return "dna_metrics_unmeasured"
    dna = data.get("dna") or data
    warnings: list[str] = []
    pairs = (
        ("duration_s", "duration_s", 0.6),
        (("hook", "duration_s"), ("hook", "duration_s"), 0.5),
        (("shots", "count"), ("shots", "count"), 0.01),
        (("shots", "avg_s"), ("shots", "avg_s"), 0.4),
    )
    for m_path, d_path, tol in pairs:
        m_val = _dig(measured, m_path)
        d_val = _dig(dna, d_path)
        if m_val is None or d_val is None:
            continue
        if abs(float(m_val) - float(d_val)) > tol:
            _put(dna, d_path, m_val)
            warnings.append(f"dna_{'.'.join(d_path)}_corrected_to_measured")
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("vision_semantics_required")
def _vision_semantics_required(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Reference/scene captions need real semantics; pixel stats alone are not one.

    When the provider could not describe the frame we keep the measurement but
    refuse to pretend the caption is a semantic description.
    """
    if data.get("semantic_available") is False:
        warnings = data.setdefault("warnings", [])
        for flag in ("semantic_unavailable", "metrics_only"):
            if flag not in warnings:
                warnings.append(flag)
    return data


def _dig(obj: Any, path: tuple[str, ...]) -> Any:
    cur = obj
    for part in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _put(obj: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur = obj
    for part in path[:-1]:
        cur = cur.setdefault(part, {})
    cur[path[-1]] = value


#: Content-safety screen applied to any text the UI will render (SECURITY.md §7).
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"reveal\s+(your|the)\s+(system\s+)?prompt", re.I),
    re.compile(r"disregard\s+(the\s+)?(system|previous)\s+prompt", re.I),
    re.compile(r"\b(api[_-]?key|secret|password|token)\b\s*[:=]", re.I),
)


def screen_untrusted_text(text: str, *, source: str) -> str:
    """Detect injection attempts inside untrusted input.

    We do not execute anything, but a match is recorded as a warning and the
    caller can refuse to use the text as a generation instruction.
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text or ""):
            from app.core.logging import log_event

            log_event(logger, "prompt_injection.detected", source=source, pattern=pattern.pattern[:40])
            return "injection_suspected"
    return ""