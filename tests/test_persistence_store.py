"""Entity-store round-trip tests for both SQLite and in-memory stores.

Every test runs twice (parametrized by store type) so the two
implementations stay behaviorally interchangeable. The SQLite store
uses a fresh in-memory database per test; the InMemoryPersistentStore
uses plain Python dicts. Both must round-trip every entity.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from clawstu.engagement.session import Session, SessionPhase
from clawstu.persistence.connection import initialize_database, open_connection
from clawstu.persistence.store import (
    AbstractPersistentStore,
    InMemoryPersistentStore,
    PersistentStore,
)
from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ModalityOutcome,
    ObservationEvent,
    ZPDEstimate,
)


@pytest.fixture
def sqlite_store() -> Iterator[PersistentStore]:
    conn = open_connection(":memory:")
    initialize_database(conn)
    store = PersistentStore(conn)
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def memory_store() -> InMemoryPersistentStore:
    return InMemoryPersistentStore()


@pytest.fixture(params=["sqlite", "memory"])
def store(
    request: pytest.FixtureRequest,
    sqlite_store: PersistentStore,
    memory_store: InMemoryPersistentStore,
) -> AbstractPersistentStore:
    if request.param == "sqlite":
        return sqlite_store
    return memory_store


# -- LearnerStore -----------------------------------------------------


def test_learner_upsert_and_get_round_trips(store: AbstractPersistentStore) -> None:
    profile = LearnerProfile(learner_id="alice", age_bracket=AgeBracket.MIDDLE)
    store.learners.upsert(profile)
    loaded = store.learners.get("alice")
    assert loaded is not None
    assert loaded.learner_id == "alice"
    assert loaded.age_bracket is AgeBracket.MIDDLE


def test_learner_get_missing_returns_none(store: AbstractPersistentStore) -> None:
    assert store.learners.get("ghost") is None


def test_learner_upsert_is_idempotent(store: AbstractPersistentStore) -> None:
    profile = LearnerProfile(learner_id="bob", age_bracket=AgeBracket.LATE_HIGH)
    store.learners.upsert(profile)
    store.learners.upsert(profile)
    loaded = store.learners.get("bob")
    assert loaded is not None
    assert loaded.age_bracket is AgeBracket.LATE_HIGH


# -- SessionStore -----------------------------------------------------


def test_session_upsert_and_get_round_trips(store: AbstractPersistentStore) -> None:
    learner = LearnerProfile(learner_id="carol", age_bracket=AgeBracket.ADULT)
    store.learners.upsert(learner)
    session = Session(
        learner_id="carol",
        domain=Domain.US_HISTORY,
        phase=SessionPhase.TEACHING,
    )
    store.sessions.upsert(session)
    loaded = store.sessions.get(session.id)
    assert loaded is not None
    assert loaded.learner_id == "carol"
    assert loaded.domain is Domain.US_HISTORY
    assert loaded.phase is SessionPhase.TEACHING


def test_session_list_for_learner_filters(store: AbstractPersistentStore) -> None:
    learner_a = LearnerProfile(learner_id="a", age_bracket=AgeBracket.MIDDLE)
    learner_b = LearnerProfile(learner_id="b", age_bracket=AgeBracket.MIDDLE)
    store.learners.upsert(learner_a)
    store.learners.upsert(learner_b)
    s_a1 = Session(learner_id="a", domain=Domain.US_HISTORY)
    s_a2 = Session(learner_id="a", domain=Domain.CIVICS)
    s_b1 = Session(learner_id="b", domain=Domain.US_HISTORY)
    store.sessions.upsert(s_a1)
    store.sessions.upsert(s_a2)
    store.sessions.upsert(s_b1)
    a_sessions = store.sessions.list_for_learner("a")
    assert {s.id for s in a_sessions} == {s_a1.id, s_a2.id}


# -- EventStore -------------------------------------------------------


def test_event_append_and_list_round_trips(store: AbstractPersistentStore) -> None:
    store.learners.upsert(
        LearnerProfile(learner_id="dana", age_bracket=AgeBracket.MIDDLE)
    )
    event = ObservationEvent(
        kind=EventKind.CHECK_FOR_UNDERSTANDING,
        domain=Domain.US_HISTORY,
        modality=Modality.TEXT_READING,
        tier=ComplexityTier.MEETING,
        correct=True,
        concept="federalism",
        notes="quick response",
    )
    store.events.append(event, learner_id="dana", session_id=None)
    events = store.events.list_for_learner("dana")
    assert len(events) == 1
    assert events[0].concept == "federalism"
    assert events[0].correct is True


def test_event_list_preserves_insertion_order(store: AbstractPersistentStore) -> None:
    store.learners.upsert(
        LearnerProfile(learner_id="ed", age_bracket=AgeBracket.MIDDLE)
    )
    for concept in ("one", "two", "three"):
        store.events.append(
            ObservationEvent(
                kind=EventKind.VOLUNTARY_QUESTION,
                domain=Domain.CIVICS,
                concept=concept,
            ),
            learner_id="ed",
            session_id=None,
        )
    events = store.events.list_for_learner("ed")
    assert [e.concept for e in events] == ["one", "two", "three"]


# -- ZPDStore ---------------------------------------------------------


def test_zpd_upsert_all_and_get_all_round_trips(store: AbstractPersistentStore) -> None:
    store.learners.upsert(
        LearnerProfile(learner_id="frank", age_bracket=AgeBracket.MIDDLE)
    )
    estimates = {
        Domain.US_HISTORY: ZPDEstimate(
            domain=Domain.US_HISTORY, tier=ComplexityTier.EXCEEDING, confidence=0.8, samples=10
        ),
        Domain.CIVICS: ZPDEstimate(
            domain=Domain.CIVICS, tier=ComplexityTier.APPROACHING, confidence=0.4, samples=5
        ),
    }
    store.zpd.upsert_all("frank", estimates)
    loaded = store.zpd.get_all("frank")
    assert loaded[Domain.US_HISTORY].tier is ComplexityTier.EXCEEDING
    assert loaded[Domain.US_HISTORY].samples == 10
    assert loaded[Domain.CIVICS].tier is ComplexityTier.APPROACHING


def test_zpd_upsert_all_overwrites_on_second_call(store: AbstractPersistentStore) -> None:
    store.learners.upsert(
        LearnerProfile(learner_id="grace", age_bracket=AgeBracket.MIDDLE)
    )
    store.zpd.upsert_all(
        "grace",
        {Domain.US_HISTORY: ZPDEstimate(domain=Domain.US_HISTORY, samples=1)},
    )
    store.zpd.upsert_all(
        "grace",
        {Domain.US_HISTORY: ZPDEstimate(domain=Domain.US_HISTORY, samples=42)},
    )
    loaded = store.zpd.get_all("grace")
    assert loaded[Domain.US_HISTORY].samples == 42


# -- ModalityStore ----------------------------------------------------


def test_modality_upsert_all_and_get_all_round_trips(store: AbstractPersistentStore) -> None:
    store.learners.upsert(
        LearnerProfile(learner_id="hank", age_bracket=AgeBracket.LATE_HIGH)
    )
    outcomes = {
        Modality.TEXT_READING: ModalityOutcome(
            attempts=10, successes=7, total_latency_seconds=55.0
        ),
        Modality.PRIMARY_SOURCE: ModalityOutcome(
            attempts=3, successes=2, total_latency_seconds=12.5
        ),
    }
    store.modality_outcomes.upsert_all("hank", outcomes)
    loaded = store.modality_outcomes.get_all("hank")
    assert loaded[Modality.TEXT_READING].attempts == 10
    assert loaded[Modality.TEXT_READING].successes == 7
    assert loaded[Modality.PRIMARY_SOURCE].total_latency_seconds == pytest.approx(12.5)


# -- MisconceptionStore -----------------------------------------------


def test_misconception_upsert_all_and_get_all_round_trips(
    store: AbstractPersistentStore,
) -> None:
    store.learners.upsert(
        LearnerProfile(learner_id="iris", age_bracket=AgeBracket.MIDDLE)
    )
    store.misconceptions.upsert_all(
        "iris", {"federalism": 3, "separation_of_powers": 1}
    )
    loaded = store.misconceptions.get_all("iris")
    assert loaded == {"federalism": 3, "separation_of_powers": 1}


# -- ArtifactStore ----------------------------------------------------


def test_artifact_upsert_get_and_mark_consumed(store: AbstractPersistentStore) -> None:
    store.learners.upsert(
        LearnerProfile(learner_id="jack", age_bracket=AgeBracket.ADULT)
    )
    store.artifacts.upsert(
        "jack",
        pathway_json='{"concepts":["a","b"]}',
        first_block_json='{"id":"b1"}',
        first_check_json='{"id":"c1"}',
    )
    loaded = store.artifacts.get("jack")
    assert loaded is not None
    assert loaded["pathway_json"] == '{"concepts":["a","b"]}'
    assert loaded["consumed_at"] is None
    store.artifacts.mark_consumed("jack")
    after = store.artifacts.get("jack")
    assert after is not None
    assert after["consumed_at"] is not None


# -- KGStore ----------------------------------------------------------


def test_kg_append_and_find_by_subject(store: AbstractPersistentStore) -> None:
    store.kg.append_triple(
        "Abraham Lincoln", "was_president_of", "United States", confidence=1.0
    )
    store.kg.append_triple(
        "Abraham Lincoln",
        "signed",
        "Emancipation Proclamation",
        confidence=0.95,
        source_session="sess-001",
    )
    hits = store.kg.find_by_subject("Abraham Lincoln")
    assert len(hits) == 2
    predicates = {row["predicate"] for row in hits}
    assert predicates == {"was_president_of", "signed"}


# -- SchedulerRunStore ------------------------------------------------


def test_scheduler_append_and_list_recent(store: AbstractPersistentStore) -> None:
    store.scheduler_runs.append(
        task_name="nightly-review",
        learner_id_hash="deadbeef1234",
        outcome="success",
        duration_ms=123,
        token_cost_input=100,
        token_cost_output=250,
    )
    store.scheduler_runs.append(
        task_name="hourly-ping",
        learner_id_hash=None,
        outcome="failure",
        duration_ms=5,
        error_message="timeout",
    )
    recent = store.scheduler_runs.list_recent(limit=10)
    assert len(recent) == 2
    task_names = {row["task_name"] for row in recent}
    assert task_names == {"nightly-review", "hourly-ping"}


# -- Container and lifecycle ------------------------------------------


def test_in_memory_store_is_isolated_across_instances() -> None:
    a = InMemoryPersistentStore()
    b = InMemoryPersistentStore()
    a.learners.upsert(
        LearnerProfile(learner_id="solo", age_bracket=AgeBracket.MIDDLE)
    )
    assert a.learners.get("solo") is not None
    assert b.learners.get("solo") is None


def test_persistent_store_initialize_is_idempotent() -> None:
    conn = open_connection(":memory:")
    store = PersistentStore(conn)
    try:
        store.initialize()
        store.initialize()  # second call must not raise
        assert store.learners.get("nobody") is None
    finally:
        store.close()


def test_abstract_store_exposes_all_expected_attributes(
    store: AbstractPersistentStore,
) -> None:
    # A mild shape contract: every attribute referenced by AppState
    # exists on both store variants.
    attrs = (
        "learners",
        "sessions",
        "events",
        "zpd",
        "modality_outcomes",
        "misconceptions",
        "artifacts",
        "kg",
        "scheduler_runs",
    )
    for attr in attrs:
        assert hasattr(store, attr), f"store is missing attribute: {attr}"
        # Touch the attribute to ensure it actually exists, not just hasattr.
        assert getattr(store, attr) is not None
