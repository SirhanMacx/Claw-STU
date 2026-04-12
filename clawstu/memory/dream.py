"""Overnight dream cycle — rewrite compiled truth from accumulated timelines.

Spec reference: §4.3.7.

The dream cycle runs overnight via the scheduler (Phase 6). For every
brain page with non-empty timeline activity since the last cycle, it
asks an LLM to rewrite the compiled-truth section using the timeline
entries as evidence, then compares the proposal to the existing truth
and saves the page only if the diff is meaningful.

This module ships the body of the cycle (``dream_cycle``). Phase 6
wires the scheduler task that invokes it.

Consolidator protocol
---------------------
Memory must not import `clawstu.orchestrator.ModelRouter` because the
orchestrator layer is above memory in the DAG. Instead, dream_cycle
takes a narrow async ``Consolidator`` Protocol: a single
``consolidate(system, user) -> str`` method. Callers in the scheduler
construct a concrete Consolidator that wraps a real
`ModelRouter.for_task(TaskKind.DREAM_CONSOLIDATION)` and passes the
prompt through its provider's ``complete`` method.

Idempotency
-----------
A page is saved only when the proposed compiled truth is "meaningfully
different" from the existing one. Phase 4 applies two criteria:

1. Relative length change > 10%.
2. OR the proposal mentions a concept token that the old truth did
   not (any 5+ character alphanumeric token not in the old truth
   counts as "a new concept").

If neither holds, the page is skipped (idempotent no-op). The spec
guarantees a second dream cycle over an unchanged brain produces
zero rewrites — the counter in ``DreamReport.pages_rewritten`` is
the canonical signal.

Failure handling
----------------
If the consolidator raises, the page is logged as skipped and the
cycle continues. A single provider error must not crash the whole
run. The report's ``errors`` counter records how many pages were
skipped due to provider errors.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from clawstu.memory.pages import BrainPage
from clawstu.memory.store import BrainStore

logger = logging.getLogger(__name__)


class Consolidator(Protocol):
    """Narrow async interface for the dream cycle's LLM consolidation call."""

    async def consolidate(self, *, system: str, user: str) -> str:
        """Return a rewritten compiled-truth paragraph for the prompt."""
        ...


@dataclass(frozen=True)
class DreamReport:
    """Structured output of a dream cycle run."""

    pages_rewritten: int = 0
    pages_skipped: int = 0
    errors: int = 0
    gap_count: int = 0
    duration_ms: float = 0.0
    rewritten_keys: tuple[str, ...] = field(default_factory=tuple)


_SYSTEM_PROMPT = (
    "You are Stuart's dream-cycle consolidator. Given the existing "
    "compiled truth for a brain page and a timeline of recent events, "
    "produce a rewritten compiled-truth paragraph that better reflects "
    "what Stuart now knows. Do not invent facts. Keep the paragraph "
    "short and direct."
)


def _build_prompt(page: BrainPage) -> str:
    """Render a page's current compiled truth + timeline for the LLM."""
    header = f"PAGE_KIND: {page.kind.value}\n"
    compiled = f"CURRENT_COMPILED_TRUTH:\n{page.compiled_truth}\n\n"
    timeline_lines: list[str] = []
    for entry in page.timeline:
        timeline_lines.append(
            f"- {entry.timestamp.isoformat()} {entry.kind}: {entry.text}"
        )
    timeline_block = "\n".join(timeline_lines) or "- (none)"
    return f"{header}{compiled}TIMELINE:\n{timeline_block}"


def _is_meaningful_change(old: str, new: str) -> bool:
    """Return True if the proposed rewrite is meaningfully different."""
    if not new:
        return False
    if old == new:
        return False
    old_len = max(len(old), 1)
    relative = abs(len(new) - len(old)) / old_len
    if relative > 0.1:
        return True
    # New concept token heuristic: any 5+-char alnum token in the new
    # text that wasn't in the old text counts as a new concept.
    old_tokens = {t.lower() for t in old.split() if len(t) >= 5}
    for token in new.split():
        clean = "".join(ch for ch in token if ch.isalnum())
        if len(clean) >= 5 and clean.lower() not in old_tokens:
            return True
    return False


# HEARTBEAT: single-responsibility, no natural seam
async def dream_cycle(
    learner_id: str,
    consolidator: Consolidator,
    brain_store: BrainStore,
) -> DreamReport:
    """Run one dream cycle over every page for a learner.

    Skips pages with an empty timeline (no new evidence to consolidate).
    Calls ``consolidator.consolidate`` once per page with non-empty
    timeline, compares the result to the existing compiled truth, and
    saves the page iff the change is meaningful. A per-page provider
    error increments the ``errors`` counter and is otherwise silent.
    """
    start = time.monotonic()
    rewritten = 0
    skipped = 0
    errors = 0
    rewritten_keys: list[str] = []

    pages = brain_store.list_for_learner(learner_id)
    for page in pages:
        if not page.timeline:
            skipped += 1
            continue
        prompt = _build_prompt(page)
        try:
            proposal = await consolidator.consolidate(
                system=_SYSTEM_PROMPT,
                user=prompt,
            )
        except Exception:
            logger.warning("dream_cycle_learner_failed", exc_info=True)
            errors += 1
            continue
        if not _is_meaningful_change(page.compiled_truth, proposal):
            skipped += 1
            continue
        page.compiled_truth = proposal
        brain_store.put(page, learner_id)
        rewritten += 1
        rewritten_keys.append(f"{page.kind.value}")

    duration_ms = (time.monotonic() - start) * 1000.0
    return DreamReport(
        pages_rewritten=rewritten,
        pages_skipped=skipped,
        errors=errors,
        gap_count=0,
        duration_ms=duration_ms,
        rewritten_keys=tuple(rewritten_keys),
    )
