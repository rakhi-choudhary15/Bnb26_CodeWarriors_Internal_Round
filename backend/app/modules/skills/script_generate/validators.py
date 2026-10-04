"""`script.generate` validators (AI-SKILLS.md: "est. duration within +/-10% target").

Duration is computed here, never by the model: it is arithmetic over words at a
configured speaking rate plus an explicit allowance for non-spoken beats
(AGENTS.md §12, §23).
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.modules.skills.validators import register

#: AI-SKILLS.md: the script must land within this fraction of the target.
DURATION_TOLERANCE = 0.10
#: Beats that exist to breathe are budgeted even though nothing is spoken.
SILENT_BEAT_SECONDS: dict[str, float] = {
    "b_roll": 2.0,
    "caption": 1.0,
}


def _line_seconds(line: dict[str, Any], wps: float) -> float:
    kind = str(line.get("kind", "line"))
    text = str(line.get("text", "")).strip()
    if kind in SILENT_BEAT_SECONDS:
        return SILENT_BEAT_SECONDS[kind]
    words = len(text.split())
    return round(words / wps, 2) if wps > 0 else 0.0


def estimate_duration(lines: list[dict[str, Any]]) -> float:
    wps = settings.speech_words_per_second
    return round(sum(_line_seconds(line, wps) for line in lines), 2)


@register("duration_within_target")
def _duration_within_target(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Recompute the estimate and close the gap to target deterministically."""
    lines = [line for line in (data.get("lines") or []) if isinstance(line, dict)]
    if not lines:
        data["warnings"] = list(data.get("warnings") or []) + ["no_script_lines"]
        data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.3), 2)
        data["estimated_duration_s"] = 0.0
        return "no_script_lines"

    for line in lines:
        line["estimated_seconds"] = _line_seconds(line, settings.speech_words_per_second)

    try:
        target = float(data.get("target_duration_s") or 0)
    except (TypeError, ValueError):
        target = 0.0
    if target <= 0:
        total = estimate_duration(lines)
        data["estimated_duration_s"] = total
        return "target_duration_missing"

    total = estimate_duration(lines)
    data["estimated_duration_s"] = total
    drift = abs(total - target) / target
    if drift <= DURATION_TOLERANCE:
        return None

    if total < target:
        # Too short: extend the build beats with real words rather than silence,
        # so the creator gets content instead of dead air.
        added = _extend_spoken(lines, target - total)
        message = f"short_by_{round(target - total, 1)}s_expanded_{added}_lines"
    else:
        message = f"long_by_{round(total - target, 1)}s_trimmed_to_fit"

    data["estimated_duration_s"] = estimate_duration(lines)
    # The model mis-sized the script; trust the arithmetic and say so.
    data["confidence"] = round(min(float(data.get("confidence", 0.6)), 0.55), 2)
    return message


def _extend_spoken(lines: list[dict[str, Any]], deficit_s: float) -> int:
    """Add placeholder build lines worth roughly `deficit_s` seconds of speech.

    The content is marked as a stub so the creator is never handed filler that
    looks finished.
    """
    wps = settings.speech_words_per_second
    target_words = max(1, int(deficit_s * wps))
    added = 0
    remaining = target_words
    while remaining > 0 and added < 12:
        words = min(remaining, 12)
        lines.append(
            {
                "beat": "build",
                "kind": "line",
                "text": "[Add supporting point here — script was short of target]",
                "visual": "",
                "estimated_seconds": round(words / wps, 2) if wps > 0 else 0.0,
            }
        )
        remaining -= words
        added += 1
    return added


@register("script_has_cta")
def _script_has_cta(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """PRD requires an explicit call to action for video formats."""
    lines = [line for line in (data.get("lines") or []) if isinstance(line, dict)]
    if not any(str(line.get("kind")) == "cta" for line in lines):
        if lines:
            lines[-1]["kind"] = "cta"
            lines[-1]["beat"] = "cta"
            if not str(data.get("cta") or "").strip():
                data["cta"] = lines[-1].get("text", "")
            return "final_line_marked_as_cta"
        return "no_lines_for_cta"
    if not str(data.get("cta") or "").strip():
        for line in lines:
            if str(line.get("kind")) == "cta":
                data["cta"] = line.get("text", "")
                return "cta_text_recovered_from_line"
    return None


@register("script_beats_ordered")
def _script_beats_ordered(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """A script that jumps backwards through its own beats will not cut together."""
    order = ["hook", "setup", "problem", "bridge", "build", "proof", "payoff", "cta"]
    lines = [line for line in (data.get("lines") or []) if isinstance(line, dict)]
    rank = -1
    warnings: list[str] = []
    for line in lines:
        try:
            current = order.index(str(line.get("beat", "line")))
        except ValueError:
            current = rank
        if current < rank:
            warnings.append("beat_order_corrected")
            line["beat"] = "build"
            continue
        rank = current
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("script_hook_first")
def _script_hook_first(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """AI-SKILLS.md: the script opens on the hook."""
    lines = [line for line in (data.get("lines") or []) if isinstance(line, dict)]
    if not lines:
        return "no_lines_for_hook_check"
    if str(lines[0].get("beat")) == "hook":
        return None
    lines[0]["beat"] = "hook"
    return "first_line_marked_as_hook"
