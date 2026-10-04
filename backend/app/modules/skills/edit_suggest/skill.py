"""`edit.suggest` (AI-SKILLS.md, PRD §5: trim/caption/reframe REAL, rest MOCKED)."""

from __future__ import annotations

from typing import Any

from app.ai.gateway.base import Message
from app.core.logging import get_logger
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.edit_suggest.schemas import EditSuggestOutput
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.spec import ModelRequirement, SkillSpec

logger = get_logger(__name__)

SPEC = SkillSpec(
    id="edit.suggest",
    name="Suggest edits",
    purpose="Produce an editable EDL plus real and advisory edit suggestions for a clip.",
    input_schema=dict,
    output_schema=EditSuggestOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.4),
    dependencies=("clip.generate",),
    permissions=("r:reference_dna", "w:edits"),
    failure_conditions=(
        "EDL range outside the clip -> clamped to the clip",
        "no video track -> confidence capped at 0.3",
        "model marks a MOCKED suggestion applied -> reset to unapplied",
    ),
    validation_rules=(
        "edl_ranges_within_clip",
        "edl_caption_ranges_valid",
        "edl_has_video_track",
        "edl_aspect_supported",
        "edl_version_sane",
        "suggestion_status_honest",
        "suggestion_ids_unique",
        "suggestions_cover_real_types",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Produce an EDL and edit suggestions for this clip.

{clip}

{script}

{reference}

Return the JSON object only."""


class EditSuggestSkill(SkillModule):
    spec = SPEC

    def run(self, payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
        system = load_prompt("edit_suggest/prompt.md")
        clip = {**(ctx.context.get("clip") or {}), **(payload or {})}
        script = ctx.context.get("script")
        reference = ctx.context.get("reference_dna")
        body = PROMPT_BODY.format(
            clip=ctx.data_block("clip", clip),
            script=ctx.data_block("script", script) if script else "No script supplied.",
            reference=(
                ctx.data_block("reference_dna", reference)
                if reference
                else "No Reference DNA supplied."
            ),
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))
        parsed, _ = ctx.gateway.generate_structured(
            messages,
            schema=EditSuggestOutput,
            namespace=f"edit.suggest:{clip.get('clip_id') or clip.get('id') or 'unknown'}",
        )
        return SkillResult.ok(parsed, confidence=parsed.confidence, warnings=[])


registry.register(SPEC, EditSuggestSkill)