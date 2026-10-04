"""Tests for `concept.generate` (AI-SKILLS.md, REAL).

No network: the deterministic dev provider backs the gateway (AGENTS.md §14).
"""

from __future__ import annotations

import pytest

from app.modules.skills.concept_generate.schemas import ConceptOutput
from app.modules.skills.concept_generate.validators import (
    EMBEDDING_SIMILARITY_THRESHOLD,
    LEXICAL_SIMILARITY_THRESHOLD,
)
from app.modules.skills.intent_analyze.schemas import (
    CreationIntent,
)
from tests.conftest import context_holder, run_validated


@pytest.fixture
def intent() -> CreationIntent:
    return CreationIntent(
        content_type="dance_video",
        platform="instagram_reels",
        duration_s=30,
        tone=["energetic"],
        style=["bold"],
        audience="fitness dancers on their phones",
    )


@pytest.fixture
def ctx(make_ctx):
    return make_ctx("concept.generate")


def test_returns_three_concepts_with_the_documented_fields(intent, ctx) -> None:
    output = ConceptOutput.model_validate(run_validated("concept.generate", intent, ctx).output)
    assert 3 <= len(output.concepts) <= 6
    for concept in output.concepts:
        assert concept.title
        assert concept.premise
        assert concept.why


def test_selection_points_at_a_real_concept(intent, ctx) -> None:
    output = ConceptOutput.model_validate(run_validated("concept.generate", intent, ctx).output)
    assert output.selected is not None
    assert 0 <= output.selected_index < len(output.concepts)


def test_embedding_probe_is_prepared_for_the_distinctness_check(intent, ctx) -> None:
    """AI-SKILLS.md defines distinctness as embedding similarity < 0.9."""
    from app.modules.skills.concept_generate.validators import SIMILARITY_METHOD_KEY

    run_validated("concept.generate", intent, ctx)
    assert ctx.context.get(SIMILARITY_METHOD_KEY) in ("embedding", "lexical")


def test_near_duplicate_concepts_are_dropped() -> None:
    from app.modules.skills.validators import get

    rule = get("concept_three_distinct")
    payload = {
        "concepts": [
            {"title": "Fast dance reel", "premise": "Open strong then reveal the dance.", "score": 0.8},
            {"title": "Quick dance reel", "premise": "Open strong then reveal the dance.", "score": 0.7},
            {"title": "Dance myth busted", "premise": "Claim dancers overtrain, then disprove it.", "score": 0.6},
        ],
        "selected_index": 0,
        "confidence": 0.8,
        "warnings": [],
    }
    warning = rule(payload, None)
    assert len(payload["concepts"]) == 2
    assert "near_duplicate_concept_dropped" in (warning or "")


def test_identical_embedding_vectors_are_treated_as_duplicates() -> None:
    """The documented rule, exercised directly: cosine >= 0.9 means duplicate."""
    from app.modules.skills.validators import get

    rule = get("concept_three_distinct")
    ctx = context_holder(
        concept_vectors=[[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        concept_similarity_method="embedding",
    )
    payload = {
        "concepts": [
            {"title": "One", "premise": "First premise here.", "score": 0.8},
            {"title": "Two", "premise": "Second premise here.", "score": 0.7},
            {"title": "Three", "premise": "Third premise here.", "score": 0.6},
        ],
        "selected_index": 0,
        "confidence": 0.8,
        "warnings": [],
    }
    rule(payload, ctx)
    assert len(payload["concepts"]) == 2
    assert EMBEDDING_SIMILARITY_THRESHOLD == 0.9


def test_too_few_concepts_lowers_confidence_and_warns() -> None:
    from app.modules.skills.validators import get

    rule = get("concept_three_distinct")
    payload = {
        "concepts": [{"title": "Only one", "premise": "A single premise here.", "score": 0.5}],
        "selected_index": 0,
        "confidence": 0.9,
        "warnings": [],
    }
    rule(payload, None)
    assert payload["confidence"] <= 0.45
    assert any("distinct_concepts" in w for w in payload["warnings"])


def test_lexical_fallback_threshold_is_reported_not_silent() -> None:
    """A weakened check must be visible in the warnings (AGENTS.md §23)."""
    from app.modules.skills.validators import get

    rule = get("concept_three_distinct")
    payload = {
        "concepts": [
            {"title": "A", "premise": "Totally different premise about cooking.", "score": 0.8},
            {"title": "B", "premise": "Another premise about winter cycling.", "score": 0.7},
            {"title": "C", "premise": "A third premise about pottery glazing.", "score": 0.6},
        ],
        "selected_index": 0,
        "confidence": 0.8,
        "warnings": [],
    }
    warning = rule(payload, None) or ""
    assert f"distinctness_checked_lexical_at_{LEXICAL_SIMILARITY_THRESHOLD}" in warning


def test_selection_index_is_reset_when_out_of_range() -> None:
    from app.modules.skills.validators import get

    rule = get("concept_selection_in_range")
    payload = {
        "concepts": [
            {"title": "A concept", "premise": "Premise one.", "score": 0.9},
            {"title": "B concept", "premise": "Premise two.", "score": 0.2},
        ],
        "selected_index": 7,
    }
    assert rule(payload, None) == "selected_index_reset"
    assert payload["selected_index"] == 0


def test_output_never_contains_identifiers(intent, ctx) -> None:
    """AI-SKILLS.md §11: skills must not invent ids; the service assigns them."""
    output = run_validated("concept.generate", intent, ctx).output
    assert not any(key.endswith("_id") or key == "id" for key in output)
