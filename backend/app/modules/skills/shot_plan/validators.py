"""`shot.plan` validators (AI-SKILLS.md: "Σduration ≈ target; fields complete").

Timestamps here are *plan* time (seconds from the start of the final video), not
measurements of any existing asset, so the model may propose them and code must
check they add up (D-009 applies to measured media, not to a plan).
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.modules.skills.validators import register

#: AI-SKILLS.md: the sum of shot durations must land within this of the target.
TOTAL_TOLERANCE = 0.15
#: A plan with gaps cannot be cut against, so shots are made contiguous.
CONTIGUITY_TOLERANCE_S = 0.05
MAX_SHOTS = 40

REQUIRED_TEXT_FIELDS = ("framing", "action", "lighting")


@register("shots_sum_to_target")
def _shots_sum_to_target(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Compute the real sum, make shots contiguous, and close the gap to target."""
    shots = [s for s in (data.get("shots") or []) if isinstance(s, dict)]
    if not shots:
        data["warnings"] = list(data.get("warnings") or []) + ["no_shots_returned"]
        data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.3), 2)
        data["total_duration_s"] = 0.0
        return "no_shots_returned"

    if len(shots) > MAX_SHOTS:
        shots = shots[:MAX_SHOTS]
        data["warnings"] = list(data.get("warnings") or []) + [f"shots_capped_at_{MAX_SHOTS}"]

    shots.sort(key=lambda s: float(s.get("start_s", 0.0)))
    warnings: list[str] = _make_contiguous(shots)

    try:
        target = float(data.get("target_duration_s") or 0)
    except (TypeError, ValueError):
        target = 0.0

    total = round(sum(float(s["end_s"]) - float(s["start_s"]) for s in shots), 2)
    if target > 0 and total < target:
        # Extend the last shot: better a slightly long final beat than dead air.
        last = shots[-1]
        last["end_s"] = round(float(last["end_s"]) + (target - total), 2)
        warnings.append("final_shot_extended_to_target")
        total = round(sum(float(s["end_s"]) - float(s["start_s"]) for s in shots), 2)
    elif target > 0 and total > target * (1 + TOTAL_TOLERANCE):
        warnings.append(f"plan_exceeds_target_by_{round(total - target, 1)}s")

    for index, shot in enumerate(shots, start=1):
        shot["n"] = index

    data["shots"] = shots
    data["total_duration_s"] = total
    return ", ".join(sorted(set(warnings))) if warnings else None


def _make_contiguous(shots: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    cursor = 0.0
    for shot in shots:
        start = float(shot.get("start_s", 0.0))
        end = float(shot.get("end_s", 0.0))
        if end <= start:
            end = start + 1.0
            warnings.append("zero_length_shot_extended")
        if abs(start - cursor) > CONTIGUITY_TOLERANCE_S:
            shot["contiguous"] = False
            warnings.append("shot_timeline_gap_closed")
        shot["start_s"] = round(cursor, 2)
        shot["end_s"] = round(max(cursor + 0.2, end), 2)
        cursor = shot["end_s"]
    return warnings


@register("shots_fields_complete")
def _shots_fields_complete(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """A shot missing framing/action/lighting is not actionable for a creator."""
    incomplete = 0
    for shot in data.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        for field in REQUIRED_TEXT_FIELDS:
            if not str(shot.get(field) or "").strip():
                shot[field] = "unspecified — confirm during recording"
                incomplete += 1
    if incomplete:
        data["warnings"] = list(data.get("warnings") or []) + [
            f"{incomplete}_shot_fields_filled_with_placeholder"
        ]
    return f"{incomplete}_shot_fields_filled" if incomplete else None


@register("shot_count_sane")
def _shot_count_sane(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Shot length drives perceived pacing; flag plans that cannot be cut."""
    shots = [s for s in (data.get("shots") or []) if isinstance(s, dict)]
    if len(shots) < 2:
        return None
    durations = [float(s["end_s"]) - float(s["start_s"]) for s in shots]
    avg = sum(durations) / len(durations)
    if avg > 6.0:
        data["warnings"] = list(data.get("warnings") or []) + [
            f"average_shot_length_{avg:.1f}s_is_slow_for_short_form"
        ]
        data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.6), 2)
        return "average_shot_too_long"
    if avg < 0.6:
        return "average_shot_very_fast"
    return None


@register("recording_checklist_present")
def _recording_checklist_present(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """`recording.coach` depends on this block; keep it usable."""
    checklist = data.get("checklist")
    if isinstance(checklist, dict) and checklist:
        return None
    floor = settings.recording_floor_m
    data["checklist"] = {
        "props": ["tripod or stable surface"],
        "space": f"Clear {floor:.1f}m x {floor:.1f}m of floor, phone at chest height",
        "lighting": "One key light in front of the subject, no harsh backlight unless intended",
    }
    return "checklist_defaulted"
