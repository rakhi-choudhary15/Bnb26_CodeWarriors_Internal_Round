"""Tests for `edit.suggest` and EDL invariants (VIDEO-PIPELINE.md §3).

The EDL is compiled into ffmpeg arguments downstream, so these tests treat it as
the trust boundary: anything that could produce a wrong frame or imply an edit
happened is checked here.
"""

from __future__ import annotations

import pytest

from app.modules.skills.edit_suggest.schemas import (
    MOCKED_SUGGESTION_TYPES,
    REAL_SUGGESTION_TYPES,
    EditSuggestOutput,
)
from app.modules.skills.validators import get
from tests.conftest import context_holder, run_to_model

CLIP = {"clip_id": "clip-1", "asset_id": "asset-abc", "start_s": 12.0, "end_s": 38.5}


@pytest.fixture
def ctx(make_ctx):
    return make_ctx(
        "edit.suggest",
        clip=CLIP,
        script={
            "lines": [
                {"beat": "hook", "text": "Nobody tells you this.", "kind": "line"},
                {"beat": "setup", "text": "Here is the setup.", "kind": "line"},
                {"beat": "build", "text": "This is the key step.", "kind": "line"},
            ]
        },
    )


def output(ctx) -> EditSuggestOutput:
    return run_to_model("edit.suggest", {}, ctx, EditSuggestOutput)


def test_edl_targets_nine_by_six(ctx) -> None:
    assert output(ctx).edl.aspect == "9:16"


def test_video_range_uses_source_timestamps_inside_the_clip(ctx) -> None:
    video = output(ctx).edl.tracks["video"]
    assert video
    for item in video:
        assert item["src_asset"] == CLIP["asset_id"]
        assert item["in_s"] >= CLIP["start_s"]
        assert item["out_s"] <= CLIP["end_s"]
        assert item["out_s"] > item["in_s"]


def test_captions_are_timeline_relative_and_readable(ctx) -> None:
    captions = output(ctx).edl.tracks.get("captions") or []
    assert captions
    for caption in captions:
        assert caption["end_s"] > caption["start_s"]
        assert caption["end_s"] - caption["start_s"] >= 1.0
        assert caption["text"].strip()


def test_real_suggestions_are_applied_and_mocked_ones_are_not(ctx) -> None:
    """PRD §5: only trim/caption/reframe execute; the rest are advisory text."""
    for suggestion in output(ctx).suggestions:
        if suggestion.type in REAL_SUGGESTION_TYPES:
            assert suggestion.impl_status == "real"
        else:
            assert suggestion.impl_status == "mocked"
            assert suggestion.applied is False


def test_suggestion_ids_are_unique(ctx) -> None:
    ids = [s.id for s in output(ctx).suggestions]
    assert len(ids) == len(set(ids))


def test_all_three_real_suggestion_types_are_present(ctx) -> None:
    present = {s.type for s in output(ctx).suggestions}
    assert {"trim", "caption", "reframe"} <= present
    assert present & set(MOCKED_SUGGESTION_TYPES)


def test_edl_without_a_video_track_is_refused() -> None:
    rule = get("edl_has_video_track")
    payload = {
        "edl": {"tracks": {"video": []}},
        "confidence": 0.9,
        "warnings": [],
    }
    assert rule(payload, None) == "edl_has_no_video_track"
    assert payload["confidence"] <= 0.3


def test_range_outside_the_clip_is_clamped() -> None:
    rule = get("edl_ranges_within_clip")
    payload = {
        "edl": {
            "tracks": {
                "video": [{"src_asset": "asset-abc", "in_s": 0.0, "out_s": 400.0}],
            }
        }
    }
    warning = rule(payload, context_holder(clip=CLIP))
    item = payload["edl"]["tracks"]["video"][0]
    assert item["in_s"] == 12.0
    assert item["out_s"] == 38.5
    assert "edl_range_clamped_to_clip" in (warning or "")


def test_missing_clip_context_is_reported_not_silently_assumed() -> None:
    rule = get("edl_ranges_within_clip")
    payload = {"edl": {"tracks": {"video": [{"in_s": 0.0, "out_s": 10.0}]}}}
    assert rule(payload, context_holder()) == "clip_context_missing_ranges_unverified"


def test_mocked_suggestion_cannot_stay_applied() -> None:
    """The check that stops the UI implying a render changed."""
    rule = get("suggestion_status_honest")
    payload = {
        "edl": {"suggestions": []},
        "suggestions": [
            {"id": "a", "type": "trim", "detail": "cut", "applied": True},
            {"id": "b", "type": "music", "detail": "add a beat", "applied": True},
        ],
    }
    warning = rule(payload, None)
    by_id = {s["id"]: s for s in payload["suggestions"]}
    assert by_id["a"]["applied"] is True
    assert by_id["b"]["applied"] is False
    assert by_id["b"]["impl_status"] == "mocked"
    assert "mocked_suggestion_unapplied" in (warning or "")


def test_status_is_derived_not_trusted() -> None:
    """A `music` suggestion claiming to be real is corrected, never honoured."""
    from app.modules.skills.edit_suggest.schemas import EditSuggestion

    suggestion = EditSuggestion.model_validate(
        {"id": "x", "type": "music", "detail": "d", "impl_status": "real", "applied": True}
    )
    assert suggestion.impl_status == "mocked"
    assert suggestion.applied is False

    real = EditSuggestion.model_validate(
        {"id": "y", "type": "trim", "detail": "d", "impl_status": "mocked", "applied": True}
    )
    assert real.impl_status == "real"
    assert real.applied is True


def test_aspect_is_forced_to_nine_by_six() -> None:
    rule = get("edl_aspect_supported")
    payload = {"edl": {"aspect": "16:9"}}
    assert rule(payload, None) == "edl_aspect_forced_to_9_16"
    assert payload["edl"]["aspect"] == "9:16"
