"""`SchedulerRunner` — APScheduler wrapper for the Phase 6 task fleet.

Spec reference: §4.7.6.

The runner takes a `TaskRegistry` and a `ProactiveContext` at
construction time, builds an `AsyncIOScheduler`, and registers one
cron job per enabled `TaskSpec`. The job, when fired by APScheduler,
calls back into `_run_spec` which awaits the spec's `run_fn`,
captures the resulting `TaskReport`, and persists it via
`SchedulerRunStore.append`.

Lifecycle is managed by the FastAPI app via the lifespan context
manager (Phase 6 commit 4): `await runner.start()` on app startup,
`await runner.stop()` on app shutdown. The scheduler does NOT spin
up an event loop on its own — it inherits the FastAPI loop. This
means the runner is not safe to use outside an async context, but
that's not a constraint anyone hits in practice (uvicorn always
provides a loop).

Per-learner iteration is a Phase 6.5 concern. The Phase 6 runner
calls each spec's `run_fn` exactly once per scheduled tick with the
`"*"` learner sentinel. The five tasks themselves are tolerant of
this: `prune_stale` is genuinely global, the per-learner tasks treat
`"*"` as a degenerate-but-safe input (no-op for an unknown learner,
hashed sentinel in the report).

Type discipline note: APScheduler ships without a `py.typed` marker,
so its types are `Any` to mypy. The runner exposes a tight typed
shell — every public method has fully annotated signatures and the
internal `_scheduler` attribute is typed via assignment. Tests
construct a runner and read its `get_job_ids()` view; they do NOT
call `start()` because that would spawn an event loop the test
doesn't own.
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import TaskRegistry, TaskReport, TaskSpec

# Sentinel passed to per-learner task run_fns when the runner does not
# yet iterate active learners. Spec §4.7.6 calls this out as Phase 6.5
# work; until then, every tick fires a single global call per task.
_GLOBAL_LEARNER_SENTINEL = "*"

logger = logging.getLogger(__name__)


class SchedulerRunner:
    """Async cron runner that drives the Phase 6 task registry.

    Parameters
    ----------
    registry:
        The set of `TaskSpec` instances the runner should schedule.
        Disabled specs are skipped at job-load time, not at fire
        time, so flipping `TaskSpec.enabled` between instances takes
        effect on the next runner instance.
    context:
        The `ProactiveContext` passed to every task. Held for the
        lifetime of the runner.
    """

    def __init__(
        self,
        *,
        registry: TaskRegistry,
        context: ProactiveContext,
    ) -> None:
        self._registry = registry
        self._context = context
        # APScheduler's AsyncIOScheduler is constructed unstarted.
        # Calling .start() requires a running event loop; tests skip
        # that step entirely. The scheduler is typed Any below to
        # appease mypy strict mode without scattering # type: ignore
        # comments — the public surface of SchedulerRunner is the
        # tight type contract.
        self._scheduler: Any = AsyncIOScheduler()
        self._load_jobs()

    # -- public API ----------------------------------------------------

    async def start(self) -> None:
        """Start the underlying scheduler.

        Must be called from inside a running asyncio event loop. The
        FastAPI lifespan context manager handles this for production;
        tests do not call it.
        """
        self._scheduler.start()

    async def stop(self) -> None:
        """Stop the scheduler without waiting for in-flight jobs.

        `wait=False` matches the spec's "stops cleanly when uvicorn
        stops" intent — uvicorn's shutdown is not blocked by tasks
        that may still be writing reports.
        """
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def get_job_ids(self) -> list[str]:
        """Return the job ids currently registered with APScheduler.

        Used by `tests/test_scheduler_runner.py` to verify the
        registry-to-jobs translation without running the scheduler.
        """
        return [job.id for job in self._scheduler.get_jobs()]

    @property
    def registry(self) -> TaskRegistry:
        """Expose the underlying registry for the admin route."""
        return self._registry

    @property
    def context(self) -> ProactiveContext:
        """Expose the bound context (lets the admin route reach
        `persistence.scheduler_runs` for the recent-runs view)."""
        return self._context

    # -- internal ------------------------------------------------------

    def _load_jobs(self) -> None:
        for spec in self._registry.list_enabled():
            self._scheduler.add_job(
                func=self._run_spec,
                trigger=CronTrigger.from_crontab(spec.cron),
                args=[spec.name],
                id=spec.name,
                name=spec.description,
                replace_existing=True,
            )

    async def _run_spec(self, task_name: str) -> None:
        """Execute one tick for `task_name` and persist the report.

        Wrapped in a broad try/except because APScheduler will not
        retry a failed job — we'd rather record a failed report than
        let an exception silently kill the job.
        """
        spec: TaskSpec | None = self._registry.get(task_name)
        if spec is None:
            logger.warning("scheduler tick for unknown task: %s", task_name)
            return
        try:
            report = await spec.run_fn(self._context, _GLOBAL_LEARNER_SENTINEL)
        except Exception as exc:  # pragma: no cover — defense in depth
            logger.exception("task %s raised", task_name)
            report = TaskReport(
                task_name=task_name,
                learner_id_hash=None,
                outcome="failed",
                duration_ms=0,
                error_message=str(exc),
            )
        self._record(report)

    def _record(self, report: TaskReport) -> None:
        self._context.persistence.scheduler_runs.append(
            task_name=report.task_name,
            learner_id_hash=report.learner_id_hash,
            outcome=report.outcome,
            duration_ms=report.duration_ms,
            token_cost_input=report.token_cost.input_tokens,
            token_cost_output=report.token_cost.output_tokens,
            error_message=report.error_message,
        )
