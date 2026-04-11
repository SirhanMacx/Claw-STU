"""Shared helpers for scheduler task modules.

All tasks report their target learner in `TaskReport.learner_id_hash`
using the same 12-char sha256 slice used by `clawstu.memory.store`
(spec §4.6.2). Centralizing it here keeps the "plaintext ids never
end up in scheduler_runs" invariant a one-place change.

Tasks that operate globally (e.g. `prune_stale`) pass the sentinel
string `"*"` as `learner_id` and this helper maps that to `None`,
which is the value the admin route uses to render "global" in the
transparency dashboard.
"""

from __future__ import annotations

import hashlib
import time

_GLOBAL_LEARNER = "*"
_HASH_LEN = 12


def hash_learner_id(learner_id: str) -> str | None:
    """Return the short sha256 slice for `learner_id`, or `None` global.

    The sentinel `"*"` maps to `None` so the `TaskReport` records a
    global-task run without a learner key. Every other input is
    hashed; plaintext ids never cross this boundary.
    """
    if learner_id == _GLOBAL_LEARNER:
        return None
    digest = hashlib.sha256(learner_id.encode("utf-8")).hexdigest()
    return digest[:_HASH_LEN]


def elapsed_ms(start: float) -> int:
    """Return integer milliseconds since `start` (from `time.perf_counter`).

    Centralized because every task uses the same wall-clock measurement
    and reports it as `duration_ms`. Guaranteed non-negative — clock
    drift on `perf_counter` is not a concern in practice but the
    `max(0, …)` clamp keeps `TaskReport.duration_ms` well-formed.
    """
    return max(0, int((time.perf_counter() - start) * 1000))
