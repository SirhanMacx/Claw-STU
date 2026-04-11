"""`prepare_next_session` task — idempotent warm-start stub.

Spec reference: §4.7.5 (cron `15 3 * * *`).

Phase 6 ships the idempotency shell. When the task fires it checks for
an existing unconsumed next-session artifact; if one is present the
task returns `outcome="skipped_current"`. Otherwise it writes a
minimal placeholder artifact via `ArtifactStore.upsert` so the next
time the task fires it short-circuits.

Real live-content generation (calling `LiveContentGenerator` to
pre-bake a pathway, a first block, and a first check) is a Phase 7
concern — the machinery already exists in
`clawstu.orchestrator.live_content`, but wiring it here would require
async iteration over every active learner's preferred topic and a
policy decision on which topic to prime. That is out of scope for
Phase 6. This stub keeps the task on-schedule and exercises the
idempotency contract end-to-end.
"""

from __future__ import annotations

import json
import time

from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import TaskReport, TaskSpec
from clawstu.scheduler.tasks._common import elapsed_ms, hash_learner_id

_TASK_NAME = "prepare_next_session"
_CRON = "15 3 * * *"

_PLACEHOLDER_PATHWAY = {"concepts": ["placeholder"]}
_PLACEHOLDER_BLOCK = {
    "title": "placeholder",
    "body": "placeholder — Phase 6 stub; real content lands in Phase 7.",
}
_PLACEHOLDER_CHECK = {
    "prompt": "placeholder",
    "type": "crq",
    "rubric": ["Phase 6 stub check."],
}


async def run(ctx: ProactiveContext, learner_id: str) -> TaskReport:
    """Skip if an unconsumed artifact exists; otherwise write a stub.

    The idempotency check uses `ArtifactStore.get(learner_id)` which
    returns a dict with `consumed_at` set when the learner has picked
    up the staged content. If `consumed_at is None` the artifact is
    still live and this task refuses to overwrite it — a second tick
    in the same night must not clobber warm-start content the learner
    hasn't seen yet.
    """
    start = time.perf_counter()
    existing = ctx.persistence.artifacts.get(learner_id)
    if existing is not None and existing.get("consumed_at") is None:
        return TaskReport(
            task_name=_TASK_NAME,
            learner_id_hash=hash_learner_id(learner_id),
            outcome="skipped_current",
            duration_ms=elapsed_ms(start),
            details={"reason": "unconsumed artifact already exists"},
        )
    ctx.persistence.artifacts.upsert(
        learner_id=learner_id,
        pathway_json=json.dumps(_PLACEHOLDER_PATHWAY),
        first_block_json=json.dumps(_PLACEHOLDER_BLOCK),
        first_check_json=json.dumps(_PLACEHOLDER_CHECK),
    )
    return TaskReport(
        task_name=_TASK_NAME,
        learner_id_hash=hash_learner_id(learner_id),
        outcome="success",
        duration_ms=elapsed_ms(start),
        details={"artifact": "placeholder"},
    )


SPEC = TaskSpec(
    name=_TASK_NAME,
    cron=_CRON,
    description="Pre-stage a next-session artifact (idempotent placeholder).",
    run_fn=run,
)
