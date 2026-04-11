"""hybrid_search tests — keyword, vector, fusion, degraded path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from clawstu.memory.embeddings import DIM, NullEmbeddings
from clawstu.memory.pages import ConceptPage, LearnerPage
from clawstu.memory.search import hybrid_search
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
