"""Intent Engine service (AI-ARCHITECTURE.md §2).

Rule-based post-processing lives here, not in the prompt: platform limits, stage
skill existence and template selection are decisions, and a model should not be
asked to make them.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.ai.gateway.base import get_gateway
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.core.models import CreationIntent as IntentRow
from app.modules.intent import repository
from app.modules.skills.base import SkillContext
from app.modules.skills.intent_analyze.schemas import (
    IntentAnalyzeInput,
    IntentAnalyzeOutput,
)
from app.modules.skills.platform_specs import get_spec
from app.modules.skills.registry import get_module, has_skill
from app.modules.skills.router import run_skill

logger = get_logger(__name__)

#: Stage names the Intent Engine may propose, mapped to the skill that runs them.
#: The model speaks in stage names because that is what a creator recognises;
#: only this table turns a name into something the router can execute.
STAGE_SKILLS: dict[str, str] = {
    "concept": "concept.generate",
    "concept_select": "concept.generate",
    "hook": "hook.generate",
    "hook_generate": "hook.generate",
    "script": "script.generate",
    "script_generate": "script.generate",
    "shot_plan": "shot.plan",
    "shots": "shot.plan",
    "footage_understanding": "video.understand",
    "video": "video.understand",
    "match": "clip.generate",
    "clips": "clip.generate",
    "editing": "edit.suggest",
    "edit": "edit.suggest",
    "platform_adaptation": "platform.adapt",
    "platform": "platform.adapt",
    "captions": "caption.generate",
    "caption": "caption.generate",
}

#: Stage names with no skill behind them. They become manual creator steps rather
#: than being dropped, because a human review gate is part of the product.
MANUAL_STAGES: frozenset[str] = frozenset({"review", "approval", "human_review"})

#: Fallback order per template, used when the proposal is empty or unusable.
TEMPLATES: dict[str, tuple[str, ...]] = {
    "talking_head": ("concept_select", "hook_generate", "script_generate", "shot_plan", "caption_generate"),
    "tutorial": ("concept_select", "hook_generate", "script_generate", "shot_plan", "caption_generate"),
    "story": ("concept_select", "hook_generate", "script_generate", "shot_plan", "caption_generate"),
    "product_demo": ("concept_select", "hook_generate", "script_generate", "shot_plan", "caption_generate"),
    "vlog": ("concept_select", "hook_generate", "script_generate", "caption_generate"),
    "interview": ("concept_select", "hook_generate", "script_generate", "caption_generate"),
    "short": ("hook_generate", "script_generate", "caption_generate"),
    "generic": ("concept_select", "hook_generate", "script_generate", "shot_plan", "caption_generate"),
}

#: The minimum a usable blueprint needs, whatever the model proposed.
REQUIRED_STAGES: tuple[str, ...] = ("hook.generate", "script.generate", "caption.generate")


def analyze(
    *,
    owner_id: uuid.UUID,
    project_id: uuid.UUID,
    primary_text: str,
    details_text: str | None,
    creator_dna: dict[str, Any] | None,
    db: Session,
) -> IntentRow:
    """Parse an intent, validate it against the real skill registry, persist it."""
    text = primary_text.strip()
    if len(text) < 5:
        raise ValidationError(
            "Describe what you want to make in a little more detail.",
            details={"field": "primary_text", "min_length": 5},
        )

    skill = get_module("intent.analyze")
    if skill is None:
        raise ValidationError("The Intent Engine is not available on this deployment.")

    ctx = SkillContext(
        owner_id=owner_id,
        project_id=project_id,
        step_id=None,
        skill_id="intent.analyze",
        gateway=get_gateway(),
        context={"creator_dna": creator_dna or {}},
    )
    # `run_skill` is the single entry point: it parses the typed input, runs the
    # validators and records the run. Going around it would skip all three.
    result = run_skill(
        "intent.analyze",
        IntentAnalyzeInput(
            primary_text=text, details_text=details_text, creator_dna=creator_dna
        ).model_dump(),
        ctx,
        db,
    )
    if result.status != "ok" or not result.output:
        raise ValidationError(
            "We could not understand that yet. Try adding a platform and a duration.",
            details={"warnings": result.warnings or [result.error]},
        )

    parsed = _post_process(result.output, result.warnings)
    return repository.create(
        db,
        owner_id=owner_id,
        project_id=project_id,
        primary_text=text,
        details_text=details_text,
        parsed=parsed,
        confidence=parsed.get("confidence", {}),
        parse_status="ready",
        fallback=bool(result.warnings),
    )


def _post_process(output: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """Apply the rule-based corrections the model is not allowed to make.

    Everything here is deterministic on purpose: platform limits, which stages
    exist, and what "done" means. Asking a model for any of it would make the
    same request produce different blueprints.
    """
    skill_output = IntentAnalyzeOutput.model_validate(output)
    intent = skill_output.to_intent()
    intent.apply_platform_limits()

    spec = get_spec(intent.platform)
    if intent.format == "video" and spec.aspect != "9:16":
        # Vertical video is the MVP target; another aspect is stated, never
        # silently rendered wrong.
        intent.assumptions.append(
            f"{spec.label} renders at {spec.aspect}; only 9:16 rendering is implemented."
        )
        intent.confidence.overall = min(intent.confidence.overall, 0.6)

    stages, needs_manual_review = _usable_stages(intent.stages, intent.content_type)
    if stages != intent.stages:
        intent.assumptions.append(
            f"Stage list adjusted to skills this deployment has: {', '.join(stages)}."
        )
    intent.stages = stages

    intent.expected_output = intent.expected_output or (
        f"A {spec.label} {intent.format} of about {intent.duration_s}s, captioned, "
        f"opening on a {spec.hook_window_s:g}s hook."
    )
    parsed = intent.model_dump(exclude={"primary_text", "details_text"})
    # Which stage template was actually applied. The UI shows it so a creator can
    # see why the stage list looks the way it does.
    parsed["template_key"] = template_key(intent.content_type)
    # Not part of the intent contract, but the UI needs it to decide whether to
    # ask for a human confirmation before running the workflow.
    parsed["manual_review"] = needs_manual_review
    # Warnings are advisory, so they travel alongside `parsed`, not inside it.
    parsed["warnings"] = [*skill_output.warnings, *warnings]
    return parsed


def _usable_stages(proposed: list[str], content_type: str) -> tuple[list[str], bool]:
    """Turn proposed stage names into runnable skill ids.

    Returns the skill ids in order, plus whether the creator asked for a manual
    review gate. Unknown names are dropped rather than guessed at: a stage that
    maps to nothing must not silently become a step that does the wrong thing.
    """
    fallback = TEMPLATES.get(content_type, TEMPLATES["generic"])
    ordered: list[str] = []
    manual = False
    for name in [*proposed, *fallback]:
        key = str(name).strip().lower()
        if key in MANUAL_STAGES:
            manual = True
            continue
        skill_id = STAGE_SKILLS.get(key)
        if skill_id is None and has_skill(key):
            # Already a skill id, e.g. from a re-analysis of a machine proposal.
            skill_id = key
        if skill_id is not None and has_skill(skill_id) and skill_id not in ordered:
            ordered.append(skill_id)
    for required in REQUIRED_STAGES:
        if required not in ordered:
            ordered.append(required)
    return ordered, manual


def template_key(content_type: str) -> str:
    return content_type if content_type in TEMPLATES else "generic"
