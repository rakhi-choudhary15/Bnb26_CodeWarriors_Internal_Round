"""`platform.adapt` (AI-SKILLS.md: Reels REAL, others MOCKED)."""

from __future__ import annotations

from app.ai.gateway.base import Message
from app.core.logging import get_logger
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.platform_adapt.schemas import PlatformAdaptOutput
from app.modules.skills.platform_specs import PLATFORMS
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.spec import ModelRequirement, SkillSpec

logger = get_logger(__name__)

SPEC = SkillSpec(
    id="platform.adapt",
    name="Adapt to platforms",
    purpose="Produce per-platform variants with spec-correct limits and honest status.",
    input_schema=dict,
    output_schema=PlatformAdaptOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.6),
    dependencies=("edit.suggest", "script.generate"),
    permissions=("r:variants", "w:variants"),
    failure_conditions=(
        "unsupported platform -> dropped, fallback to instagram_reels with warning",
        "duration above platform ceiling -> clamped by code",
    ),
    validation_rules=(
        "variants_match_spec_table",
        "variant_duration_clamped",
        "variant_text_within_limits",
        "variant_reframe_notes_present",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Adapt this cut for each requested platform.

{spec_table}

{intent}

{source}

Return the JSON object only."""


class PlatformAdaptSkill(SkillModule):
    spec = SPEC

    def run(self, payload: dict, ctx: SkillContext) -> SkillResult:
        system = load_prompt("platform_adapt/prompt.md")
        intent = ctx.context.get("intent") or {}
        requested = ctx.context.get("platforms") or [intent.get("platform", "instagram_reels")]
        # Resolve the requested list against the spec table before prompting so
        # the model is never asked for a platform that does not exist.
        keys = [k for k in (str(p).strip().lower() for p in requested) if k in PLATFORMS]
        if not keys:
            keys = ["instagram_reels"]
        spec_table = {
            key: {
                "aspect": PLATFORMS[key].aspect,
                "width": PLATFORMS[key].width,
                "height": PLATFORMS[key].height,
                "max_duration_s": PLATFORMS[key].max_duration_s,
                "caption_chars": PLATFORMS[key].caption_chars,
                "hashtag_limit": PLATFORMS[key].hashtag_limit,
            }
            for key in keys
        }
        source = ctx.context.get("edit") or ctx.context.get("script") or {}
        try:
            master_duration = float(ctx.context.get("master_duration_s") or intent.get("duration_s") or 30)
        except (TypeError, ValueError):
            master_duration = 30.0

        body = PROMPT_BODY.format(
            spec_table=ctx.data_block("platform_specs", spec_table),
            intent=ctx.data_block("intent", {**intent, "master_duration_s": master_duration}),
            source=ctx.data_block("source", source),
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))
        parsed, _ = ctx.gateway.generate_structured(
            messages,
            schema=PlatformAdaptOutput,
            namespace=f"platform.adapt:{'-'.join(sorted(keys))}",
        )
        for variant in parsed.variants:
            if not variant.duration_s:
                variant.duration_s = min(
                    master_duration, float(PLATFORMS[variant.platform].max_duration_s)
                )
        return SkillResult.ok(parsed, confidence=parsed.confidence, warnings=[])


registry.register(SPEC, PlatformAdaptSkill)