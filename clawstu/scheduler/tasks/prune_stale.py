"""`prune_stale` task — close sessions idle longer than the cutoff.

Spec reference: §4.7.5 (cron `0 5 * * 0`).

Global task: `learner_id` is the sentinel `"*"` and is ignored. Walks
`persistence.sessions.list_all()` once a week and marks any session
whose `started_at` is older than `_CUTOFF_DAYS` days and whose phase
is not already `CLOSED` as `CLOSED`. Records the number of sessions
pruned in `TaskReport.details["pruned"]`.

This is the mop-up task: learners who abandon a session mid-way
eventually get them tidied up so the admin view doesn't accumulate
infinite "open" rows. It is the only Phase 6 task that writes to
`sessions` rather than reading from it.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from clawstu.engagement.session import SessionPhase
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import TaskReport, TaskSpec
from clawstu.scheduler.tasks._common import elapsed_ms, hash_learner_id

_TASK_NAME = "prune_stale"
_CRON = "0 5 * * 0"
_CUTOFF_DAYS = 30


async def run(ctx: ProactiveContext, learner_id: str) -> TaskReport:
    """Close every session older than the cutoff that isn't already closed.

    `learner_id` is accepted for signature parity with the per-learner
    tasks but ignored — this is a global sweep. The passed value is
    typically `"*"`, which `hash_learner_id` maps to `None` in the
    reported `learner_id_hash`.
    """
    start = time.perf_counter()
    cutoff = datetime.now(UTC) - timedelta(days=_CUTOFF_DAYS)
    pruned = 0
    sessions = ctx.persistence.sessions.list_all()
    for session in sessions:
        if session.phase is SessionPhase.CLOSED:
            continue
        if session.started_at >= cutoff:
            continue
        session.phase = SessionPhase.CLOSED
        ctx.persistence.sessions.upsert(session)
        pruned += 1
    return TaskReport(
        task_name=_TASK_NAME,
        learner_id_hash=hash_learner_id(learner_id),
        outcome="success",
        duration_ms=elapsed_ms(start),
        details={
            "pruned": pruned,
            "cutoff_days": _CUTOFF_DAYS,
            "sessions_scanned": len(sessions),
        },
    )


SPEC = TaskSpec(
    name=_TASK_NAME,
    cron=_CRON,
    description="Close sessions that have been idle longer than the cutoff.",
    run_fn=run,
)
