"""`video.understand` (AI-SKILLS.md: scenes + captions, `video.understand` REAL).

Scene boundaries and visual metrics are produced by the deterministic detector in
the worker and passed in as facts. This skill only asks a vision model to describe
those scenes, and reports honestly when it cannot.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.gateway.base import GenerateResult
from app.core.config import settings
from app.core.logging import get_logger
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.spec import ModelRequirement, SkillSpec
from app.modules.skills.video_understand.schemas import (
    Scene,
    SceneQuality,
    UnderstandInput,
    VideoUnderstandOutput,
)

logger = get_logger(__name__)

SPEC = SkillSpec(
    id="video.understand",
    name="Understand footage",
    purpose="Turn deterministic scene detection into captioned, quality-scored scenes.",
    input_schema=UnderstandInput,
    output_schema=VideoUnderstandOutput,
    model_requirements=ModelRequirement(capability="vision", temperature=0.2),
    dependencies=("asset.ingest",),
    permissions=("r:assets", "w:scenes"),
    failure_conditions=(
        "no detected scenes -> confidence 0.0, scenes empty",
        "vision unavailable -> captions dropped, not invented",
        "more frames than the cap -> only the cap is analysed",
    ),
    validation_rules=(
        "scene_ranges_within_asset",
        "scene_count_within_cap",
        "scenes_contiguous",
        "captions_flagged_without_vision",
        "quality_scores_present",
        "confidence_bounded",
    ),
    status="real",
    async_job=True,
)

PROMPT_BODY = """Describe each supplied scene.

{scenes}

Return one caption and tag list per scene, in the given order."""


class VideoUnderstandSkill(SkillModule):
    spec = SPEC

    def run(self, payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
        data = UnderstandInput.model_validate(payload)
        scene_context = ctx.context.get("scenes") or data.detected_scenes
        scenes = _to_scenes(scene_context, data.duration_s)
        if not scenes:
            logger.warning("video.understand: no detected scenes for asset %s", data.asset_id)
            return SkillResult.ok(
                VideoUnderstandOutput(
                    asset_id=data.asset_id,
                    vision_status="unavailable",
                    confidence=0.0,
                    warnings=["no_scenes_detected"],
                )
            )

        frames = _sample_frames(ctx.context.get("frames"))
        captions, vision_status, vision_warnings, frames_used = self._describe(
            frames, scenes, ctx
        )
        merged = [
            scene.model_copy(
                update={
                    "caption": captions.get(index, {}).get("caption", ""),
                    "tags": list(captions.get(index, {}).get("tags", [])),
                }
            )
            for index, scene in enumerate(scenes)
        ]
        warnings = [*vision_warnings]
        if not data.has_speech:
            # Flagged for `clip.generate`, which redistributes its weights.
            warnings.append("no_speech_visual_weighting_expected")
        confidence = _confidence(vision_status, merged)
        return SkillResult.ok(
            VideoUnderstandOutput(
                asset_id=data.asset_id,
                scenes=merged,
                frames_analyzed=frames_used,
                vision_status=vision_status,
                confidence=confidence,
                warnings=warnings,
            )
        )

    def _describe(
        self,
        frames: list[dict[str, Any]],
        scenes: list[Scene],
        ctx: SkillContext,
    ) -> tuple[dict[int, dict[str, Any]], str, list[str], int]:
        """Vision-caption each scene from the frame nearest its midpoint.

        Returns captions keyed by scene index, an honest vision status, warnings
        and the number of frames actually sent.
        """
        if not frames:
            return {}, "unavailable", ["vision_frames_unavailable"], 0

        system = load_prompt("video_understand/prompt.md")
        chosen = [_frame_for(scene, frames) for scene in scenes]
        images = [(f["bytes"], "image/jpeg") for f in chosen if f is not None]
        frames_used = len(images)
        if not images:
            return {}, "unavailable", ["vision_frames_unreadable"], 0

        body = PROMPT_BODY.format(
            scenes=ctx.data_block(
                "scenes",
                [
                    {
                        "index": index,
                        "start_s": scene.start_s,
                        "end_s": scene.end_s,
                        "quality": scene.quality.model_dump(),
                    }
                    for index, scene in enumerate(scenes)
                ],
            )
        )
        try:
            result: GenerateResult = ctx.gateway.describe_images(
                images,
                f"{system}\n\n{body}",
                namespace=f"video.understand:{ctx.context.get('asset_hash', 'nohash')}",
                json_mode=True,
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never invent
            logger.warning("video.understand: vision call failed: %s", exc)
            return {}, "unavailable", ["vision_call_failed"], 0

        captions, semantic, warnings = _parse_vision(result, len(scenes))
        if not semantic:
            # The provider answered with measurements but no semantics.
            return {}, "mocked", [*warnings, "vision_semantics_unavailable"], frames_used
        status = "mocked" if ctx.gateway.provider_name == "dev" else "real"
        return captions, status, warnings, frames_used


def _to_scenes(raw: Any, duration_s: float) -> list[Scene]:
    """Build scenes from the detector's output, dropping unusable entries."""
    scenes: list[Scene] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        try:
            quality_raw = entry.get("quality") or {}
            scene = Scene(
                start_s=float(entry.get("start_s", 0.0)),
                end_s=float(entry.get("end_s", 0.0)),
                quality=SceneQuality(
                    sharpness=float(quality_raw.get("sharpness", 0.5)),
                    brightness=float(quality_raw.get("brightness", 0.5)),
                    motion=float(quality_raw.get("motion", 0.0)),
                    score=float(quality_raw.get("score", 0.5)),
                ),
            )
        except Exception:  # noqa: BLE001 - a malformed scene is dropped, not fatal
            continue
        if scene.end_s > duration_s:
            scene.end_s = round(duration_s, 3)
        if scene.duration_s >= settings.scene_min_duration_s:
            scenes.append(scene)
    scenes.sort(key=lambda s: s.start_s)
    return scenes


def _frame_for(scene: Scene, frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The supplied frame closest to the scene midpoint."""
    midpoint = scene.start_s + scene.duration_s / 2
    usable = [f for f in frames if f.get("bytes")]
    if not usable:
        return None
    return min(usable, key=lambda f: abs(float(f.get("t_s", 0.0)) - midpoint))


def _sample_frames(frames: Any) -> list[dict[str, Any]]:
    """Enforce the documented frame cap before anything is sent to a provider."""
    usable = [f for f in (frames or []) if isinstance(f, dict) and f.get("bytes")]
    return usable[: settings.max_frames_analyzed]


def _parse_vision(
    result: GenerateResult, scene_count: int
) -> tuple[dict[int, dict[str, Any]], bool, list[str]]:
    """Read the provider's scene descriptions defensively.

    Providers return either `{semantic_available, frames:[...]}` (dev) or a bare
    list of `{index, caption, tags}`. Anything else is treated as no semantics.
    """
    warnings = [w for w in (result.warnings or []) if w != "dev_provider"]
    payload: Any = result.structured
    if payload is None:
        try:
            payload = json.loads(result.text or "{}")
        except json.JSONDecodeError:
            return {}, False, [*warnings, "vision_response_unparseable"]

    frames: list[Any]
    semantic = True
    if isinstance(payload, dict) and "frames" in payload:
        frames = list(payload.get("frames") or [])
        semantic = bool(payload.get("semantic_available", True))
    elif isinstance(payload, dict) and "scenes" in payload:
        frames = list(payload.get("scenes") or [])
    elif isinstance(payload, list):
        frames = payload
    else:
        return {}, False, [*warnings, "vision_response_unrecognised"]

    captions: dict[int, dict[str, Any]] = {}
    for position, entry in enumerate(frames[:scene_count]):
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        index = int(index) if isinstance(index, int) else position
        if not 0 <= index < scene_count:
            continue
        caption = str(entry.get("caption") or "").strip()
        tags = [str(t).strip().lower() for t in (entry.get("tags") or []) if str(t).strip()]
        if caption:
            captions[index] = {"caption": caption, "tags": tags[:8]}
    return captions, semantic, warnings


def _confidence(vision_status: str, scenes: list[Scene]) -> float:
    """Scene detection is deterministic, so only the captions add uncertainty."""
    if not scenes:
        return 0.0
    base = 0.75
    if vision_status == "mocked":
        base = 0.5
    elif vision_status == "unavailable":
        base = 0.4
    captioned = sum(1 for scene in scenes if scene.caption.strip())
    coverage = captioned / len(scenes)
    return round(min(base * (0.5 + 0.5 * coverage), 1.0), 3)


registry.register(SPEC, VideoUnderstandSkill)
