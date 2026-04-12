"""hybrid_search tests — keyword, vector, fusion, degraded path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from clawstu.memory.embeddings import DIM, NullEmbeddings
from clawstu.memory.pages import (
    BrainPage,
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    SessionPage,
    SourcePage,
    TopicPage,
)
from clawstu.memory.search import (
    _cosine_similarity,
    _keyword_score,
    _page_key,
    _rank_by_score,
    _tokenize,
    hybrid_search,
)
from clawstu.memory.store import BrainStore


class _FakeReadyEmbeddings:
    """Test double — deterministic per-text unit vectors.

    Produces a one-hot vector whose "hot" index depends on the hash
    of the text modulo DIM. This lets a test arrange query and pages
    to land on the same / different axis, giving controlled cosine
    similarity without a real model.
    """

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def _vec_for(text: str) -> NDArray[np.float32]:
        axis = hash(text) % DIM
        v = np.zeros(DIM, dtype=np.float32)
        v[axis] = 1.0
        return v

    def encode(self, text: str) -> NDArray[np.float32]:
        return self._vec_for(text)

    def encode_batch(self, texts: list[str]) -> NDArray[np.float32]:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            out[i] = self._vec_for(t)
        return out


class _DiverseScoreEmbeddings:
    """Test double that returns vectors with diverse cosine similarities.

    The query vector is always [1, 0, 0, ...]. Each page text receives
    a vector with a different angle, giving distinct cosine scores so
    the vector leg produces unique rankings (covers lines 185 and 193).
    """

    def is_ready(self) -> bool:
        return True

    def encode(self, text: str) -> NDArray[np.float32]:
        v = np.zeros(DIM, dtype=np.float32)
        v[0] = 1.0
        return v

    def encode_batch(self, texts: list[str]) -> NDArray[np.float32]:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for i in range(len(texts)):
            # Vary the angle: text 0 is closest, text N is farthest.
            out[i][0] = float(len(texts) - i)
            out[i][1] = float(i + 1)
        # Normalize each row to unit length.
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        out = out / np.where(norms == 0, 1.0, norms)
        return out


class _NotReadyEmbeddings:
    """is_ready=False variant so tests can exercise the degraded path."""

    def is_ready(self) -> bool:
        return False

    def encode(self, text: str) -> NDArray[np.float32]:  # pragma: no cover
        raise RuntimeError("should not be called")

    def encode_batch(
        self, texts: list[str]
    ) -> NDArray[np.float32]:  # pragma: no cover
        raise RuntimeError("should not be called")

    def bootstrap(self) -> None:  # pragma: no cover
        raise RuntimeError("should not be called")


@pytest.fixture
def populated_store(tmp_path: Path) -> BrainStore:
    store = BrainStore(tmp_path / "brain")
    store.put(
        LearnerPage(
            learner_id="l1",
            compiled_truth="Visual learner; prefers primary sources.",
        ),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="civil_war",
            compiled_truth="Causes and consequences of the civil war.",
        ),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="reconstruction",
            compiled_truth="Reconstruction amendments and their enforcement.",
        ),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="great_depression",
            compiled_truth="Unrelated twentieth century topic.",
        ),
        "l1",
    )
    return store


def test_hybrid_search_returns_empty_for_empty_store(tmp_path: Path) -> None:
    store = BrainStore(tmp_path / "empty")
    results = hybrid_search(
        "civil war", store, "l1", NullEmbeddings(), top_k=5
    )
    assert results == []


def test_hybrid_search_with_null_embeddings_is_driven_by_keyword(
    populated_store: BrainStore,
) -> None:
    # "civil war" query — only the civil_war concept page contains both
    # terms. The reconstruction page contains neither. The learner page
    # contains neither.
    results = hybrid_search(
        "civil war",
        populated_store,
        "l1",
        NullEmbeddings(),
        top_k=10,
    )
    assert len(results) == 4  # learner + 3 concepts
    assert results[0].page_key == "concept:civil_war"
    # Higher-scoring entry should come before pages with zero keyword
    # matches — the keyword score for pages with no match is 0, so
    # civil_war ranks strictly above them.
    top_keys = [r.page_key for r in results[:1]]
    assert top_keys == ["concept:civil_war"]


def test_hybrid_search_top_k_truncates(populated_store: BrainStore) -> None:
    results = hybrid_search(
        "reconstruction",
        populated_store,
        "l1",
        NullEmbeddings(),
        top_k=2,
    )
    assert len(results) == 2
    assert results[0].page_key == "concept:reconstruction"


def test_hybrid_search_degraded_path_with_not_ready_embeddings(
    populated_store: BrainStore,
) -> None:
    """When embeddings.is_ready() is False, encode() must NOT be called.

    The test double's encode methods raise if called, so the only way
    this test passes is if hybrid_search skips the vector leg entirely.
    """
    results = hybrid_search(
        "civil war",
        populated_store,
        "l1",
        _NotReadyEmbeddings(),
        top_k=5,
    )
    assert len(results) == 4
    assert results[0].page_key == "concept:civil_war"


def test_hybrid_search_rrf_fusion_with_ready_embeddings_preserves_keyword_top(
    populated_store: BrainStore,
) -> None:
    """With a 'ready' backend, RRF runs on both legs.

    The fake embeddings backend is deterministic but unrelated to the
    semantic content (hash-based one-hot), so the vector leg
    contributes a noise signal to the RRF. The keyword leg still
    determines which page ranks at the top for a keyword-obvious
    query.
    """
    results = hybrid_search(
        "civil war",
        populated_store,
        "l1",
        _FakeReadyEmbeddings(),
        top_k=10,
    )
    assert results[0].page_key == "concept:civil_war"


# -------------------------------------------------------------------
# _page_key coverage: lines 89-97 (SessionPage, SourcePage,
# MisconceptionPage, TopicPage, TypeError)
# -------------------------------------------------------------------


class TestPageKey:
    """Direct tests for _page_key covering each page type."""

    def test_session_page_key(self) -> None:
        page = SessionPage(
            session_id="sess1",
            learner_id="l1",
            compiled_truth="summary",
        )
        assert _page_key(page) == "session:sess1"

    def test_source_page_key(self) -> None:
        page = SourcePage(
            source_id="src1",
            title="A Source",
            age_bracket="middle",
            compiled_truth="text",
        )
        assert _page_key(page) == "source:src1"

    def test_misconception_page_key(self) -> None:
        page = MisconceptionPage(
            learner_id="l1",
            misconception_id="mc1",
            concept_id="c1",
            compiled_truth="wrong belief",
        )
        assert _page_key(page) == "misconception:mc1"

    def test_topic_page_key(self) -> None:
        page = TopicPage(
            learner_id="l1",
            topic_id="reform_movements",
            compiled_truth="cluster overview",
        )
        assert _page_key(page) == "topic:reform_movements"

    def test_unsupported_page_type_raises(self) -> None:
        """Line 97: TypeError for unknown page subclass.

        BrainPage itself is not matched by any isinstance check in
        _page_key, so instantiating the base class directly (with a
        valid PageKind) triggers the TypeError fall-through.
        """
        from clawstu.memory.pages.base import PageKind

        bare_page = BrainPage(
            kind=PageKind.LEARNER,
            compiled_truth="test",
        )
        # BrainPage is not LearnerPage, so isinstance(bare_page, LearnerPage)
        # is False even though kind=LEARNER. _page_key falls through all
        # branches and raises TypeError.
        with pytest.raises(TypeError, match="unsupported page type"):
            _page_key(bare_page)


# -------------------------------------------------------------------
# _keyword_score edge case: empty query (line 108)
# -------------------------------------------------------------------


def test_keyword_score_empty_query() -> None:
    """When query_terms is empty, _keyword_score returns 0.0."""
    assert _keyword_score(set(), "some text here") == 0.0


def test_keyword_score_partial_match() -> None:
    score = _keyword_score({"civil", "war", "causes"}, "civil war battles")
    assert 0.0 < score < 1.0
    assert score == pytest.approx(2.0 / 3.0)


def test_keyword_score_full_match() -> None:
    score = _keyword_score({"hello", "world"}, "hello world")
    assert score == 1.0


# -------------------------------------------------------------------
# hybrid_search with empty query triggers line 108
# -------------------------------------------------------------------


def test_hybrid_search_empty_query(populated_store: BrainStore) -> None:
    """An empty string query produces results with 0.0 keyword scores."""
    results = hybrid_search(
        "",
        populated_store,
        "l1",
        NullEmbeddings(),
        top_k=10,
    )
    # With an empty query every page gets keyword_score 0.0, so results
    # are still returned (RRF rank-based) but all keyword scores are 0.
    assert len(results) == 4


# -------------------------------------------------------------------
# hybrid_search with diverse vector scores (lines 185, 193)
# -------------------------------------------------------------------


def test_hybrid_search_diverse_vectors_activates_vector_leg(
    populated_store: BrainStore,
) -> None:
    """When embeddings produce diverse cosine scores, the vector leg
    participates in RRF (covering lines 185 and 193).

    The _DiverseScoreEmbeddings double returns distinct cosine
    similarities per page, so ``unique_scores`` has len > 1 and the
    vector_ranks dict is populated.
    """
    results = hybrid_search(
        "civil war",
        populated_store,
        "l1",
        _DiverseScoreEmbeddings(),
        top_k=10,
    )
    # All four pages should be returned.
    assert len(results) == 4
    # With both legs active, scores should be higher than pure keyword
    # RRF since there's an additive vector component.
    for r in results:
        # Each page should have a positive RRF score.
        assert r.score > 0.0


# -------------------------------------------------------------------
# hybrid_search with all page types in the store
# -------------------------------------------------------------------


def test_hybrid_search_indexes_all_page_types(tmp_path: Path) -> None:
    """Exercise _page_key for every page type through hybrid_search."""
    store = BrainStore(tmp_path / "brain")
    store.put(
        LearnerPage(
            learner_id="l1",
            compiled_truth="likes primary sources",
        ),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="revolution",
            compiled_truth="American revolution overview",
        ),
        "l1",
    )
    store.put(
        SessionPage(
            session_id="s1",
            learner_id="l1",
            compiled_truth="covered revolution in session",
        ),
        "l1",
    )
    store.put(
        MisconceptionPage(
            learner_id="l1",
            misconception_id="m1",
            concept_id="revolution",
            compiled_truth="confused revolution with civil war",
        ),
        "l1",
    )
    store.put(
        TopicPage(
            learner_id="l1",
            topic_id="founding_era",
            compiled_truth="revolution and constitution era",
        ),
        "l1",
    )
    results = hybrid_search(
        "revolution",
        store,
        "l1",
        NullEmbeddings(),
        top_k=10,
    )
    keys = {r.page_key for r in results}
    assert "concept:revolution" in keys
    assert "session:s1" in keys
    assert "misconception:m1" in keys
    assert "topic:founding_era" in keys


# -------------------------------------------------------------------
# Helpers: _tokenize, _rank_by_score, _cosine_similarity
# -------------------------------------------------------------------


def test_tokenize_basic() -> None:
    assert _tokenize("Hello World") == ["hello", "world"]


def test_tokenize_with_punctuation() -> None:
    assert _tokenize("can't stop!") == ["can", "t", "stop"]


def test_rank_by_score_ordering() -> None:
    items = [("a", 1.0), ("b", 3.0), ("c", 2.0)]
    ranks = _rank_by_score(items)
    assert ranks["b"] == 1
    assert ranks["c"] == 2
    assert ranks["a"] == 3


def test_cosine_similarity_identical() -> None:
    v = np.ones(DIM, dtype=np.float32)
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_zero_vector() -> None:
    v = np.ones(DIM, dtype=np.float32)
    z = np.zeros(DIM, dtype=np.float32)
    assert _cosine_similarity(v, z) == 0.0
    assert _cosine_similarity(z, z) == 0.0
