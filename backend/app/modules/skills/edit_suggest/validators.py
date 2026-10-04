"""`edit.suggest` validators (AI-SKILLS.md: "EDL schema; ranges in clip").

VIDEO-PIPELINE.md §3 makes the EDL the render source of truth, so the compiler
downstream trusts it. Everything a malformed EDL could produce — out-of-range
in/out, a caption outside its track, a "real" music suggestion — is rejected or
downgraded here, before it can reach ffmpeg.
"""

from __future__ import annotations

from typing import Any

from app.modules.skills.edit_suggest.schemas import (
    MOCKED_SUGGESTION_TYPES,
    REAL_SUGGESTION_TYPES,
)
from app.modules.skills.validators import register

MIN_CLIP_S = 0.5
MAX_EDL_VERSION = 999


@register("edl_ranges_within_clip")
def _edl_ranges_within_clip(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Every source range must sit inside the clip being edited."""
    clip = ctx.context.get("clip") if ctx else None
    if not isinstance(clip, dict):
        return "clip_context_missing_ranges_unverified"
    clip_start = float(clip.get("start_s", 0.0))
    clip_end = float(clip.get("end_s", clip_start))
    if clip_end <= clip_start:
        return "clip_range_invalid"

    edl = data.get("edl")
    if not isinstance(edl, dict):
        return "edl_missing"

    warnings: list[str] = []
    video = (edl.get("tracks") or {}).get("video") or []
    for item in video:
        if not isinstance(item, dict):
            continue
        in_s = max(clip_start, float(item.get("in_s", clip_start)))
        out_s = min(clip_end, float(item.get("out_s", clip_end)))
        if out_s <= in_s:
            out_s = min(clip_end, in_s + 0.5)
            warnings.append("edl_range_collapsed")
        if in_s != float(item.get("in_s", in_s)) or out_s != float(item.get("out_s", out_s)):
            warnings.append("edl_range_clamped_to_clip")
        item["in_s"] = round(in_s, 2)
        item["out_s"] = round(out_s, 2)

    data["edl"] = edl
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("edl_caption_ranges_valid")
def _edl_caption_ranges_valid(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Captions are timeline-relative; they must not end before they start."""
    edl = data.get("edl")
    if not isinstance(edl, dict):
        return "edl_missing"
    warnings: list[str] = []
    captions = (edl.get("tracks") or {}).get("captions") or []
    kept: list[dict[str, Any]] = []
    for caption in captions:
        if not isinstance(caption, dict):
            continue
        start = float(caption.get("start_s", 0.0))
        end = float(caption.get("end_s", 0.0))
        if not str(caption.get("text") or "").strip():
            warnings.append("empty_caption_dropped")
            continue
        if end <= start:
            end = start + 1.2
            warnings.append("caption_range_fixed")
        caption["start_s"] = round(max(0.0, start), 2)
        caption["end_s"] = round(end, 2)
        kept.append(caption)
    tracks = edl.setdefault("tracks", {})
    tracks["captions"] = kept
    edl["tracks"] = tracks
    data["edl"] = edl
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("edl_has_video_track")
def _edl_has_video_track(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """An EDL with no video track cannot compile to a render."""
    edl = data.get("edl")
    if not isinstance(edl, dict):
        return "edl_missing"
    video = (edl.get("tracks") or {}).get("video") or []
    if not video:
        data["warnings"] = list(data.get("warnings") or []) + ["edl_has_no_video_track"]
        data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.3), 2)
        return "edl_has_no_video_track"
    return None


@register("suggestion_status_honest")
def _suggestion_status_honest(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """PRD §5: only trim/caption/reframe are executed; the rest are advisory.

    A MOCKED suggestion must never be marked `applied`, because nothing applied
    it. This is the check that stops the UI implying a render changed.
    """
    suggestions = [s for s in (data.get("suggestions") or []) if isinstance(s, dict)]
    warnings: list[str] = []
    for suggestion in suggestions:
        kind = str(suggestion.get("type", ""))
        expected = "real" if kind in REAL_SUGGESTION_TYPES else "mocked"
        suggestion["impl_status"] = expected
        if expected == "mocked":
            suggestion.setdefault("warnings", []).append("advisory_only_not_rendered")
            if suggestion.get("applied"):
                suggestion["applied"] = False
                warnings.append("mocked_suggestion_unapplied")
    data["suggestions"] = suggestions
    if data.get("edl") is not None:
        data["edl"]["suggestions"] = suggestions
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("suggestion_ids_unique")
def _suggestion_ids_unique(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """PATCH /api/edits/:id addresses suggestions by id; ids must be unique."""
    suggestions = [s for s in (data.get("suggestions") or []) if isinstance(s, dict)]
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for index, suggestion in enumerate(suggestions):
        suggestion_id = str(suggestion.get("id") or "") or f"s{index + 1}"
        if suggestion_id in seen:
            suggestion_id = f"{suggestion_id}_{index + 1}"
        seen.add(suggestion_id)
        suggestion["id"] = suggestion_id
        deduped.append(suggestion)
    data["suggestions"] = deduped
    if isinstance(data.get("edl"), dict):
        data["edl"]["suggestions"] = deduped
    return "suggestion_ids_deduplicated" if len(deduped) != len(suggestions) else None


@register("edl_version_sane")
def _edl_version_sane(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Versions are monotonic (AGENTS.md §15: versions are immutable)."""
    edl = data.get("edl")
    if not isinstance(edl, dict):
        return "edl_missing"
    try:
        version = int(edl.get("version", 1))
    except (TypeError, ValueError):
        version = 1
    if version < 1:
        edl["version"] = 1
        return "edl_version_reset"
    if version > MAX_EDL_VERSION:
        edl["version"] = MAX_EDL_VERSION
        return "edl_version_capped"
    return None


@register("edl_aspect_supported")
def _edl_aspect_supported(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """The render target is 9:16; anything else is not a Reels deliverable."""
    edl = data.get("edl")
    if not isinstance(edl, dict):
        return "edl_missing"
    if str(edl.get("aspect")) != "9:16":
        edl["aspect"] = "9:16"
        return "edl_aspect_forced_to_9_16"
    return None


@register("suggestions_cover_real_types")
def _suggestions_cover_real_types(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """A minimal plan should still trim, caption and reframe — those are REAL."""
    suggestions = [s for s in (data.get("suggestions") or []) if isinstance(s, dict)]
    if not suggestions:
        return "no_suggestions"
    present = {str(s.get("type")) for s in suggestions}
    missing = [t for t in ("trim", "caption", "reframe") if t not in present]
    if missing:
        return f"missing_real_suggestion_types:{','.join(missing)}"
    return None


__all__ = [
    "MOCKED_SUGGESTION_TYPES",
    "REAL_SUGGESTION_TYPES",
    "MAX_EDL_VERSION",
    "MIN_CLIP_S",
]
