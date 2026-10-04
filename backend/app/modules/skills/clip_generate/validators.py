"""Named validators for `clip.generate`.

Ranges are the dangerous part: an out-of-range or overlapping candidate produces a
broken render, so these clamp and drop rather than warn.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.modules.skills.platform_specs import clamp_duration, get_spec
from app.modules.skills.validators import register


@register("clip_ranges_within_asset")
def clip_ranges_within_asset(payload: dict[str, Any], ctx: Any) -> str | None:
    duration = _asset_duration(payload, ctx)
    if duration is None:
        return "asset_duration_unknown_ranges_unverified"
    dropped = 0
    kept = []
    for clip in payload.get("clips") or []:
        start = max(0.0, round(float(clip.get("start_s", 0.0)), 3))
        end = round(float(clip.get("end_s", 0.0)), 3)
        start, end = min(start, duration), min(end, duration)
        if end <= start:
            dropped += 1
            continue
        clip["start_s"], clip["end_s"] = start, end
        kept.append(clip)
    payload["clips"] = kept
    return "clip_range_dropped" if dropped else None


@register("clip_durations_within_platform")
def clip_durations_within_platform(payload: dict[str, Any], ctx: Any) -> str | None:
    """VIDEO-PIPELINE.md: candidates must fit the target platform's bounds."""
    adjusted = 0
    for clip in payload.get("clips") or []:
        platform = str(clip.get("target_platform") or "instagram_reels")
        wanted = round(float(clip.get("end_s", 0)) - float(clip.get("start_s", 0)), 3)
        clamped = clamp_duration(platform, wanted)
        if abs(clamped - wanted) < 1e-6:
            continue
        # Shrink from the tail: the head carries the hook.
        clip["end_s"] = round(float(clip["start_s"]) + clamped, 3)
        adjusted += 1
    return "clip_duration_clamped_to_platform" if adjusted else None


@register("clips_do_not_overlap")
def clips_do_not_overlap(payload: dict[str, Any], ctx: Any) -> str | None:
    """Non-overlap is a documented validation rule, not an optimisation."""
    clips = sorted(payload.get("clips") or [], key=lambda c: float(c.get("start_s", 0)))
    kept: list[dict[str, Any]] = []
    dropped = 0
    for clip in clips:
        start = float(clip["start_s"])
        if kept and start < float(kept[-1]["end_s"]) - 1e-6:
            dropped += 1
            continue
        kept.append(clip)
    payload["clips"] = kept
    return "overlapping_clips_dropped" if dropped else None


@register("clips_above_threshold")
def clips_above_threshold(payload: dict[str, Any], ctx: Any) -> str | None:
    """AI-SKILLS.md failure condition: no clip above threshold is a valid result."""
    clips = payload.get("clips") or []
    kept = [c for c in clips if float(c.get("confidence", 0.0)) >= settings.clip_min_confidence]
    if len(kept) != len(clips):
        payload["clips"] = kept
        return "low_confidence_clips_dropped"
    if not kept:
        payload.setdefault("warnings", []).append("no_clip_above_threshold")
        payload["confidence"] = 0.0
    return None


@register("clip_ids_unique")
def clip_ids_unique(payload: dict[str, Any], ctx: Any) -> str | None:
    seen: set[str] = set()
    for clip in payload.get("clips") or []:
        base = str(clip.get("id") or "")
        candidate, suffix = base, 2
        while candidate in seen:
            candidate, suffix = f"{base}-{suffix}", suffix + 1
        seen.add(candidate)
        clip["id"] = candidate
    return None


@register("visual_only_confidence_capped")
def visual_only_confidence_capped(payload: dict[str, Any], ctx: Any) -> str | None:
    """AI-SKILLS.md: the dance-without-speech path is capped at 0.7 and flagged."""
    if not payload.get("visual_only"):
        return None
    for clip in payload.get("clips") or []:
        if float(clip.get("confidence", 0.0)) > settings.clip_visual_only_confidence_cap:
            clip["confidence"] = settings.clip_visual_only_confidence_cap
            clip["visual_only"] = True
    payload["confidence"] = round(
        min(float(payload.get("confidence", 0.0)), settings.clip_visual_only_confidence_cap), 3
    )
    payload.setdefault("warnings", []).append("visual_only_confidence_capped")
    return "visual_only_confidence_capped"


@register("reasons_present")
def reasons_present(payload: dict[str, Any], ctx: Any) -> str | None:
    """A candidate without a reason cannot be reviewed by a human."""
    missing = 0
    for clip in payload.get("clips") or []:
        if not str(clip.get("reason") or "").strip():
            clip["reason"] = "Candidate window scored above threshold; reason unavailable."
            missing += 1
    return "clip_reason_missing" if missing else None


def _asset_duration(payload: dict[str, Any], ctx: Any) -> float | None:
    for candidate in (
        payload.get("duration_s"),
        (getattr(ctx, "context", None) or {}).get("duration_s"),
        ((getattr(ctx, "context", None) or {}).get("asset") or {}).get("duration_s"),
    ):
        if isinstance(candidate, (int, float)) and candidate > 0:
            return float(candidate)
    return None


__all__ = [
    "clip_ranges_within_asset",
    "clip_durations_within_platform",
    "clips_do_not_overlap",
    "clips_above_threshold",
    "clip_ids_unique",
    "visual_only_confidence_capped",
    "reasons_present",
    "get_spec",
]
