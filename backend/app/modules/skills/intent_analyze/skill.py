"""`intent.analyze` — the Intent Engine (PRD FR-2, MVP-SCOPE #2, REAL)."""

from __future__ import annotations

from app.ai.gateway.base import Message
from app.core.logging import get_logger
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.intent_analyze.schemas import (
    CreationIntent,
    IntentAnalyzeInput,
    IntentAnalyzeOutput,
)
from app.modules.skills.spec import ModelRequirement, SkillSpec

logger = get_logger(__name__)

PROMPT_PATH = "intent_analyze/prompt.md"

SPEC = SkillSpec(
    id="intent.analyze",
    name="Analyze creation intent",
    purpose="Turn a creator's plain-language request into a structured CreationIntent.",
    input_schema=IntentAnalyzeInput,
    output_schema=IntentAnalyzeOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.2),
    dependencies=(),
    permissions=("r:creator_dna", "w:creation_intents"),
    failure_conditions=(
        "ambiguous intent -> low confidence plus explicit assumptions",
        "provider unavailable -> deterministic fallback with fallback=true",
        "schema invalid after repair -> generic low-confidence intent",
    ),
    validation_rules=(
        "intent_enums",
        "intent_duration_clamp",
        "intent_skills_exist",
        "intent_stages_match_skills",
        "intent_assumptions_present",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Parse this creation request into a structured intent.

{registry}

{registry_hint}

{dna}

{payload}

Return the JSON object only."""


class IntentAnalyzeSkill(SkillModule):
    spec = SPEC

    def run(self, payload: IntentAnalyzeInput, ctx: SkillContext) -> SkillResult:
        from app.modules.skills.prompt_loader import load_prompt
        from app.modules.skills.registry import list_specs

        registry_ids = sorted(s.id for s in list_specs())
        registry_block = "\n".join(f"- {skill_id}" for skill_id in registry_ids)

        dna_block = ""
        if payload.creator_dna:
            # Creator DNA is ≤300 tokens of style guidance and never overrides an
            # explicit instruction (CREATOR-DNA.md §5).
            dna_block = ctx.data_block("creator_dna", payload.creator_dna)

        body = PROMPT_BODY.format(
            registry=ctx.data_block("skill_registry", registry_block),
            registry_hint="Only use skill ids from the list above.",
            dna=dna_block,
            payload=ctx.data_block(
                "input",
                {
                    "primary_text": payload.primary_text,
                    "details_text": payload.details_text,
                },
            ),
        )

        system = load_prompt(PROMPT_PATH)
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))

        try:
            parsed, result = ctx.gateway.generate_structured(
                messages,
                schema=IntentAnalyzeOutput,
                namespace=f"intent.analyze:{result_key(payload)}",
                hint=_output_hint(),
            )
        except Exception as exc:  # noqa: BLE001 - AI-ARCHITECTURE §2 fallback path
            logger.warning("intent.analyze falling back to deterministic parse: %s", type(exc).__name__)
            fallback = deterministic_fallback(payload)
            return SkillResult.ok(
                fallback,
                confidence=0.35,
                warnings=["fallback_deterministic_parse"],
            )

        intent = parsed.to_intent().apply_platform_limits()
        # `primary_text`/`details_text` are what the creator typed, not something
        # the model understood, so they are excluded from the understanding output.
        output = IntentAnalyzeOutput.model_validate(
            intent.model_dump(exclude={"primary_text", "details_text"})
        )
        return SkillResult.ok(
            output,
            confidence=intent.confidence.overall,
            warnings=[],
        )


def _output_hint() -> str:

    schema = IntentAnalyzeOutput.model_json_schema()
    # The wrapper schema is noise for the model; hand it the field list instead.
    field_lines = []
    for name, spec in schema.get("properties", {}).items():
        default = spec.get("default")
        field_lines.append(f'  "{name}": <{spec.get("type", "any")}> (default: {default!r})')
    return "{\n" + ",\n".join(field_lines) + "\n}"


def result_key(payload: IntentAnalyzeInput) -> str:
    from app.core.ids import short_hash

    return short_hash({"p": payload.primary_text, "d": payload.details_text})


def deterministic_fallback(payload: IntentAnalyzeInput) -> dict:
    """Offline/low-confidence path used when the provider is unreachable.

    This is a keyword parser, not a model: it is registered as part of the
    documented degradation path (AI-ARCHITECTURE.md §2 "Failure") and the intent
    is flagged `fallback: true` so the UI can ask the creator to confirm.
    """
    from app.ai.gateway.providers.dev_provider import DevProvider

    text = f"{payload.primary_text} {payload.details_text or ''}"
    result = DevProvider().generate(
        [Message(role="user", content=f"[task:intent.analyze]{text}")],
        model="dev",
        json_mode=True,
    )
    intent = CreationIntent.model_validate(result.structured or {})
    return intent.apply_platform_limits().model_dump()


registry.register(SPEC, IntentAnalyzeSkill)