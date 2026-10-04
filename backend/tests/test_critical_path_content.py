"""Critical path: intent -> concept -> hook -> script -> shot plan -> caption -> platforms.

Each stage consumes the previous stage's validated output exactly as the workflow
engine does, so a contract break between stages fails here rather than in the UI.
"""

from __future__ import annotations

from app.modules.skills.caption_generate.schemas import CaptionOutput
from app.modules.skills.concept_generate.schemas import ConceptOutput
from app.modules.skills.hook_generate.schemas import HookOutput
from app.modules.skills.intent_analyze.schemas import (
    IntentAnalyzeInput,
    IntentAnalyzeOutput,
)
from app.modules.skills.platform_adapt.schemas import PlatformAdaptOutput
from app.modules.skills.platform_specs import PLATFORMS
from app.modules.skills.script_generate.schemas import ScriptOutput
from app.modules.skills.shot_plan.schemas import ShotPlanOutput
from tests.conftest import run_to_model

REEL = "30 second energetic dance reel for instagram"


def run_chain(request: str, *, make_ctx, details: str | None = None, platforms: list[str] | None = None) -> dict:
    ctx = make_ctx("intent.analyze")
    intent = run_to_model(
        "intent.analyze", IntentAnalyzeInput(primary_text=request, details_text=details), ctx, IntentAnalyzeOutput
    ).to_intent()

    concepts = run_to_model(
        "concept.generate",
        intent,
        make_ctx("concept.generate", intent=intent.model_dump()),
        ConceptOutput,
    )

    hooks = run_to_model(
        "hook.generate",
        concepts,
        make_ctx("hook.generate", intent=intent.model_dump(), concept=concepts.model_dump()),
        HookOutput,
    )

    script = run_to_model(
        "script.generate",
        hooks,
        make_ctx(
            "script.generate",
            intent=intent.model_dump(),
            concept=concepts.model_dump(),
            target_duration_s=intent.duration_s,
        ),
        ScriptOutput,
    )

    shot_plan = run_to_model(
        "shot.plan",
        script,
        make_ctx("shot.plan", intent=intent.model_dump(), target_duration_s=intent.duration_s),
        ShotPlanOutput,
    )

    caption = run_to_model(
        "caption.generate",
        script,
        make_ctx("caption.generate", intent=intent.model_dump()),
        CaptionOutput,
    )

    adapt = run_to_model(
        "platform.adapt",
        {},
        make_ctx(
            "platform.adapt",
            intent=intent.model_dump(),
            platforms=platforms or [intent.platform],
            script=script.model_dump(),
            master_duration_s=shot_plan.total_duration_s,
        ),
        PlatformAdaptOutput,
    )
    return {
        "intent": intent,
        "concepts": concepts,
        "hooks": hooks,
        "script": script,
        "shot_plan": shot_plan,
        "caption": caption,
        "adapt": adapt,
    }


def test_chain_produces_a_usable_reel(make_ctx) -> None:
    out = run_chain(REEL, make_ctx=make_ctx)
    assert out["intent"].platform == "instagram_reels"
    assert out["intent"].duration_s == 30
    assert out["concepts"].selected is not None
    assert out["hooks"].selected is not None
    assert out["script"].spoken_lines
    assert out["shot_plan"].shots
    assert out["caption"].caption.strip()


def test_hook_opens_the_script(make_ctx) -> None:
    out = run_chain(REEL, make_ctx=make_ctx)
    script = out["script"]
    assert script.lines[0].beat == "hook"
    assert script.lines[0].text.strip()


def test_script_lands_within_ten_percent_of_target(make_ctx) -> None:
    """AI-SKILLS.md `script.generate` key validation."""
    out = run_chain(REEL, make_ctx=make_ctx)
    script = out["script"]
    assert script.target_duration_s == 30
    assert script.duration_drift <= 0.10 + 1e-9, f"drift={script.duration_drift}"


def test_every_hook_fits_the_spoken_budget(make_ctx) -> None:
    """AI-SKILLS.md `hook.generate`: <=12 spoken words and <=3s estimated."""
    out = run_chain(REEL, make_ctx=make_ctx)
    for hook in out["hooks"].hooks:
        assert hook.word_count <= 12, hook.text
        assert hook.estimated_seconds <= 3.0 + 1e-9, hook.text


def test_script_ends_with_a_call_to_action(make_ctx) -> None:
    out = run_chain("45s product ad for our new wireless earbuds", make_ctx=make_ctx)
    script = out["script"]
    assert script.cta.strip()
    assert script.lines[-1].kind == "cta"


def test_shot_plan_tiles_the_full_duration(make_ctx) -> None:
    """AI-SKILLS.md `shot.plan`: Σduration ≈ target, shots are contiguous."""
    plan = run_chain(REEL, make_ctx=make_ctx)["shot_plan"]
    assert plan.shots[0].start_s == 0.0
    # `strict=False`: the last shot has no successor, which is the point here.
    for previous, following in zip(plan.shots, plan.shots[1:], strict=False):
        assert abs(previous.end_s - following.start_s) < 0.06
    assert abs(plan.total_duration_s - plan.target_duration_s) <= 0.5


def test_every_shot_is_actionable(make_ctx) -> None:
    plan = run_chain(REEL, make_ctx=make_ctx)["shot_plan"]
    for shot in plan.shots:
        assert shot.framing and shot.action and shot.lighting


def test_recording_checklist_feeds_the_coach(make_ctx) -> None:
    plan = run_chain(REEL, make_ctx=make_ctx)["shot_plan"]
    assert plan.checklist.get("space")
    assert plan.checklist.get("lighting")


def test_caption_respects_platform_limits(make_ctx) -> None:
    caption = run_chain(REEL, make_ctx=make_ctx)["caption"]
    limit = PLATFORMS[caption.platform].caption_chars
    assert len(caption.caption) <= limit
    assert all(tag.startswith("#") for tag in caption.hashtags)


def test_reels_variant_is_real_and_others_are_mocked(make_ctx) -> None:
    """MVP-SCOPE: Reels REAL, other platforms MOCKED metadata only."""
    out = run_chain(REEL, make_ctx=make_ctx, platforms=["instagram_reels", "youtube_shorts", "linkedin"])
    variants = {v.platform: v for v in out["adapt"].variants}
    assert set(variants) >= {"instagram_reels", "youtube_shorts", "linkedin"}
    assert variants["instagram_reels"].impl_status == "real"
    assert variants["instagram_reels"].render_capable is True
    for key in ("youtube_shorts", "linkedin"):
        assert variants[key].impl_status == "mocked"
        assert variants[key].render_capable is False


def test_non_vertical_variants_carry_reframe_instructions(make_ctx) -> None:
    out = run_chain(REEL, make_ctx=make_ctx, platforms=["youtube", "linkedin"])
    for variant in out["adapt"].variants:
        if variant.aspect != "9:16":
            assert variant.reframe_notes, f"{variant.platform} has no reframe notes"


def test_variant_durations_respect_each_ceiling(make_ctx) -> None:
    out = run_chain(REEL, make_ctx=make_ctx, platforms=["instagram_reels", "youtube_shorts"])
    for variant in out["adapt"].variants:
        assert variant.duration_s <= PLATFORMS[variant.platform].max_duration_s


def test_unsupported_platform_is_reported_not_invented(make_ctx) -> None:
    """AI-SKILLS.md `platform.adapt` key failure condition."""
    out = run_chain(REEL, make_ctx=make_ctx, platforms=["instagram_reels", "myspace_video"])
    keys = {v.platform for v in out["adapt"].variants}
    assert "myspace_video" not in keys
    assert keys == {"instagram_reels"}


def test_caps_stay_reported(make_ctx) -> None:
    out = run_chain("create a 180 second tutorial for youtube shorts", make_ctx=make_ctx)
    intent = out["intent"]
    assert intent.platform == "youtube_shorts"
    assert intent.duration_s == 60
    assert intent.confidence.duration_s <= 0.6
    assert any("clamped" in a.lower() for a in intent.assumptions)
