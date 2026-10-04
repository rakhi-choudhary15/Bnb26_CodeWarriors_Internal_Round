"""Tests for `video.understand` and `clip.generate` (VIDEO-PIPELINE.md §1-3).

Both skills decide which footage a creator sees, so the invariants that matter
are: source timestamps stay source timestamps, out-of-range ranges never survive,
and the no-speech path is flagged and capped rather than quietly confident.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.modules.skills.clip_generate.schemas import ClipGenerateOutput
from app.modules.skills.validators import get
from app.modules.skills.video_understand.schemas import VideoUnderstandOutput
from tests.conftest import context_holder, run_to_model

ASSET_DURATION_S = 96.0

SCENES = [
    {
        "start_s": 0.0,
        "end_s": 8.0,
        "caption": "Person at a desk with a laptop",
        "tags": ["talking_head"],
        "quality": {"sharpness": 0.7, "brightness": 0.6, "motion": 0.2, "score": 0.72},
    },
    {
        "start_s": 8.0,
        "end_s": 24.0,
        "caption": "Close-up of hands typing",
        "tags": ["b_roll"],
        "quality": {"sharpness": 0.5, "brightness": 0.5, "motion": 0.4, "score": 0.55},
    },
    {
        "start_s": 24.0,
        "end_s": 40.0,
        "caption": "Outdoor walking shot",
        "tags": ["b_roll", "outdoor"],
        "quality": {"sharpness": 0.3, "brightness": 0.8, "motion": 0.7, "score": 0.48},
    },
    {
        "start_s": 40.0,
        "end_s": 60.0,
        "caption": "Screen recording of a dashboard",
        "tags": ["screen_recording"],
        "quality": {"sharpness": 0.8, "brightness": 0.4, "motion": 0.1, "score": 0.66},
    },
    {
        "start_s": 60.0,
        "end_s": 96.0,
        "caption": "Person speaking to camera",
        "tags": ["talking_head", "outdoor"],
        "quality": {"sharpness": 0.75, "brightness": 0.65, "motion": 0.3, "score": 0.78},
    },
]

TRANSCRIPT = [
    {"start_s": 0.5, "end_s": 4.2, "text": "Nobody tells you this part."},
    {"start_s": 4.2, "end_s": 9.0, "text": "I wasted three months on it."},
    {"start_s": 20.0, "end_s": 27.5, "text": "Here is the part that actually worked."},
    {"start_s": 40.0, "end_s": 48.0, "text": "This dashboard shows the whole funnel."},
    {"start_s": 62.0, "end_s": 72.0, "text": "Try it on one video before you judge it."},
    {"start_s": 80.0, "end_s": 88.0, "text": "Link in the bio if you want the template."},
]


@pytest.fixture
def understand_ctx(make_ctx):
    return make_ctx("video.understand", duration_s=ASSET_DURATION_S, scenes=SCENES)


@pytest.fixture
def clip_ctx(make_ctx):
    return make_ctx(
        "clip.generate",
        duration_s=ASSET_DURATION_S,
        asset={"duration_s": ASSET_DURATION_S},
    )


def understood(ctx) -> VideoUnderstandOutput:
    payload = {
        "asset_id": "asset-1",
        "duration_s": ASSET_DURATION_S,
        "detected_scenes": SCENES,
        "has_speech": True,
    }
    return run_to_model("video.understand", payload, ctx, VideoUnderstandOutput)


def generated(ctx, **overrides) -> ClipGenerateOutput:
    payload = {
        "asset_id": "asset-1",
        "duration_s": ASSET_DURATION_S,
        "platform": "instagram_reels",
        "scenes": SCENES,
        "transcript": TRANSCRIPT,
        "intent": "A short story about a funnel dashboard mistake.",
        "reference_dna": {"preferred_clip_duration_s": 30},
        **overrides,
    }
    return run_to_model("clip.generate", payload, ctx, ClipGenerateOutput)


# ---------------------------------------------------------------------------
# video.understand
# ---------------------------------------------------------------------------
def test_scenes_keep_the_detector_boundaries(understand_ctx) -> None:
    scenes = understood(understand_ctx).scenes
    assert len(scenes) == len(SCENES)
    for produced, source in zip(scenes, SCENES, strict=True):
        assert produced.start_s == source["start_s"]
        assert produced.end_s == source["end_s"]


def test_scenes_are_ordered_and_non_overlapping(understand_ctx) -> None:
    scenes = understood(understand_ctx).scenes
    for previous, current in zip(scenes, scenes[1:], strict=False):
        assert current.start_s >= previous.end_s


def test_quality_metrics_are_carried_through(understand_ctx) -> None:
    scenes = understood(understand_ctx).scenes
    assert [s.quality.score for s in scenes] == [s["quality"]["score"] for s in SCENES]


def test_vision_status_is_reported_honestly_without_frames(understand_ctx) -> None:
    """No frames were supplied, so no caption may claim to come from vision."""
    result = understood(understand_ctx)
    assert result.vision_status == "unavailable"
    assert result.frames_analyzed == 0
    assert not result.has_captions
    assert "vision_frames_unavailable" in result.warnings
    assert result.confidence <= 0.4


def test_scene_range_validator_clamps_to_the_asset() -> None:
    rule = get("scene_ranges_within_asset")
    payload = {
        "duration_s": 30.0,
        "scenes": [
            {"start_s": 0.0, "end_s": 12.0},
            {"start_s": 28.0, "end_s": 400.0},
            {"start_s": 30.0, "end_s": 31.0},
        ],
    }
    rule(payload, context_holder(duration_s=30.0))
    kept = payload["scenes"]
    assert [s["end_s"] for s in kept] == [12.0, 30.0]
    assert len(kept) == 2


def test_scene_cap_keeps_the_longest_scenes() -> None:
    rule = get("scene_count_within_cap")
    scenes = [{"start_s": i, "end_s": i + 1} for i in range(settings.scene_max_count + 10)]
    scenes.append({"start_s": 500.0, "end_s": 540.0})
    payload = {"scenes": scenes}
    assert rule(payload, None) == "scene_count_capped"
    kept = payload["scenes"]
    assert len(kept) == settings.scene_max_count
    assert {"start_s": 500.0, "end_s": 540.0} in kept
    assert [s["start_s"] for s in kept] == sorted(s["start_s"] for s in kept)


def test_unavailable_vision_drops_fabricated_captions() -> None:
    rule = get("captions_flagged_without_vision")
    payload = {
        "vision_status": "unavailable",
        "confidence": 0.9,
        "scenes": [{"caption": "A cat playing piano", "tags": ["cat"]}],
    }
    assert rule(payload, None) == "captions_dropped_vision_unavailable"
    assert payload["scenes"][0]["caption"] == ""
    assert payload["confidence"] <= 0.4


def test_no_scenes_returns_an_empty_but_valid_result(make_ctx) -> None:
    """Neither the input nor the context carries detection output."""
    ctx = make_ctx("video.understand")
    payload = {
        "asset_id": "asset-1",
        "duration_s": ASSET_DURATION_S,
        "detected_scenes": [],
        "has_speech": True,
    }
    result = run_to_model("video.understand", payload, ctx, VideoUnderstandOutput)
    assert result.scenes == []
    assert result.confidence == 0.0
    assert "no_scenes_detected" in result.warnings


def test_detected_scenes_may_come_from_context(understand_ctx) -> None:
    """The Context Manager may supply detection output instead of the payload."""
    payload = {"asset_id": "asset-1", "duration_s": ASSET_DURATION_S}
    result = run_to_model("video.understand", payload, understand_ctx, VideoUnderstandOutput)
    assert len(result.scenes) == len(SCENES)


# ---------------------------------------------------------------------------
# clip.generate
# ---------------------------------------------------------------------------
def test_candidate_ranges_are_source_seconds_inside_the_asset(clip_ctx) -> None:
    for clip in generated(clip_ctx).clips:
        assert 0.0 <= clip.start_s < clip.end_s <= ASSET_DURATION_S


def test_clip_ids_are_derived_and_unique(clip_ctx) -> None:
    ids = [c.id for c in generated(clip_ctx).clips]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("clip_") for i in ids)


def test_candidates_do_not_overlap(clip_ctx) -> None:
    clips = sorted(generated(clip_ctx).clips, key=lambda c: c.start_s)
    for previous, current in zip(clips, clips[1:], strict=False):
        assert current.start_s >= previous.end_s


def test_clip_durations_fit_the_platform(clip_ctx) -> None:
    from app.modules.skills.platform_specs import get_spec

    spec = get_spec("instagram_reels")
    for clip in generated(clip_ctx).clips:
        assert spec.min_duration_s <= clip.duration_s <= spec.max_duration_s


def test_only_windows_in_the_documented_size_are_proposed(clip_ctx) -> None:
    for clip in generated(clip_ctx).clips:
        assert clip.duration_s >= 1.0


def test_every_candidate_carries_a_reviewable_reason(clip_ctx) -> None:
    for clip in generated(clip_ctx).clips:
        assert clip.reason.strip()


def test_confidence_is_never_above_the_threshold_gate(clip_ctx) -> None:
    for clip in generated(clip_ctx).clips:
        assert clip.confidence >= settings.clip_min_confidence - 1e-6


def test_mocked_relevance_embedding_is_disclosed(clip_ctx) -> None:
    """The dev provider's embeddings carry no semantics, so we must say so."""
    result = generated(clip_ctx)
    assert "relevance_embedding_mocked" in result.warnings


def test_visual_only_path_is_capped_and_flagged(clip_ctx) -> None:
    result = generated(clip_ctx, transcript=[])
    assert result.visual_only is True
    assert "no_speech_visual_weighting_applied" in result.warnings
    assert result.confidence <= settings.clip_visual_only_confidence_cap
    for clip in result.clips:
        assert clip.confidence <= settings.clip_visual_only_confidence_cap
        assert clip.visual_only is True


def test_no_speech_still_produces_candidates_from_visual_signals(clip_ctx) -> None:
    result = generated(clip_ctx, transcript=[])
    assert result.clips, "scenes alone must be enough to propose a clip"


def test_unsupported_platform_is_rejected(clip_ctx) -> None:
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        generated(clip_ctx, platform="tiktok-but-not-a-platform")


def test_asset_shorter_than_a_window_yields_no_candidates(clip_ctx) -> None:
    result = generated(clip_ctx, duration_s=5.0)
    assert result.clips == []
    assert result.candidates_considered == 0
    assert "no_candidate_windows" in result.warnings


def test_range_outside_asset_is_dropped() -> None:
    rule = get("clip_ranges_within_asset")
    payload = {
        "duration_s": 40.0,
        "clips": [
            {"id": "a", "start_s": 0.0, "end_s": 30.0},
            {"id": "b", "start_s": 35.0, "end_s": 400.0},
            {"id": "c", "start_s": 39.0, "end_s": 38.0},
        ],
    }
    rule(payload, context_holder(duration_s=40.0))
    ids = [c["id"] for c in payload["clips"]]
    assert ids == ["a", "b"]
    assert payload["clips"][1]["end_s"] == 40.0


def test_overlapping_candidates_are_removed() -> None:
    rule = get("clips_do_not_overlap")
    payload = {
        "clips": [
            {"id": "a", "start_s": 0.0, "end_s": 30.0},
            {"id": "b", "start_s": 20.0, "end_s": 50.0},
            {"id": "c", "start_s": 30.0, "end_s": 60.0},
        ]
    }
    assert rule(payload, None) == "overlapping_clips_dropped"
    assert [c["id"] for c in payload["clips"]] == ["a", "c"]


def test_low_confidence_candidates_are_dropped() -> None:
    rule = get("clips_above_threshold")
    payload = {
        "confidence": 0.8,
        "clips": [
            {"id": "a", "confidence": 0.9},
            {"id": "b", "confidence": 0.01},
        ],
    }
    assert rule(payload, None) == "low_confidence_clips_dropped"
    assert [c["id"] for c in payload["clips"]] == ["a"]


def test_windows_are_aligned_to_transcript_and_scene_boundaries(clip_ctx) -> None:
    """A window edge that matches no real boundary would cut mid-sentence."""
    from app.modules.skills.clip_generate.skill import _candidate_windows

    boundaries = {0.0, 96.0} | {0.5, 4.2, 9.0, 20.0, 27.5, 40.0, 48.0, 62.0, 72.0, 80.0, 88.0}
    boundaries |= {s["start_s"] for s in SCENES} | {s["end_s"] for s in SCENES}
    for window in _candidate_windows(ASSET_DURATION_S, TRANSCRIPT, SCENES):
        assert any(abs(window["start_s"] - b) < 1e-6 for b in boundaries)
        assert any(abs(window["end_s"] - b) < 1e-6 for b in boundaries)


def test_score_breakdown_weights_sum_to_one() -> None:
    from app.modules.skills.clip_generate.schemas import ScoreBreakdown
    from app.modules.skills.clip_generate.skill import _weighted

    total_weight = (
        settings.clip_weight_relevance
        + settings.clip_weight_hook
        + settings.clip_weight_visual_quality
        + settings.clip_weight_completeness
        + settings.clip_weight_dna_fit
    )
    assert round(total_weight, 6) == 1.0
    perfect = ScoreBreakdown(
        relevance=1.0, hook_strength=1.0, visual_quality=1.0, completeness=1.0, dna_fit=1.0
    )
    assert round(_weighted(perfect, has_speech=True), 6) == 1.0
    assert 0.0 <= _weighted(perfect, has_speech=False) <= 1.0
