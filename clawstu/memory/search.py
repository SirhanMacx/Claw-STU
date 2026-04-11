"""Hybrid keyword + vector search with Reciprocal Rank Fusion.

Spec reference: §4.3.4. RRF constant ``k=60`` matches the Claw-ED
pattern.

Algorithm
---------
1. **Pool** all pages for the learner via `BrainStore.list_for_learner`.
2. **Keyword rank**: tokenize the query into lowercased terms, count
   how many distinct terms appear in each page's compiled truth,
   normalize by the query term count. Higher is better.
3. **Vector rank**: if ``embeddings.is_ready()`` is True, encode the
   query and each page's compiled truth, compute cosine similarity,
   and rank descending. Higher is better.
4. **Reciprocal Rank Fusion**: combined score for each page is
   ``sum(1 / (k + rank_i))`` over each leg that ran, with ``k = 60``.
   Ties broken by keyword score (so the pure-keyword collapse is
   stable across runs).
5. Return the top ``top_k`` results, each wrapped in `SearchResult`
   with the page key, the combined RRF score, and the `BrainPage`
   itself.

Page key
--------
The page key is a stable string of the form ``<kind>:<id>`` where
``<id>`` is the subclass-specific id field (learner_id, concept_id,
...). Keys are unique within a learner because no single learner
has two pages of the same kind with the same id.

NullEmbeddings degraded path
----------------------------
When the active backend is `NullEmbeddings`, every page's compiled
truth encodes to the same zero vector, and the cosine-similarity
scores are either all zero or (formally) undefined (zero-length
vectors). `_cosine_similarity` is defensive — it returns 0.0 on a
zero-length vector — so the vector rank becomes uniform across
pages, the vector leg contributes a constant additive term to every
RRF score, and the final ordering is determined entirely by the
keyword leg. This is the exact "collapses to keyword-only" semantics
the spec documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from clawstu.memory.embeddings import Embeddings
from clawstu.memory.pages import (
    BrainPage,
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    SessionPage,
    SourcePage,
    TopicPage,
)
from clawstu.memory.store import BrainStore

RRF_K = 60  # reciprocal rank fusion constant

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class SearchResult:
    """One result row from `hybrid_search`."""

    page_key: str
    score: float
    page: BrainPage


def _page_key(page: BrainPage) -> str:
    """Return a ``<kind>:<id>`` string for a page.

    Used both for RRF merging (same key across keyword and vector
    legs) and for the `SearchResult.page_key` field returned to
    callers.
    """
    kind = page.kind.value
    if isinstance(page, LearnerPage):
        return f"{kind}:{page.learner_id}"
    if isinstance(page, ConceptPage):
        return f"{kind}:{page.concept_id}"
    if isinstance(page, SessionPage):
        return f"{kind}:{page.session_id}"
    if isinstance(page, SourcePage):
        return f"{kind}:{page.source_id}"
    if isinstance(page, MisconceptionPage):
        return f"{kind}:{page.misconception_id}"
    if isinstance(page, TopicPage):
        return f"{kind}:{page.topic_id}"
    raise TypeError(f"unsupported page type: {type(page).__name__}")


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on non-alnum-underscore."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _keyword_score(query_terms: set[str], page_text: str) -> float:
    """Fraction of distinct query terms present in ``page_text``."""
    if not query_terms:
        return 0.0
    page_tokens = set(_tokenize(page_text))
    matches = query_terms & page_tokens
    return len(matches) / len(query_terms)


def _cosine_similarity(
    a: NDArray[np.float32],
    b: NDArray[np.float32],
) -> float:
    """Cosine similarity, defensive against zero-length vectors."""
    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def _rank_by_score(
    items: list[tuple[str, float]],
) -> dict[str, int]:
    """Given ``[(key, score), ...]``, return a rank dict keyed by key.

    Rank 1 is the highest score. Ties are broken arbitrarily but
    deterministically by the order in ``items`` (caller controls the
    initial iteration order).
    """
    ordered = sorted(items, key=lambda pair: (-pair[1], pair[0]))
    return {key: idx + 1 for idx, (key, _) in enumerate(ordered)}


def hybrid_search(
    query: str,
    brain_store: BrainStore,
    learner_id: str,
    embeddings: Embeddings,
    top_k: int = 10,
) -> list[SearchResult]:
    """Hybrid keyword + vector retrieval with RRF fusion.

    Returns the top ``top_k`` pages tied to ``learner_id``, ranked
    by Reciprocal Rank Fusion of a keyword-match leg and an
    embeddings-based vector leg. If ``embeddings.is_ready()`` is
    False, the vector leg is skipped and the result is keyword-only.
    """
    pages = brain_store.list_for_learner(learner_id)
    if not pages:
        return []

    query_terms = set(_tokenize(query))
    keyed_pages: dict[str, BrainPage] = {_page_key(p): p for p in pages}

    # Keyword leg
    keyword_scores = [
        (key, _keyword_score(query_terms, page.compiled_truth))
        for key, page in keyed_pages.items()
    ]
    keyword_ranks = _rank_by_score(keyword_scores)

    # Vector leg (only if backend is ready AND produces any signal)
    vector_ranks: dict[str, int] | None = None
    if embeddings.is_ready():
        query_vec = embeddings.encode(query)
        page_texts = [page.compiled_truth for page in keyed_pages.values()]
        page_vecs = embeddings.encode_batch(page_texts)
        vector_scores = [
            (key, _cosine_similarity(query_vec, page_vecs[idx]))
            for idx, key in enumerate(keyed_pages.keys())
        ]
        # Degenerate case: the backend is "ready" but every page scores
        # identically (e.g., NullEmbeddings returns zero vectors, so
        # every cosine is 0.0). A uniform vector leg contributes only
        # the alphabetical tiebreaker of `_rank_by_score`, which would
        # inject noise into the keyword result. Skip it in that case so
        # the final ordering is driven by the keyword leg alone.
        unique_scores = {round(score, 9) for _, score in vector_scores}
        if len(unique_scores) > 1:
            vector_ranks = _rank_by_score(vector_scores)

    # RRF fusion
    keyword_score_map = dict(keyword_scores)
    fused: list[tuple[str, float]] = []
    for key in keyed_pages:
        rrf = 1.0 / (RRF_K + keyword_ranks[key])
        if vector_ranks is not None:
            rrf += 1.0 / (RRF_K + vector_ranks[key])
        fused.append((key, rrf))

    # Sort by RRF descending, tiebreak by keyword score (so the
    # degraded keyword-only path is stable across runs).
    fused.sort(key=lambda pair: (-pair[1], -keyword_score_map[pair[0]], pair[0]))
    top = fused[:top_k]
    return [
        SearchResult(
            page_key=key,
            score=score,
            page=keyed_pages[key],
        )
        for key, score in top
    ]
