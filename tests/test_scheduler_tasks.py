"""Tests for the five Phase 6 scheduler task bodies.

Each task is exercised end-to-end against a fabricated `ProactiveContext`
that wires an in-memory brain store, an in-memory persistence store,
and an `EchoProvider`-backed `ModelRouter`. No network, no event loop,
no APScheduler — pure async-function tests.

The dream_cycle test asserts that the task happily wraps Phase 4's
memory-level `dream_cycle` and surfaces its DreamReport counters in
`TaskReport.details`. The prepare_next_session test exercises the
idempotency contract (run twice, second run is `skipped_current`).
The pure-Python tasks (spaced_review, refresh_zpd, prune_stale) are
tested directly against synthesized event / session histories.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from clawstu.engagement.session import Session, SessionPhase
from clawstu.memory.pages import LearnerPage, TimelineEntry
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ObservationEvent,
)
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.tasks import (
    dream_cycle,
    prepare_next_session,
    prune_stale,
    refresh_zpd,
    spaced_review,
)
from clawstu.scheduler.tasks._common import hash_learner_id


def _router(provider: LLMProvider | None = None) -> ModelRouter:
    """Build a ModelRouter that resolves every task kind to EchoProvider."""
    echo = provider if isinstance(provider, EchoProvider) else EchoProvider()
    providers: dict[str, LLMProvider] = {"echo": echo}
    return ModelRouter(config=AppConfig(), providers=providers)


@pytest.fixture
def brain_store(tmp_path: Path) -> BrainStore:
    return BrainStore(tmp_path / "brain")


@pytest.fixture
def persistence() -> InMemoryPersistentStore:
    return InMemoryPersistentStore()


@pytest.fixture
def context(
    brain_store: BrainStore,
    persistence: InMemoryPersistentStore,
) -> ProactiveContext:
    return ProactiveContext(
        router=_router(),
        brain_store=brain_store,
        persistence=persistence,
    )


# -- helpers ----------------------------------------------------------------


def _learner(
    persistence: InMemoryPersistentStore,
    learner_id: str = "test-learner",
) -> LearnerProfile:
    profile = LearnerProfile(
        learner_id=learner_id,
        age_bracket=AgeBracket.MIDDLE,
    )
    persistence.learners.upsert(profile)
    return profile


def _check_event(
    *,
    concept: str,
    timestamp: datetime,
    domain: Domain = Domain.US_HISTORY,
    correct: bool = True,
) -> ObservationEvent:
    return ObservationEvent(
        kind=EventKind.CHECK_FOR_UNDERSTANDING,
        domain=domain,
        modality=Modality.SOCRATIC_DIALOGUE,
        tier=ComplexityTier.MEETING,
        correct=correct,
        latency_seconds=10.0,
        concept=concept,
        timestamp=timestamp,
    )


# -- dream_cycle ------------------------------------------------------------


class TestDreamCycleTask:
    async def test_returns_task_report_for_empty_brain(
        self,
        context: ProactiveContext,
    ) -> None:
        report = await dream_cycle.run(context, "test-learner")
        assert report.task_name == "dream_cycle"
        assert report.outcome == "success"
        assert report.duration_ms >= 0
        assert report.error_message is None
        assert report.learner_id_hash == hash_learner_id("test-learner")
        # Phase 4 reports zero rewrites for an empty brain.
        assert report.details["pages_rewritten"] == 0

    async def test_wraps_memory_dream_cycle_with_pages(
        self,
        context: ProactiveContext,
        brain_store: BrainStore,
    ) -> None:
        # Seed a learner page so the dream cycle has something to walk.
        page = LearnerPage(
            learner_id="test-learner",
            compiled_truth="Initial short truth.",
            timeline=[
                TimelineEntry(
                    timestamp=datetime(2026, 4, 11, 14, 0, tzinfo=UTC),
                    kind="session_close",
                    text="blocks=2 reteaches=0",
                )
            ],
        )
        brain_store.put(page, "test-learner")

        report = await dream_cycle.run(context, "test-learner")
        # The echo provider's reply is a short string and the existing
        # truth is also short, so the meaningful-change heuristic may
        # or may not flip — the task itself is still successful.
        assert report.outcome == "success"
        assert report.task_name == "dream_cycle"
        assert "pages_rewritten" in report.details
        assert "pages_skipped" in report.details
        assert "errors" in report.details
        assert "gap_count" in report.details

    async def test_top_level_exception_marks_run_failed(
        self,
        brain_store: BrainStore,
        persistence: InMemoryPersistentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _raise(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated dream-level failure")

        monkeypatch.setattr(
            "clawstu.scheduler.tasks.dream_cycle._memory_dream_cycle",
            _raise,
        )
        ctx = ProactiveContext(
            router=_router(),
            brain_store=brain_store,
            persistence=persistence,
        )
        report = await dream_cycle.run(ctx, "test-learner")
        assert report.outcome == "failed"
        assert report.error_message == "simulated dream-level failure"
        assert report.task_name == "dream_cycle"


# -- prepare_next_session ---------------------------------------------------


class TestPrepareNextSessionTask:
    async def test_writes_artifact_when_none_exists(
        self,
        context: ProactiveContext,
    ) -> None:
        report = await prepare_next_session.run(context, "alice")
        assert report.outcome == "success"
        assert report.task_name == "prepare_next_session"
        artifact = context.persistence.artifacts.get("alice")
        assert artifact is not None
        assert artifact["pathway_json"] is not None
        assert artifact["first_block_json"] is not None
        assert artifact["first_check_json"] is not None
        assert artifact["consumed_at"] is None

    async def test_idempotent_second_run_is_skipped(
        self,
        context: ProactiveContext,
    ) -> None:
        first = await prepare_next_session.run(context, "alice")
        second = await prepare_next_session.run(context, "alice")
        assert first.outcome == "success"
        assert second.outcome == "skipped_current"
        details = second.details
        assert "reason" in details

    async def test_runs_again_after_artifact_consumed(
        self,
        context: ProactiveContext,
    ) -> None:
        first = await prepare_next_session.run(context, "alice")
        assert first.outcome == "success"
        context.persistence.artifacts.mark_consumed("alice")
        second = await prepare_next_session.run(context, "alice")
        assert second.outcome == "success"
        artifact = context.persistence.artifacts.get("alice")
        assert artifact is not None
        # Re-running clears consumed_at because upsert resets it.
        assert artifact["consumed_at"] is None


# -- spaced_review ----------------------------------------------------------


class TestSpacedReviewTask:
    async def test_no_events_yields_zero_stale_concepts(
        self,
        context: ProactiveContext,
    ) -> None:
        report = await spaced_review.run(context, "alice")
        assert report.outcome == "success"
        assert report.details["stale_concept_count"] == 0
        assert report.details["stale_concepts"] == []

    async def test_recent_events_are_not_stale(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        recent = datetime.now(UTC) - timedelta(days=1)
        persistence.events.append(
            _check_event(concept="reconstruction", timestamp=recent),
            learner_id="alice",
            session_id=None,
        )
        report = await spaced_review.run(context, "alice")
        assert report.details["stale_concept_count"] == 0

    async def test_old_events_become_stale(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        old = datetime.now(UTC) - timedelta(days=30)
        persistence.events.append(
            _check_event(concept="emancipation", timestamp=old),
            learner_id="alice",
            session_id=None,
        )
        persistence.events.append(
            _check_event(
                concept="industrialization",
                timestamp=datetime.now(UTC) - timedelta(days=20),
            ),
            learner_id="alice",
            session_id=None,
        )
        report = await spaced_review.run(context, "alice")
        assert report.details["stale_concept_count"] == 2
        assert report.details["stale_concepts"] == [
            "emancipation",
            "industrialization",
        ]

    async def test_non_review_events_are_ignored(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        # SESSION_START / VOLUNTARY_QUESTION / etc. should be skipped.
        persistence.events.append(
            ObservationEvent(
                kind=EventKind.SESSION_START,
                domain=Domain.US_HISTORY,
                concept="reconstruction",
                timestamp=datetime.now(UTC) - timedelta(days=30),
            ),
            learner_id="alice",
            session_id=None,
        )
        report = await spaced_review.run(context, "alice")
        assert report.details["stale_concept_count"] == 0

    async def test_review_events_without_concept_are_ignored(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        # A check-for-understanding event with concept=None should be
        # skipped — there's nothing to file under.
        persistence.events.append(
            ObservationEvent(
                kind=EventKind.CHECK_FOR_UNDERSTANDING,
                domain=Domain.US_HISTORY,
                modality=Modality.SOCRATIC_DIALOGUE,
                tier=ComplexityTier.MEETING,
                correct=True,
                latency_seconds=10.0,
                concept=None,
                timestamp=datetime.now(UTC) - timedelta(days=30),
            ),
            learner_id="alice",
            session_id=None,
        )
        report = await spaced_review.run(context, "alice")
        assert report.details["stale_concept_count"] == 0

    async def test_most_recent_event_per_concept_wins(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        # First event is old, second is fresh — concept should NOT be stale.
        persistence.events.append(
            _check_event(
                concept="federalism",
                timestamp=datetime.now(UTC) - timedelta(days=40),
            ),
            learner_id="alice",
            session_id=None,
        )
        persistence.events.append(
            _check_event(
                concept="federalism",
                timestamp=datetime.now(UTC) - timedelta(days=2),
            ),
            learner_id="alice",
            session_id=None,
        )
        report = await spaced_review.run(context, "alice")
        assert report.details["stale_concept_count"] == 0


# -- refresh_zpd ------------------------------------------------------------


class TestRefreshZpdTask:
    async def test_missing_learner_returns_failed(
        self,
        context: ProactiveContext,
    ) -> None:
        report = await refresh_zpd.run(context, "ghost")
        assert report.outcome == "failed"
        assert report.error_message is not None
        assert "ghost" in report.error_message

    async def test_existing_learner_runs_successfully(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        _learner(persistence, "alice")
        report = await refresh_zpd.run(context, "alice")
        assert report.outcome == "success"
        assert report.details["events_replayed"] == 0
        assert report.details["domains_updated"] == 0

    async def test_replays_review_events_through_calibrator(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        _learner(persistence, "alice")
        # Three correct answers in US_HISTORY: replays should produce
        # one upserted ZPD estimate for that domain.
        for _ in range(3):
            persistence.events.append(
                _check_event(
                    concept="reconstruction",
                    timestamp=datetime.now(UTC),
                    correct=True,
                ),
                learner_id="alice",
                session_id=None,
            )
        report = await refresh_zpd.run(context, "alice")
        assert report.outcome == "success"
        assert report.details["events_replayed"] == 3
        assert report.details["domains_updated"] == 1
        # Persistence should now contain the recomputed estimate.
        stored = persistence.zpd.get_all("alice")
        assert Domain.US_HISTORY in stored

    async def test_skips_events_without_correct_field(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        _learner(persistence, "alice")
        # MODALITY_ENGAGEMENT events have no `correct` field — they
        # should be skipped by the replay loop.
        persistence.events.append(
            ObservationEvent(
                kind=EventKind.MODALITY_ENGAGEMENT,
                domain=Domain.US_HISTORY,
                concept="reconstruction",
                timestamp=datetime.now(UTC),
            ),
            learner_id="alice",
            session_id=None,
        )
        report = await refresh_zpd.run(context, "alice")
        assert report.outcome == "success"
        assert report.details["events_replayed"] == 0

    async def test_skips_review_events_with_correct_unset(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        _learner(persistence, "alice")
        # A check_for_understanding event with correct=None (e.g.
        # one that timed out without grading) should be skipped by
        # the replay loop even though its kind is in _REPLAY_KINDS.
        persistence.events.append(
            ObservationEvent(
                kind=EventKind.CHECK_FOR_UNDERSTANDING,
                domain=Domain.US_HISTORY,
                modality=Modality.SOCRATIC_DIALOGUE,
                tier=ComplexityTier.MEETING,
                correct=None,
                concept="reconstruction",
                timestamp=datetime.now(UTC),
            ),
            learner_id="alice",
            session_id=None,
        )
        report = await refresh_zpd.run(context, "alice")
        assert report.outcome == "success"
        assert report.details["events_replayed"] == 0


# -- prune_stale ------------------------------------------------------------


class TestPruneStaleTask:
    async def test_empty_session_table_is_a_no_op(
        self,
        context: ProactiveContext,
    ) -> None:
        report = await prune_stale.run(context, "*")
        assert report.outcome == "success"
        assert report.details["pruned"] == 0
        assert report.details["sessions_scanned"] == 0
        assert report.learner_id_hash is None

    async def test_recent_sessions_are_not_pruned(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        session = Session(
            learner_id="alice",
            domain=Domain.US_HISTORY,
            phase=SessionPhase.TEACHING,
        )
        # `started_at` defaults to now, so this session is fresh.
        persistence.sessions.upsert(session)
        report = await prune_stale.run(context, "*")
        assert report.details["pruned"] == 0
        assert report.details["sessions_scanned"] == 1
        # Phase should still be TEACHING.
        roundtrip = persistence.sessions.get(session.id)
        assert roundtrip is not None
        assert roundtrip.phase == SessionPhase.TEACHING

    async def test_old_unclosed_sessions_get_pruned(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        old_started_at = datetime.now(UTC) - timedelta(days=45)
        session = Session(
            learner_id="alice",
            domain=Domain.US_HISTORY,
            phase=SessionPhase.TEACHING,
            started_at=old_started_at,
        )
        persistence.sessions.upsert(session)
        report = await prune_stale.run(context, "*")
        assert report.details["pruned"] == 1
        assert report.details["sessions_scanned"] == 1
        roundtrip = persistence.sessions.get(session.id)
        assert roundtrip is not None
        assert roundtrip.phase == SessionPhase.CLOSED

    async def test_already_closed_sessions_are_left_alone(
        self,
        context: ProactiveContext,
        persistence: InMemoryPersistentStore,
    ) -> None:
        old_started_at = datetime.now(UTC) - timedelta(days=60)
        session = Session(
            learner_id="alice",
            domain=Domain.US_HISTORY,
            phase=SessionPhase.CLOSED,
            started_at=old_started_at,
        )
        persistence.sessions.upsert(session)
        report = await prune_stale.run(context, "*")
        assert report.details["pruned"] == 0
        assert report.details["sessions_scanned"] == 1


# -- _common helpers --------------------------------------------------------


class TestHashLearnerId:
    def test_global_sentinel_maps_to_none(self) -> None:
        assert hash_learner_id("*") is None

    def test_concrete_id_returns_short_hash(self) -> None:
        h = hash_learner_id("test-learner")
        assert h is not None
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_is_deterministic(self) -> None:
        assert hash_learner_id("alice") == hash_learner_id("alice")
        assert hash_learner_id("alice") != hash_learner_id("bob")
