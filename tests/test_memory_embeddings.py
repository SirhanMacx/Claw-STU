"""Embeddings layer tests — NullEmbeddings + default factory.

Phase 4 ships with NullEmbeddings as the default backend; OnnxEmbeddings
is scaffolded but its bootstrap / encode / encode_batch methods raise
NotImplementedError. These tests cover the NullEmbeddings contract
(the only one that actually runs in Phase 4) and the default factory.
"""

from __future__ import annotations

import numpy as np

from clawstu.memory.embeddings import (
    DIM,
    Embeddings,
    NullEmbeddings,
    default_embeddings,
)


def test_null_embeddings_returns_zero_vector() -> None:
    emb = NullEmbeddings()
    vec = emb.encode("anything")
    assert vec.shape == (DIM,)
    assert vec.dtype == np.float32
    assert np.all(vec == 0.0)


def test_null_embeddings_is_ready() -> None:
    emb = NullEmbeddings()
    assert emb.is_ready() is True
    emb.bootstrap()
    # bootstrap is a no-op and should not change readiness.
    assert emb.is_ready() is True


def test_null_embeddings_batch_matches_dim() -> None:
    emb = NullEmbeddings()
    texts = ["one", "two", "three"]
    batch = emb.encode_batch(texts)
    assert batch.shape == (3, DIM)
    assert batch.dtype == np.float32
    assert np.all(batch == 0.0)


def test_default_embeddings_returns_null_embeddings_in_phase_4() -> None:
    emb = default_embeddings()
    assert isinstance(emb, NullEmbeddings)
    # Structural check that the returned object satisfies the Protocol.
    assert isinstance(emb, Embeddings)
