"""Named validators for `video.understand`."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.skills.validators import register

logger = get_logger(__name__)


@register("scene_ranges_within_asset")
def scene_ranges_within_asset(payload: dict[str, Any], ctx: Any) -> str | None:
    """Clamp scenes to the asset and drop zero/negative-length entries."""
    duration = _asset_duration(payload, ctx)
    if duration is None:
        return "asset_duration_unknown_ranges_unverified"
    kept: list[dict[str, Any]] = []
    clamped = 0
    for scene in payload.get("scenes") or []:
        start = max(0.0, round(float(scene.get("start_s", 0.0)), 3))
        end = round(float(scene.get("end_s", 0.0)), 3)
        new_start, new_end = min(start, duration), min(end, duration)
        if new_start != start or new_end != end:
            clamped += 1
        if new_end - new_start < settings.scene_min_duration_s:
            continue
        scene["start_s"], scene["end_s"] = new_start, new_end
        kept.append(scene)
    payload["scenes"] = kept
    return "scene_ranges_clamped_to_asset" if clamped else None


@register("scene_count_within_cap")
def scene_count_within_cap(payload: dict[str, Any], ctx: Any) -> str | None:
    """VIDEO-PIPELINE.md §1 frame cap: never hand the model unbounded scenes."""
    scenes = payload.get("scenes") or []
    cap = settings.scene_max_count
    if len(scenes) > cap:
        # Keep the longest scenes: short ones rarely carry a usable clip.
        scenes.sort(key=lambda s: float(s.get("end_s", 0)) - float(s.get("start_s", 0)), reverse=True)
        payload["scenes"] = sorted(scenes[:cap], key=lambda s: float(s.get("start_s", 0)))
        return "scene_count_capped"
    return None


@register("scenes_contiguous")
def scenes_contiguous(payload: dict[str, Any], ctx: Any) -> str | None:
    """Scenes must tile the asset in order; gaps would hide footage from scoring."""
    scenes = payload.get("scenes") or []
    for previous, current in zip(scenes, scenes[1:], strict=False):
        if float(current["start_s"]) < float(previous["end_s"]) - 1e-6:
            return "scenes_overlap_or_unordered"
    return None


@register("captions_flagged_without_vision")
def captions_flagged_without_vision(payload: dict[str, Any], ctx: Any) -> str | None:
    """A caption must never outlive the vision call that produced it.

    `mocked` captions are kept but capped, because the dev provider describes
    real pixels without semantics and that is worth showing. `unavailable` means
    no vision call happened at all, so any caption is fabricated and is dropped.
    """
    status = payload.get("vision_status")
    scenes = payload.get("scenes") or []
    captioned = any(str(s.get("caption") or "").strip() for s in scenes)
    if status == "unavailable" and captioned:
        for scene in scenes:
            scene["caption"] = ""
            scene["tags"] = []
        payload["confidence"] = round(min(float(payload.get("confidence", 0.5)), 0.4), 3)
        return "captions_dropped_vision_unavailable"
    if status == "mocked":
        payload["confidence"] = round(min(float(payload.get("confidence", 0.5)), 0.5), 3)
    if not captioned:
        payload.setdefault("warnings", []).append("no_scene_captions")
        payload["confidence"] = round(min(float(payload.get("confidence", 0.5)), 0.4), 3)
    return None


@register("quality_scores_present")
def quality_scores_present(payload: dict[str, Any], ctx: Any) -> str | None:
    """`clip.generate` scores visual quality; a missing metric must not read as 0."""
    for scene in payload.get("scenes") or []:
        quality = scene.get("quality")
        if not isinstance(quality, dict) or "score" not in quality:
            return "scene_quality_missing_downstream_score_affected"
    return None


def _asset_duration(payload: dict[str, Any], ctx: Any) -> float | None:
    for candidate in (
        payload.get("duration_s"),
        (getattr(ctx, "context", None) or {}).get("duration_s"),
        ((getattr(ctx, "context", None) or {}).get("asset") or {}).get("duration_s"),
    ):
        if isinstance(candidate, (int, float)) and candidate > 0:
            return float(candidate)
    return None
