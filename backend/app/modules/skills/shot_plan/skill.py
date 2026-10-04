"""`shot.plan` (AI-SKILLS.md, MVP-SCOPE, REAL)."""

from __future__ import annotations

from app.ai.gateway.base import Message
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.script_generate.schemas import ScriptOutput
from app.modules.skills.shot_plan.schemas import ShotPlanOutput
from app.modules.skills.spec import ModelRequirement, SkillSpec

SPEC = SkillSpec(
    id="shot.plan",
    name="Plan shots",
    purpose="Turn a script into a contiguous, actionable shot list for the target duration.",
    input_schema=ScriptOutput,
    output_schema=ShotPlanOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.6),
    dependencies=("script.generate",),
    permissions=("r:reference_dna", "w:shot_plans"),
    failure_conditions=(
        "sum of shot durations != target -> final shot extended, warning recorded",
        "gaps in the timeline -> shots made contiguous",
        "incomplete shot fields -> placeholder text, warning recorded",
    ),
    validation_rules=(
        "shots_sum_to_target",
        "shots_fields_complete",
        "shot_count_sane",
        "recording_checklist_present",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Plan the shots for this script.

{intent}

{script}

{reference}

Return the JSON object only."""


class ShotPlanSkill(SkillModule):
    spec = SPEC

    def run(self, payload: ScriptOutput, ctx: SkillContext) -> SkillResult:
        system = load_prompt("shot_plan/prompt.md")
        intent = ctx.context.get("intent") or {}
        reference = ctx.context.get("reference_dna")
        try:
            target = float(ctx.context.get("target_duration_s") or payload.target_duration_s or 30)
        except (TypeError, ValueError):
            target = 30.0
        body = PROMPT_BODY.format(
            intent=ctx.data_block("intent", {**intent, "target_duration_s": target}),
            script=ctx.data_block("script", payload.model_dump()),
            reference=(
                ctx.data_block("reference_dna", reference)
                if reference
                else "No Reference DNA supplied; plan from the script alone."
            ),
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))
        parsed, _ = ctx.gateway.generate_structured(
            messages,
            schema=ShotPlanOutput,
            namespace=f"shot.plan:{intent.get('platform', 'unknown')}:{int(target)}",
        )
        parsed.target_duration_s = target
        return SkillResult.ok(parsed, confidence=parsed.confidence, warnings=[])


registry.register(SPEC, ShotPlanSkill)