"""Session close writer — mint brain pages from a finished session.

Spec reference: §4.3.6.

``write_session_to_memory`` runs on every session close. It produces:

1. A ``SessionPage`` — one-page history of the session.
2. An updated ``LearnerPage`` — compiled truth bumped from the
   accumulated profile signals; the session gets a timeline entry.
3. For each concept the session touched: an updated or created
   ``ConceptPage`` with a timeline entry and a refreshed compiled
   truth.
4. For each wrong-answer concept: an incremented ``MisconceptionPage``
   with a timeline entry.
5. KG triples ``(concept, taught_in, session_id)`` and
   ``(session_id, includes, concept)`` for every concept touched.

Decoupling from engagement.Session
----------------------------------
Memory must not import from the engagement layer (the layer DAG
forbids it — engagement is above memory). The writer takes a
memory-local `SessionSnapshot` pydantic model instead: the caller in
the API / orchestrator layer builds a snapshot from a real
`clawstu.engagement.session.Session` and passes it here. Same trick
as the `KGStoreProto` in `knowledge_graph.py`.

Compiled-truth semantics
------------------------
This writer does NOT rewrite the full compiled truth via an LLM —
that is the dream cycle's job (§4.3.7). What it does do is APPEND a
short programmatic summary sentence to the existing compiled truth,
which seeds the next dream cycle with fresh evidence to consolidate.
That keeps the write path LLM-free and deterministic; the
consolidation pass runs asynchronously in the background.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from clawstu.memory.knowledge_graph import KGStoreProto, add_triple
from clawstu.memory.pages import (
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
    TimelineEntry,
)
from clawstu.memory.store import BrainStore
from clawstu.profile.model import LearnerProfile


class SessionSnapshot(BaseModel):
    """Memory-local view of a finished session.

    Callers in the engagement / api / orchestrator layers construct
    this from a real `Session` model. The snapshot intentionally
    carries only the fields the writer needs — no pathway, no
    assessment items, no signals (those come from the accompanying
    LearnerProfile argument).
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    learner_id: str
    concepts_touched: tuple[str, ...] = ()
    wrong_answer_concepts: tuple[str, ...] = ()
    blocks_presented: int = 0
    reteach_count: int = 0
    summary: str = ""


def _now() -> datetime:
    return datetime.now(UTC)


def _write_session_page(
    snapshot: SessionSnapshot,
    brain_store: BrainStore,
    learner_id: str,
    now: datetime,
) -> None:
    """Create and store a SessionPage for the finished session."""
    session_summary = (
        snapshot.summary
        or (
            f"Session {snapshot.session_id[:8]}. "
            f"Blocks presented: {snapshot.blocks_presented}. "
            f"Re-teaches: {snapshot.reteach_count}."
        )
    )
    session_page = SessionPage(
        session_id=snapshot.session_id,
        learner_id=learner_id,
        updated_at=now,
        compiled_truth=session_summary,
        timeline=[
            TimelineEntry(
                timestamp=now,
                kind="session_close",
                text=(
                    f"{snapshot.blocks_presented} blocks, "
                    f"{snapshot.reteach_count} reteaches, "
                    f"{len(snapshot.concepts_touched)} concepts"
                ),
            )
        ],
    )
    brain_store.put(session_page, learner_id)


def _write_learner_page(
    profile: LearnerProfile,
    snapshot: SessionSnapshot,
    brain_store: BrainStore,
    learner_id: str,
    now: datetime,
) -> None:
    """Update or create the LearnerPage with a session-close timeline entry."""
    learner_page = brain_store.get(PageKind.LEARNER, learner_id, learner_id)
    if not isinstance(learner_page, LearnerPage):
        learner_page = LearnerPage(
            learner_id=learner_id,
            compiled_truth="",
        )
    learner_page.append_timeline(
        TimelineEntry(
            timestamp=now,
            kind="session_close",
            text=(
                f"session={snapshot.session_id[:8]} "
                f"blocks={snapshot.blocks_presented} "
                f"reteaches={snapshot.reteach_count}"
            ),
        )
    )
    if not learner_page.compiled_truth:
        accuracy_numerator = profile.voluntary_question_count
        learner_page.compiled_truth = (
            f"Learner {learner_id} ({profile.age_bracket.value}). "
            f"Voluntary questions to date: {accuracy_numerator}."
        )
    brain_store.put(learner_page, learner_id)


def _write_concept_pages(
    snapshot: SessionSnapshot,
    brain_store: BrainStore,
    learner_id: str,
    now: datetime,
) -> None:
    """Update or create a ConceptPage for each concept the session touched."""
    for concept in snapshot.concepts_touched:
        concept_page = brain_store.get(
            PageKind.CONCEPT, concept, learner_id,
        )
        if not isinstance(concept_page, ConceptPage):
            concept_page = ConceptPage(
                learner_id=learner_id,
                concept_id=concept,
                compiled_truth=(
                    f"Concept {concept}. First encountered in "
                    f"session {snapshot.session_id[:8]}."
                ),
            )
        concept_page.append_timeline(
            TimelineEntry(
                timestamp=now,
                kind="session_touched",
                text=f"session={snapshot.session_id[:8]}",
            )
        )
        brain_store.put(concept_page, learner_id)


def _write_misconception_pages(
    snapshot: SessionSnapshot,
    brain_store: BrainStore,
    learner_id: str,
    now: datetime,
) -> None:
    """Increment or create a MisconceptionPage for each wrong-answer concept."""
    for concept in snapshot.wrong_answer_concepts:
        misc_id = f"{concept}_miss"
        misc_page = brain_store.get(
            PageKind.MISCONCEPTION, misc_id, learner_id,
        )
        if not isinstance(misc_page, MisconceptionPage):
            misc_page = MisconceptionPage(
                learner_id=learner_id,
                misconception_id=misc_id,
                concept_id=concept,
                occurrences=0,
                compiled_truth=(
                    f"Student missed a check-for-understanding on {concept}."
                ),
            )
        misc_page.occurrences += 1
        misc_page.append_timeline(
            TimelineEntry(
                timestamp=now,
                kind="miss",
                text=f"session={snapshot.session_id[:8]}",
            )
        )
        brain_store.put(misc_page, learner_id)


def _write_kg_triples(
    snapshot: SessionSnapshot,
    kg_store: KGStoreProto,
) -> None:
    """Add taught_in/includes KG triples for each concept touched."""
    for concept in snapshot.concepts_touched:
        add_triple(
            kg_store,
            subject=concept,
            predicate="taught_in",
            object_=snapshot.session_id,
            source_session=snapshot.session_id,
        )
        add_triple(
            kg_store,
            subject=snapshot.session_id,
            predicate="includes",
            object_=concept,
            source_session=snapshot.session_id,
        )


def write_session_to_memory(
    profile: LearnerProfile,
    snapshot: SessionSnapshot,
    brain_store: BrainStore,
    kg_store: KGStoreProto,
) -> None:
    """Update the brain for a finished session.

    Idempotent-by-key: calling twice with the same snapshot produces
    the same SessionPage, bumps the same LearnerPage timeline twice,
    and increments the same Misconception counter twice. Callers that
    want at-most-once semantics are responsible for that at their
    layer (e.g., checking session status before invoking).
    """
    learner_id = snapshot.learner_id
    now = _now()

    _write_session_page(snapshot, brain_store, learner_id, now)
    _write_learner_page(profile, snapshot, brain_store, learner_id, now)
    _write_concept_pages(snapshot, brain_store, learner_id, now)
    _write_misconception_pages(snapshot, brain_store, learner_id, now)
    _write_kg_triples(snapshot, kg_store)
