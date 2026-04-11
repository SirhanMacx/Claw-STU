"""Embeddings layer — zero-vector default plus a Phase-6 ONNX scaffold.

Spec context
------------
Spec §4.3.3 specifies sentence-transformers/all-MiniLM-L6-v2 via ONNX
Runtime for 384-dim page-level embeddings, with a first-run bootstrap
that downloads the weights, verifies a SHA-256, and spawns an
InferenceSession in a background thread. The tests in §4.3 assume a
pre-placed dummy ONNX file mounted via ``STU_EMBEDDINGS_MODEL_DIR``.

Pragmatic Phase 4 scope
-----------------------
A real 90 MB ONNX download is infeasible for the test suite. Producing
a valid ONNX stub that matches the MiniLM input/output shape is
non-trivial and would bloat the repo for dubious value — the stub
still can't actually run inference on CPUs, so tests would still have
to mock the encoder output.

Phase 4 therefore ships the embeddings layer as an abstract surface
with **two** concrete implementations:

1. ``NullEmbeddings`` — the DEFAULT. Returns zero vectors. `is_ready`
   is ``True``, ``bootstrap`` is a no-op. This is what tests use and
   what production will use until Phase 6 wires real ONNX loading via
   the scheduler startup hook. The fact that vector search always
   returns empty in Phase 4 is fine — hybrid search collapses to
   keyword-only, which is the spec's explicitly documented degraded
   behavior ("If embeddings aren't ready yet, vector search returns
   empty and RRF degenerates to keyword-only").

2. ``OnnxEmbeddings`` — the REAL implementation, scaffolded but NOT
   tested in Phase 4. ``bootstrap`` raises ``NotImplementedError``
   because Phase 4 does not own the download + SHA verify + tokenizer
   load sequence; that code lands in Phase 6 alongside the scheduler
   startup hook that invokes it.

The ``default_embeddings()`` factory always returns ``NullEmbeddings``
in Phase 4 — Phase 6 will change it to return ``OnnxEmbeddings`` when
``STU_EMBEDDINGS_MODEL_DIR`` is set and bootstrap has succeeded.

Why the NullEmbeddings default is a legitimate deliverable
----------------------------------------------------------
The spec documents "degenerates to keyword-only" as the acceptable
degraded state. Phase 4 ships that degraded state as the default and
Phase 6 bolts the real path on top. The search layer is tested
against the NullEmbeddings contract; when Phase 6 swaps in
OnnxEmbeddings, the search code requires no changes because both
implementations satisfy the same ``Embeddings`` Protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray


@runtime_checkable
class Embeddings(Protocol):
    """Every embeddings backend satisfies this shape."""

    def is_ready(self) -> bool:
        """Return ``True`` when the backend can serve encode() calls.

        NullEmbeddings is always ready. OnnxEmbeddings is ready only
        after a successful bootstrap has loaded the ONNX session and
        tokenizer. Search code checks this before calling encode().
        """
        ...

    def encode(self, text: str) -> NDArray[np.float32]:
        """Encode a single string as a (DIM,) float32 vector."""
        ...

    def encode_batch(self, texts: list[str]) -> NDArray[np.float32]:
        """Encode N strings as an (N, DIM) float32 matrix."""
        ...

    def bootstrap(self) -> None:
        """Perform any one-time setup (download weights, load session)."""
        ...


DIM = 384  # sentence-transformers/all-MiniLM-L6-v2 output dimension


class NullEmbeddings:
    """Zero-vector embeddings. Default Phase 4 backend.

    ``is_ready`` reports True so `hybrid_search` takes the vector
    branch — which is fine: the zero vectors produce uniform cosine
    scores, so the vector leg contributes a constant rank to every
    page and the final RRF ordering is determined entirely by the
    keyword leg. This is exactly what the spec wants for the "degraded
    to keyword-only" state.
    """

    def is_ready(self) -> bool:
        return True

    def encode(self, text: str) -> NDArray[np.float32]:
        return np.zeros(DIM, dtype=np.float32)

    def encode_batch(self, texts: list[str]) -> NDArray[np.float32]:
        return np.zeros((len(texts), DIM), dtype=np.float32)

    def bootstrap(self) -> None:
        """No-op — NullEmbeddings needs no setup."""


class OnnxEmbeddings:
    """ONNX-backed MiniLM embeddings (Phase 6 bootstrap path).

    Scaffolded in Phase 4 so the call sites in `search.py`, `context.py`,
    and the scheduler can be wired against the same interface. The
    ``bootstrap`` / ``encode`` / ``encode_batch`` bodies raise
    NotImplementedError and must not be called in Phase 4.

    Parameters
    ----------
    model_dir
        Directory that will contain ``model.onnx`` plus the tokenizer
        files (``tokenizer.json``, ``vocab.txt`` etc.). Phase 6's
        bootstrap downloads these from HuggingFace and verifies the
        SHA-256 against ``model.sha256`` before loading the ONNX
        Runtime InferenceSession.
    """

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._session: object | None = None
        self._tokenizer: object | None = None

    def is_ready(self) -> bool:
        return self._session is not None

    def encode(self, text: str) -> NDArray[np.float32]:
        if self._session is None:
            raise RuntimeError(
                "OnnxEmbeddings not bootstrapped; call bootstrap() first"
            )
        raise NotImplementedError("ONNX inference lands in Phase 6")

    def encode_batch(self, texts: list[str]) -> NDArray[np.float32]:
        if self._session is None:
            raise RuntimeError(
                "OnnxEmbeddings not bootstrapped; call bootstrap() first"
            )
        raise NotImplementedError("ONNX inference lands in Phase 6")

    def bootstrap(self) -> None:
        """Download + SHA-verify + load the ONNX session.

        Phase 4 stub: raises NotImplementedError. Phase 6's scheduler
        startup hook will implement the download/verify/load sequence
        specified in §4.3.3 and then call this method in a background
        thread.
        """
        raise NotImplementedError("ONNX bootstrap lands in Phase 6")


def default_embeddings() -> Embeddings:
    """Factory — always returns NullEmbeddings in Phase 4.

    Phase 6 will change this to respect the
    ``STU_EMBEDDINGS_MODEL_DIR`` environment variable: if set, the
    factory will return an OnnxEmbeddings backed by that directory
    after a successful bootstrap; otherwise it will still fall back
    to NullEmbeddings.
    """
    return NullEmbeddings()
