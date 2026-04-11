"""Task registry and metadata models (spec §4.7.2, §4.7.4).

A `TaskSpec` is the Phase 6 wire format between the scheduler and a
concrete task: a name, a cron string, an enabled flag, a short
description, and an async `run_fn` that takes a `ProactiveContext`
and a learner id and returns a `TaskReport`.

A `TaskRegistry` is a thin dict keyed by task name that lets the
runner ask "which tasks are enabled right now?" and lets tests
construct fake registries with a single `register()` call.

`default_registry()` returns the five-task registry the spec
mandates. The task SPEC constants are imported lazily inside the
function so importing `clawstu.scheduler.registry` does not pull in
every task's dependencies at import time — consumers that only need
`TaskRegistry` (e.g. tests that build their own registries) get a
lighter import.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from clawstu.scheduler.context import ProactiveContext


class TokenCost(BaseModel):
    """Provider token cost attached to a scheduler run.

    Phase 6 tasks that don't call an LLM leave this at the default
    `(0, 0)`. Tasks that do make LLM calls (currently only
    `dream_cycle`) fill it from the provider response when the
    provider exposes usage data.
    """

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0


TaskOutcome = Literal["success", "skipped_current", "failed"]


class TaskReport(BaseModel):
    """Structured outcome of one task run (spec §4.7.4).

    Every field is immutable. The runner takes the report, records it
    in `SchedulerRunStore`, and the `/admin/scheduler` route reads it
    back for the transparency dashboard.

    Attributes
    ----------
    task_name:
        Matches `TaskSpec.name`. Used as the primary key for joining
        scheduler runs against their task definition.
    learner_id_hash:
        A short hash of the learner id for tasks that operate on a
        single learner; `None` for global tasks like `prune_stale`.
        Plaintext learner ids never end up in `scheduler_runs`.
    outcome:
        One of `"success"`, `"skipped_current"`, or `"failed"`.
        `skipped_current` is the idempotent no-op path (e.g. an
        artifact already exists). `failed` is the exception path.
    duration_ms:
        Wall-clock duration of the run, integer milliseconds.
    token_cost:
        Provider token usage, if any.
    error_message:
        Populated only when `outcome == "failed"`.
    details:
        Task-specific auxiliary data (e.g. `pages_rewritten` for
        `dream_cycle`). Opaque to the runner and the admin route
        serializes it as-is.
    """

    model_config = ConfigDict(frozen=True)

    task_name: str
    learner_id_hash: str | None
    outcome: TaskOutcome
    duration_ms: int
    token_cost: TokenCost = Field(default_factory=TokenCost)
    error_message: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


TaskRunFn = Callable[[ProactiveContext, str], Awaitable[TaskReport]]


class TaskSpec(BaseModel):
    """Metadata for one scheduled task (spec §4.7.2).

    Attributes
    ----------
    name:
        Unique task key used by the registry and as the primary-key
        portion of `SchedulerRunStore` rows.
    cron:
        Standard 5-field cron string in local time (spec §4.7.5).
    enabled:
        When False, `TaskRegistry.list_enabled()` skips this spec so
        the runner does not add a job for it. Useful for operators
        who want to disable a task without deleting code.
    description:
        One-line human-readable summary. Surfaced in the admin route.
    run_fn:
        Async callable `(ctx, learner_id) -> TaskReport`. The runner
        awaits it once per scheduled tick.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    cron: str
    enabled: bool = True
    description: str
    run_fn: TaskRunFn


class TaskRegistry:
    """Dict of `TaskSpec` keyed by `name`.

    The runner asks the registry for `list_enabled()` once at startup
    to build its APScheduler job list. Tests construct empty
    registries and `register()` specs one at a time; the standard
    five-task bundle lives in `default_registry()`.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskSpec] = {}

    def register(self, spec: TaskSpec) -> None:
        """Add or overwrite a task spec by name."""
        self._tasks[spec.name] = spec

    def get(self, name: str) -> TaskSpec | None:
        """Return the spec for `name`, or `None` if absent."""
        return self._tasks.get(name)

    def list_enabled(self) -> list[TaskSpec]:
        """Return all enabled specs (stable insertion order)."""
        return [t for t in self._tasks.values() if t.enabled]

    def list_all(self) -> list[TaskSpec]:
        """Return every registered spec (stable insertion order)."""
        return list(self._tasks.values())


def default_registry() -> TaskRegistry:
    """Return the five-task registry the spec mandates (§4.7.5).

    Task modules are imported lazily so the module-level import of
    `clawstu.scheduler.registry` never triggers the transitive load
    of memory / orchestrator / persistence. Callers that only need
    the core types (e.g. unit tests for `TaskRegistry` itself) can
    skip this function and import the types directly.
    """
    from clawstu.scheduler.tasks.dream_cycle import SPEC as DREAM_SPEC
    from clawstu.scheduler.tasks.prepare_next_session import SPEC as PREP_SPEC
    from clawstu.scheduler.tasks.prune_stale import SPEC as PRUNE_SPEC
    from clawstu.scheduler.tasks.refresh_zpd import SPEC as ZPD_SPEC
    from clawstu.scheduler.tasks.spaced_review import SPEC as REVIEW_SPEC

    registry = TaskRegistry()
    for spec in (DREAM_SPEC, PREP_SPEC, REVIEW_SPEC, ZPD_SPEC, PRUNE_SPEC):
        registry.register(spec)
    return registry
