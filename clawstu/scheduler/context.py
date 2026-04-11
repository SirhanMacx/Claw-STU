"""`ProactiveContext` — the DI bundle handed to every scheduler task.

Spec reference: §4.7.3.

Every task run takes a `ProactiveContext` and never constructs its own
providers, brain store, or persistence. This lets tests fabricate a
context with in-memory doubles and exercise the full task body in
milliseconds — no network, no disk, no event loop.

The context is intentionally minimal: three dependencies that every
task of any flavor needs. Specialized data (e.g. the configured
crontab for a specific task) lives on the `TaskSpec`, not here.

The spec also mentions a `StructuredLogger` field; that abstraction is
not yet built, so each task uses the stdlib `logging` module directly.
This keeps Phase 6 self-contained and defers the logger discussion
until there is a real consumer for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from clawstu.memory.store import BrainStore
from clawstu.orchestrator.router import ModelRouter
from clawstu.persistence.store import AbstractPersistentStore


@dataclass
class ProactiveContext:
    """Dependency bundle passed to every scheduled task.

    Attributes
    ----------
    router:
        `ModelRouter` instance used by tasks that make LLM calls
        (currently: `dream_cycle`). Pure-Python tasks ignore it.
    brain_store:
        Atomic file-backed `BrainStore`, used by `dream_cycle` and
        (post-Phase 6) by warm-start priming.
    persistence:
        The shared `AbstractPersistentStore` — entity store surface
        exposed via `persistence.sessions`, `persistence.events`,
        `persistence.artifacts`, `persistence.zpd`, and
        `persistence.scheduler_runs`.
    """

    router: ModelRouter
    brain_store: BrainStore
    persistence: AbstractPersistentStore
