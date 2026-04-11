"""Scheduler layer — proactive background tasks (spec §4.7).

The scheduler runs APScheduler's `AsyncIOScheduler` under the FastAPI
lifespan and dispatches five registered tasks on cron triggers. Each
task is a pure async function that takes a `ProactiveContext` and a
learner id and returns a `TaskReport`, which the runner persists via
`SchedulerRunStore` for the `/admin/scheduler` transparency view.

Public surface:

- `ProactiveContext` — DI bundle with router, brain store, persistence.
- `TaskSpec` / `TaskRegistry` — task metadata + registry.
- `TaskReport` — structured outcome of a single run.
- `default_registry()` — returns a registry containing all 5 Phase 6
  tasks (dream_cycle, prepare_next_session, spaced_review,
  refresh_zpd, prune_stale).
- `SchedulerRunner` — wraps `AsyncIOScheduler`, loads jobs from a
  registry, and records reports.

Layering: `clawstu.scheduler` may import from `clawstu.orchestrator`,
`clawstu.memory`, `clawstu.persistence`, and `clawstu.engagement` per
spec §4.1 and the `_ALLOWED["scheduler"]` entry in
`tests/test_hierarchy.py`. It must not import from `clawstu.api`.
"""

from __future__ import annotations

from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import (
    TaskRegistry,
    TaskReport,
    TaskRunFn,
    TaskSpec,
    TokenCost,
    default_registry,
)

__all__ = [
    "ProactiveContext",
    "TaskRegistry",
    "TaskReport",
    "TaskRunFn",
    "TaskSpec",
    "TokenCost",
    "default_registry",
]
