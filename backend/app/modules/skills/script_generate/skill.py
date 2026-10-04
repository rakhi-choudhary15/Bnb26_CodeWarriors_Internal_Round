"""`script.generate` (AI-SKILLS.md, MVP-SCOPE, REAL)."""

from __future__ import annotations

from app.ai.gateway.base import Message
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.hook_generate.schemas import HookOutput
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.script_generate.schemas import ScriptOutput
from app.modules.skills.spec import ModelRequirement, SkillSpec

SPEC = SkillSpec(
    id="script.generate",
    name="Generate script",
    purpose="Write the beat-by-beat spoken script and CTA to fit the target duration.",
    input_schema=HookOutput,
    output_schema=ScriptOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.7),
    dependencies=("hook.generate",),
    permissions=("r:creator_dna", "w:scripts"),
    failure_conditions=(
        "estimated duration outside +/-10% of target -> lines adjusted, score capped 0.55",
        "no lines returned -> confidence capped at 0.3",
    ),
    validation_rules=(
        "script_hook_first",
        "script_beats_ordered",
        "script_has_cta",
        "duration_within_target",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Write the script that delivers this hook.

{hook}

{concept}

{intent}

{dna}

Return the JSON object only."""


class ScriptGenerateSkill(SkillModule):
    spec = SPEC

    def run(self, payload: HookOutput, ctx: SkillContext) -> SkillResult:
        system = load_prompt("script_generate/prompt.md")
        intent = ctx.context.get("intent") or {}
        concept = ctx.context.get("concept")
        dna = ctx.context.get("creator_dna")
        try:
            target = float(ctx.context.get("target_duration_s") or intent.get("duration_s") or 30)
        except (TypeError, ValueError):
            target = 30.0
        body = PROMPT_BODY.format(
            hook=ctx.data_block("hooks", payload.model_dump()),
            concept=ctx.data_block("concept", concept) if concept else "",
            intent=ctx.data_block("intent", {**intent, "target_duration_s": target}),
            dna=ctx.data_block("creator_dna", dna) if dna else "",
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))
        parsed, _ = ctx.gateway.generate_structured(
            messages,
            schema=ScriptOutput,
            namespace=f"script.generate:{intent.get('platform', 'unknown')}:{int(target)}",
        )
        parsed.target_duration_s = target
        return SkillResult.ok(parsed, confidence=parsed.confidence, warnings=[])


registry.register(SPEC, ScriptGenerateSkill)