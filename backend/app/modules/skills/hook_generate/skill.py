"""`hook.generate` (AI-SKILLS.md, MVP-SCOPE, REAL)."""

from __future__ import annotations

from app.ai.gateway.base import Message
from app.core.logging import get_logger
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.concept_generate.schemas import ConceptOutput
from app.modules.skills.hook_generate.schemas import HookOutput
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.spec import ModelRequirement, SkillSpec

logger = get_logger(__name__)

SPEC = SkillSpec(
    id="hook.generate",
    name="Generate hooks",
    purpose="Write short spoken hooks that earn the first seconds of attention.",
    input_schema=ConceptOutput,
    output_schema=HookOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.9),
    dependencies=("concept.generate",),
    permissions=("r:creator_dna", "w:hooks"),
    failure_conditions=(
        "hook exceeds 12 spoken words -> truncated to the budget, score capped",
        "no hooks returned -> confidence capped at 0.3",
    ),
    validation_rules=(
        "hook_no_empty_text",
        "hook_spoken_length",
        "hook_scores_bounded",
        "hook_selection_in_range",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Write opening hooks for this concept.

{concept}

{intent}

{dna}

Return the JSON object only."""


class HookGenerateSkill(SkillModule):
    spec = SPEC

    def run(self, payload: ConceptOutput, ctx: SkillContext) -> SkillResult:
        system = load_prompt("hook_generate/prompt.md")
        intent = ctx.context.get("intent") or {}
        dna = ctx.context.get("creator_dna")
        body = PROMPT_BODY.format(
            concept=ctx.data_block("concept", payload.model_dump()),
            intent=ctx.data_block("intent", intent),
            dna=ctx.data_block("creator_dna", dna) if dna else "",
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))
        parsed, _ = ctx.gateway.generate_structured(
            messages,
            schema=HookOutput,
            namespace=f"hook.generate:{intent.get('platform', 'unknown')}",
        )
        return SkillResult.ok(parsed, confidence=parsed.confidence, warnings=[])


registry.register(SPEC, HookGenerateSkill)