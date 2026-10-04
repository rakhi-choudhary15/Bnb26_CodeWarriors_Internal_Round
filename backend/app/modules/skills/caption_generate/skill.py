"""`caption.generate` (AI-SKILLS.md, MVP-SCOPE, REAL)."""

from __future__ import annotations

from app.ai.gateway.base import Message
from app.modules.skills import registry
from app.modules.skills.base import SkillContext, SkillModule, SkillResult
from app.modules.skills.caption_generate.schemas import CaptionOutput
from app.modules.skills.platform_specs import get_spec
from app.modules.skills.prompt_loader import load_prompt
from app.modules.skills.script_generate.schemas import ScriptOutput
from app.modules.skills.spec import ModelRequirement, SkillSpec

SPEC = SkillSpec(
    id="caption.generate",
    name="Generate caption and metadata",
    purpose="Write caption, title, description, hashtags and thumbnail text for a platform.",
    input_schema=ScriptOutput,
    output_schema=CaptionOutput,
    model_requirements=ModelRequirement(capability="text", json_mode=True, temperature=0.7),
    dependencies=("script.generate",),
    permissions=("r:creator_dna", "w:variants"),
    failure_conditions=(
        "text exceeds platform limits -> trimmed by code, warning recorded",
        "unsupported platform -> falls back to instagram_reels",
    ),
    validation_rules=(
        "platform_caption_limits",
        "caption_first_line_is_the_hook",
        "caption_hashtags_present",
        "confidence_bounded",
    ),
    status="real",
)

PROMPT_BODY = """Write the publishable text for this video.

{intent}

{script}

{dna}

Return the JSON object only."""


class CaptionGenerateSkill(SkillModule):
    spec = SPEC

    def run(self, payload: ScriptOutput, ctx: SkillContext) -> SkillResult:
        system = load_prompt("caption_generate/prompt.md")
        intent = ctx.context.get("intent") or {}
        dna = ctx.context.get("creator_dna")
        # An unknown platform is a documented failure; resolve it before asking
        # the model so the prompt always describes a real target.
        try:
            platform = get_spec(str(intent.get("platform") or "instagram_reels")).key
        except Exception:  # noqa: BLE001
            platform = "instagram_reels"
        body = PROMPT_BODY.format(
            intent=ctx.data_block("intent", {**intent, "platform": platform}),
            script=ctx.data_block("script", payload.model_dump()),
            dna=ctx.data_block("creator_dna", dna) if dna else "",
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(ctx.messages(body))
        parsed, _ = ctx.gateway.generate_structured(
            messages,
            schema=CaptionOutput,
            namespace=f"caption.generate:{platform}",
        )
        parsed.platform = platform
        return SkillResult.ok(parsed, confidence=parsed.confidence, warnings=[])


registry.register(SPEC, CaptionGenerateSkill)