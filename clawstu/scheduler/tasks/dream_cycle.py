"""`dream_cycle` task — overnight compiled-truth rewrite.

Spec reference: §4.7.5 (cron `30 2 * * *`).

Wraps `clawstu.memory.dream.dream_cycle` (built in Phase 4) and adapts
the Phase 4 `Consolidator` Protocol onto a Phase 2 `ModelRouter`. The
memory layer cannot import from orchestrator (spec §4.1), so the
adapter lives here in the scheduler where both layers are in scope.

The task is intentionally defensive: any exception from the memory
cycle or the router is caught and reported as `outcome="failed"` with
the exception text. The scheduler never lets one task's failure crash
the whole runner.
"""

from __future__ import annotations

import time

from clawstu.memory.dream import dream_cycle as _memory_dream_cycle
from clawstu.orchestrator.providers import LLMMessage
from clawstu.orchestrator.router import ModelRouter
from clawstu.orchestrator.task_kinds import TaskKind
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import TaskReport, TaskSpec
from clawstu.scheduler.tasks._common import elapsed_ms, hash_learner_id

_TASK_NAME = "dream_cycle"
_CRON = "30 2 * * *"


class _RouterConsolidator:
    """Adapt `ModelRouter.for_task(DREAM_CONSOLIDATION)` to the memory-level
    `Consolidator` Protocol.

    The memory layer cannot import `ModelRouter`, so the adapter lives
    in scheduler. The memory protocol is narrow: a single async
    `consolidate(*, system, user) -> str` method that returns the
    rewritten compiled-truth paragraph. Any provider error here
    propagates up to `dream_cycle`, which already counts it under
    `DreamReport.errors` and continues on the next page.
    """

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def consolidate(self, *, system: str, user: str) -> str:
        provider, model = self._router.for_task(TaskKind.DREAM_CONSOLIDATION)
        response = await provider.complete(
            system=system,
            messages=[LLMMessage(role="user", content=user)],
            model=model,
        )
        return response.text


async def run(ctx: ProactiveContext, learner_id: str) -> TaskReport:
    """Run one dream cycle for `learner_id`.

    Returns a `TaskReport` with `outcome="success"` on the happy path
    and `outcome="failed"` (with `error_message`) if the memory cycle
    raises. Per-page provider errors inside the memory cycle are
    counted inside `DreamReport.errors` and do NOT mark the run as
    failed — a cycle that fails on some pages and succeeds on others
    is still a successful cycle.
    """
    start = time.perf_counter()
    consolidator = _RouterConsolidator(ctx.router)
    try:
        result = await _memory_dream_cycle(
            learner_id,
            consolidator,
            ctx.brain_store,
        )
    except Exception as exc:
        return TaskReport(
            task_name=_TASK_NAME,
            learner_id_hash=hash_learner_id(learner_id),
            outcome="failed",
            duration_ms=elapsed_ms(start),
            error_message=str(exc),
        )
    return TaskReport(
        task_name=_TASK_NAME,
        learner_id_hash=hash_learner_id(learner_id),
        outcome="success",
        duration_ms=elapsed_ms(start),
        details={
            "pages_rewritten": result.pages_rewritten,
            "pages_skipped": result.pages_skipped,
            "errors": result.errors,
            "gap_count": result.gap_count,
        },
    )


SPEC = TaskSpec(
    name=_TASK_NAME,
    cron=_CRON,
    description="Overnight rewrite of compiled-truth sections on brain pages.",
    run_fn=run,
)
