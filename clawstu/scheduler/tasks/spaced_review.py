"""`spaced_review` task — identify concepts due for review.

Spec reference: §4.7.5 (cron `45 3 * * *`).

Pure-Python logic, no LLM calls. The task walks the learner's event
history, groups check-for-understanding / calibration events by
concept, and returns the set of concepts whose most-recent event is
older than the spaced-review cutoff (14 days by default).

Phase 6 just records the count in `TaskReport.details["stale_concept_count"]`
so the `/admin/scheduler` view can surface "Stuart flagged N concepts
for review tonight." A later phase will feed the list into the
`PathwayPlanner` so the next session automatically revisits stale
concepts before moving forward.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from clawstu.profile.model import EventKind
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import TaskReport, TaskSpec
from clawstu.scheduler.tasks._common import elapsed_ms, hash_learner_id

_TASK_NAME = "spaced_review"
_CRON = "45 3 * * *"
_STALE_CUTOFF_DAYS = 14

_REVIEW_KINDS = {
    EventKind.CHECK_FOR_UNDERSTANDING,
    EventKind.CALIBRATION_ANSWER,
}


async def run(ctx: ProactiveContext, learner_id: str) -> TaskReport:
    """Count stale concepts for `learner_id`.

    "Stale" means: the concept appears in at least one review-relevant
    event, and the most-recent such event is older than
    `_STALE_CUTOFF_DAYS` days. Concepts without any review event are
    ignored — they've never been learned, so there's nothing to
    review.
    """
    start = time.perf_counter()
    events = ctx.persistence.events.list_for_learner(learner_id)
    cutoff = datetime.now(UTC) - timedelta(days=_STALE_CUTOFF_DAYS)

    latest_seen: dict[str, datetime] = {}
    for event in events:
        if event.kind not in _REVIEW_KINDS:
            continue
        if event.concept is None:
            continue
        current = latest_seen.get(event.concept)
        if current is None or event.timestamp > current:
            latest_seen[event.concept] = event.timestamp

    stale_concepts = sorted(
        concept
        for concept, last_seen in latest_seen.items()
        if last_seen < cutoff
    )
    return TaskReport(
        task_name=_TASK_NAME,
        learner_id_hash=hash_learner_id(learner_id),
        outcome="success",
        duration_ms=elapsed_ms(start),
        details={
            "stale_concept_count": len(stale_concepts),
            "stale_concepts": stale_concepts,
        },
    )


SPEC = TaskSpec(
    name=_TASK_NAME,
    cron=_CRON,
    description="Flag concepts whose last review is older than the stale cutoff.",
    run_fn=run,
)
