"""`refresh_zpd` task — rebuild ZPD estimates from the event history.

Spec reference: §4.7.5 (cron `0 4 * * *`).

Phase 6 ships a MINIMUM VIABLE implementation of this task. A fully
faithful rebuild would replay every `CALIBRATION_ANSWER` and
`CHECK_FOR_UNDERSTANDING` event back through the
`ZPDCalibrator.update_estimate` pipeline from a clean slate, but doing
that pedagogically-correctly requires a decision on whether the
replayed profile should start from the age-bracket default or from
the current recorded estimate. That decision is a Phase 7 concern.

What Phase 6 does:

1. Look up the learner profile. Return `failed` if absent.
2. Rehydrate the profile's ZPD and event sub-stores from persistence
   (same pattern as `AppState.get`).
3. Re-run the calibrator's `update_estimate` over every review event.
4. Persist the recomputed estimates via `ZPDStore.upsert_all`.

The recomputation uses the calibrator that engagement already trusts,
so there is no drift between what the session runner sees and what
the nightly task produces. The only simplification vs. the spec is
that the starting point for the replay is the learner's existing
estimates, not a reset. This matches what the session runner does
during a live session; the nightly task is essentially "pretend we
just replayed every event through the same code path."
"""

from __future__ import annotations

import time

from clawstu.profile.model import EventKind
from clawstu.profile.zpd import ZPDCalibrator
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import TaskReport, TaskSpec
from clawstu.scheduler.tasks._common import elapsed_ms, hash_learner_id

_TASK_NAME = "refresh_zpd"
_CRON = "0 4 * * *"

_REPLAY_KINDS = {
    EventKind.CALIBRATION_ANSWER,
    EventKind.CHECK_FOR_UNDERSTANDING,
}


async def run(ctx: ProactiveContext, learner_id: str) -> TaskReport:
    """Recompute ZPD estimates for `learner_id` from event history."""
    start = time.perf_counter()
    profile = ctx.persistence.learners.get(learner_id)
    if profile is None:
        return TaskReport(
            task_name=_TASK_NAME,
            learner_id_hash=hash_learner_id(learner_id),
            outcome="failed",
            duration_ms=elapsed_ms(start),
            error_message=f"no learner profile for {learner_id}",
        )

    # Rehydrate the substores so the calibrator sees a consistent view,
    # same pattern AppState.get uses when a session is brought back from
    # persistence.
    profile.zpd_by_domain = ctx.persistence.zpd.get_all(learner_id)
    profile.events = ctx.persistence.events.list_for_learner(learner_id)

    calibrator = ZPDCalibrator()
    replayed = 0
    for event in profile.events:
        if event.kind not in _REPLAY_KINDS:
            continue
        if event.correct is None:
            continue
        calibrator.update_estimate(
            profile, event.domain, correct=event.correct
        )
        replayed += 1

    ctx.persistence.zpd.upsert_all(learner_id, profile.zpd_by_domain)
    return TaskReport(
        task_name=_TASK_NAME,
        learner_id_hash=hash_learner_id(learner_id),
        outcome="success",
        duration_ms=elapsed_ms(start),
        details={
            "events_replayed": replayed,
            "domains_updated": len(profile.zpd_by_domain),
        },
    )


SPEC = TaskSpec(
    name=_TASK_NAME,
    cron=_CRON,
    description="Rebuild ZPD estimates from event history (MVP replay).",
    run_fn=run,
)
