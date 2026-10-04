"""`hook.generate` validators (AI-SKILLS.md: "<= 12 words spoken / <= 3 s est.").

The word budget is the documented hard rule. Speaking rate is a configured
constant because it is measurement, not judgement (AGENTS.md §12: deterministic
parts belong in code, not prompts).
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.modules.skills.validators import register

#: AI-SKILLS.md: hooks longer than this are a failure, not a warning.
MAX_SPOKEN_WORDS = 12
#: AI-SKILLS.md: hooks must be deliverable within this many seconds.
MAX_SPOKEN_SECONDS = 3.0


@register("hook_spoken_length")
def _hook_spoken_length(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Enforce the spoken budget: both the word cap and the seconds cap.

    AI-SKILLS.md states two limits ("<=12 words / <=3s"). The tighter one wins:
    at the configured speaking rate a 12-word hook can exceed 3s, so the budget
    is derived from the slower of the two.
    """
    warnings: list[str] = []
    wps = settings.speech_words_per_second
    budget_words = MAX_SPOKEN_WORDS
    if wps > 0:
        budget_words = min(MAX_SPOKEN_WORDS, int(MAX_SPOKEN_SECONDS * wps))

    for hook in data.get("hooks") or []:
        if not isinstance(hook, dict):
            continue
        text = str(hook.get("text", ""))
        words = text.split()
        hook["word_count"] = len(words)
        hook["estimated_seconds"] = round(len(words) / wps, 2) if wps > 0 else 0.0
        if len(words) <= budget_words and hook["estimated_seconds"] <= MAX_SPOKEN_SECONDS:
            continue
        kept = words[:budget_words]
        hook["text"] = " ".join(kept)
        hook["word_count"] = len(kept)
        hook["estimated_seconds"] = round(len(kept) / wps, 2) if wps > 0 else 0.0
        # A hook we had to cut is weaker than one written to length.
        try:
            hook["score"] = round(min(float(hook.get("score", 0.6)), 0.5), 2)
        except (TypeError, ValueError):
            hook["score"] = 0.5
        warnings.append("hook_truncated_to_spoken_budget")

    if not data.get("hooks"):
        data["warnings"] = list(data.get("warnings") or []) + ["no_hooks_returned"]
        data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.3), 2)
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("hook_selection_in_range")
def _hook_selection_in_range(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    hooks = data.get("hooks") or []
    index = int(data.get("selected_index") or 0)
    if not hooks:
        data["selected_index"] = 0
        return "no_hooks_to_select"
    if not 0 <= index < len(hooks):
        data["selected_index"] = 0
        return "selected_index_reset"
    if all(float(h.get("score", 0.5)) == float(hooks[index].get("score", 0.5)) for h in hooks):
        data["selected_index"] = max(range(len(hooks)), key=lambda i: float(hooks[i].get("score", 0)))
    return None


@register("hook_scores_bounded")
def _hook_scores_bounded(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    for hook in data.get("hooks") or []:
        if not isinstance(hook, dict):
            continue
        try:
            score = float(hook.get("score", 0.5))
        except (TypeError, ValueError):
            score = 0.5
        hook["score"] = round(max(0.0, min(1.0, score)), 2)
    return data


@register("hook_no_empty_text")
def _hook_no_empty_text(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """An empty hook is a hard failure; drop it rather than show a blank card."""
    hooks = [h for h in (data.get("hooks") or []) if isinstance(h, dict)]
    kept = [h for h in hooks if str(h.get("text", "")).strip()]
    data["hooks"] = kept
    if len(kept) != len(hooks):
        return "empty_hook_dropped"
    return None
