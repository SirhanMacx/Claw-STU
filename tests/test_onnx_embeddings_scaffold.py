"""Tests for OnnxEmbeddings scaffolded methods.

OnnxEmbeddings is intentionally not production-ready in Phase 4 --
bootstrap, encode, and encode_batch all raise NotImplementedError.
These tests document that contract so the scaffold is covered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstu.memory.embeddings import OnnxEmbeddings


def test_onnx_embeddings_not_ready_by_default(tmp_path: Path) -> None:
    emb = OnnxEmbeddings(model_dir=tmp_path)
    assert emb.is_ready() is False


def test_onnx_embeddings_bootstrap_raises(tmp_path: Path) -> None:
    emb = OnnxEmbeddings(model_dir=tmp_path)
    with pytest.raises(NotImplementedError, match="ONNX bootstrap"):
        emb.bootstrap()


def test_onnx_embeddings_encode_raises_when_not_bootstrapped(
    tmp_path: Path,
) -> None:
    emb = OnnxEmbeddings(model_dir=tmp_path)
    with pytest.raises(RuntimeError, match="not bootstrapped"):
        emb.encode("test")


def test_onnx_embeddings_encode_batch_raises_when_not_bootstrapped(
    tmp_path: Path,
) -> None:
    emb = OnnxEmbeddings(model_dir=tmp_path)
    with pytest.raises(RuntimeError, match="not bootstrapped"):
        emb.encode_batch(["a", "b"])
