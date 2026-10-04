"""`concept.generate` (AI-SKILLS.md, MVP-SCOPE, REAL)."""

from __future__ import annotations

from app.ai.gateway.base import Message
from app.core.logging import get_logger
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.concept_generate.schemas import ConceptOutput
from app.modules.skills.intent_analyze.schemas import CreationIntent
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.spec import ModelRequirement, SkillSpec

logger = get_logger(__name__)

SPEC = SkillSpec(
    id="concept.generate",
    name="Generate concepts",
    purpose="Produce three structurally distinct concept options and select one.",
    input_schema=CreationIntent,
    output_schema=ConceptOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.85),
    dependencies=("intent.analyze",),
    permissions=("r:creation_intents", "w:nodes"),
    failure_conditions=(
        "fewer than 3 distinct concepts -> confidence capped at 0.45 with warning",
        "provider unavailable -> dev provider concepts, fallback=true",
    ),
    validation_rules=(
        "concept_three_distinct",
        "concept_scores_bounded",
        "concept_selection_in_range",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Generate three concept options for this request.

{assets}

{style}

{payload}

Return the JSON object only."""


class ConceptGenerateSkill(SkillModule):
    spec = SPEC

    def run(self, payload: CreationIntent, ctx: SkillContext) -> SkillResult:
        system = load_prompt("concept_generate/prompt.md")
        assets = ctx.context.get("assets") or []
        body = PROMPT_BODY.format(
            assets=(
                ctx.data_block("assets", assets)
                if assets
                else "No assets supplied yet; assume generic B-roll of the stated subject."
            ),
            style=ctx.data_block("style", {"tone": payload.tone, "style": payload.style}),
            payload=ctx.data_block("intent", payload.model_dump()),
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))
        parsed, _ = ctx.gateway.generate_structured(
            messages,
            schema=ConceptOutput,
            namespace=f"concept.generate:{payload.platform}:{payload.content_type}",
        )
        _prepare_distinctness_probe(parsed, ctx)
        return SkillResult.ok(parsed, confidence=parsed.confidence, warnings=[])


def _prepare_distinctness_probe(output: ConceptOutput, ctx: SkillContext) -> None:
    """Embed the concepts so `concept_three_distinct` uses the documented check.

    Embedding failure is not fatal: the validator falls back to a lexical check
    and records that it did so.
    """
    from app.modules.skills.concept_generate.validators import (
        SIMILARITY_METHOD_KEY,
        VECTORS_KEY,
    )

    texts = [concept.embedding_text() for concept in output.concepts]
    if len(texts) < 2:
        return
    try:
        result = ctx.gateway.embed(texts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Concept embedding unavailable (%s); using lexical check", type(exc).__name__)
        ctx.context[SIMILARITY_METHOD_KEY] = "lexical"
        return
    if len(result.vectors) == len(texts):
        ctx.context[VECTORS_KEY] = [list(v) for v in result.vectors]
        ctx.context[SIMILARITY_METHOD_KEY] = "embedding"


registry.register(SPEC, ConceptGenerateSkill)