"""`concept.generate` validators (AI-SKILLS.md: "3 distinct (embedding sim < 0.9)").

Distinctness is measured on embeddings when the skill managed to embed the
concepts, which is the documented check. The lexical fallback exists so a local
or degraded embedding provider weakens the check instead of skipping it, and the
warning records which method actually ran.
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.skills.validators import register

#: AI-SKILLS.md: two concepts are duplicates when embedding similarity >= 0.9.
EMBEDDING_SIMILARITY_THRESHOLD = 0.9
#: Jaccard never reaches 0.9 on two-sentence concepts, so the lexical fallback
#: needs its own documented threshold. Chosen so "same premise, one word swapped"
#: is caught while genuinely different concepts survive.
LEXICAL_SIMILARITY_THRESHOLD = 0.75
MIN_CONCEPTS = 3

#: ctx.context keys the skill fills in so this rule can use real embeddings.
VECTORS_KEY = "concept_vectors"
SIMILARITY_METHOD_KEY = "concept_similarity_method"

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "that", "this",
    "your", "you", "how", "why", "what", "to", "of", "in", "on", "is", "it",
    "from", "at", "by", "we", "i", "my", "me", "make", "create", "video",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _lexical_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _embedding_similarity(vectors: list[list[float]]):
    """Build a pairwise-indexed similarity callable over precomputed vectors."""

    def similarity(_a: str, _b: str, *, i: int = 0, j: int = 0) -> float:
        if i >= len(vectors) or j >= len(vectors):
            return 0.0
        return _cosine(vectors[i], vectors[j])

    return similarity


def _drop_duplicates(
    concepts: list[dict[str, Any]],
    similarity: Any,
    threshold: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Greedily keep concepts whose similarity to every kept one is below threshold.

    The index handed to `similarity` is the concept's position in the *original*
    list, so precomputed embedding vectors stay aligned even after a drop.
    """
    kept: list[dict[str, Any]] = []
    kept_positions: list[int] = []
    warnings: list[str] = []
    for position, concept in enumerate(concepts):
        text = f"{concept.get('title', '')} {concept.get('premise', '')}"
        duplicate = False
        for kept_position, prior in zip(kept_positions, kept, strict=True):
            prior_text = f"{prior.get('title', '')} {prior.get('premise', '')}"
            try:
                score = similarity(text, prior_text, i=position, j=kept_position)
            except TypeError:
                score = similarity(text, prior_text)
            if score >= threshold:
                duplicate = True
                break
        if duplicate:
            concept["distinct"] = False
            warnings.append("near_duplicate_concept_dropped")
            continue
        kept.append(concept)
        kept_positions.append(position)
    return kept, warnings


@register("concept_three_distinct")
def _concept_three_distinct(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """Keep at least 3 distinct concepts; report honestly when it cannot."""
    concepts = [c for c in (data.get("concepts") or []) if isinstance(c, dict)]
    for concept in concepts:
        if not concept.get("premise"):
            concept["premise"] = "Stated premise was empty; withheld for review."
        if not concept.get("why"):
            concept["why"] = "No rationale supplied."

    vectors = ctx.context.get(VECTORS_KEY) if ctx else None
    method = ctx.context.get(SIMILARITY_METHOD_KEY) if ctx else None
    if vectors and len(vectors) == len(concepts):
        similarity: Any = _embedding_similarity(vectors)
        threshold = EMBEDDING_SIMILARITY_THRESHOLD
    else:
        similarity = _lexical_similarity
        threshold = LEXICAL_SIMILARITY_THRESHOLD
        method = "lexical"

    warnings: list[str] = []
    concepts, dropped = _drop_duplicates(concepts, similarity, threshold)
    warnings.extend(dropped)
    if method != "embedding":
        warnings.append(f"distinctness_checked_{method}_at_{threshold}")

    data["concepts"] = concepts

    if len(concepts) < MIN_CONCEPTS:
        data["warnings"] = list(data.get("warnings") or []) + [
            f"only_{len(concepts)}_distinct_concepts"
        ]
        data["confidence"] = round(min(float(data.get("confidence", 0.5)), 0.45), 2)
    return ", ".join(sorted(set(warnings))) if warnings else None


@register("concept_selection_in_range")
def _concept_selection_in_range(data: dict[str, Any], ctx: Any) -> dict[str, Any] | str:
    """`selected_index` must point at a concept that survived validation."""
    concepts = data.get("concepts") or []
    index = int(data.get("selected_index") or 0)
    if not concepts:
        data["selected_index"] = 0
        return "no_concepts_to_select"
    if not 0 <= index < len(concepts):
        data["selected_index"] = 0
        return "selected_index_reset"
    # Select the strongest concept when the model did not give a real preference.
    if all(float(c.get("score", 0.5)) == float(concepts[index].get("score", 0.5)) for c in concepts):
        best = max(range(len(concepts)), key=lambda i: float(concepts[i].get("score", 0)))
        data["selected_index"] = best
    return None


@register("concept_scores_bounded")
def _concept_scores_bounded(data: dict[str, Any], ctx: Any) -> dict[str, Any]:
    for concept in data.get("concepts") or []:
        if not isinstance(concept, dict):
            continue
        try:
            score = float(concept.get("score", 0.5))
        except (TypeError, ValueError):
            score = 0.5
        concept["score"] = round(max(0.0, min(1.0, score)), 2)
    return data
