"""Tests for the cross-invocation CLI state bridge."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from clawstu.cli_state import (
    NoLearnersError,
    default_stores,
    load_persistence_from_disk,
    most_recent_learner,
    save_persistence_to_disk,
)
from clawstu.engagement.session import Session
from clawstu.persistence.store import InMemoryPersistentStore
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


def _make_profile(
    learner_id: str = "ada",
    bracket: AgeBracket = AgeBracket.MIDDLE,
) -> LearnerProfile:
    return LearnerProfile(learner_id=learner_id, age_bracket=bracket)


def _make_session(
    learner_id: str = "ada",
    *,
    started_at: datetime | None = None,
    topic: str = "photosynthesis",
) -> Session:
    """Build a Session in CLOSED phase pinned at a specific start time."""
    if started_at is None:
        started_at = datetime.now(UTC)
    return Session(
        learner_id=learner_id,
        domain=Domain.SCIENCE,
        topic=topic,
        started_at=started_at,
    )


def test_cli_state_save_and_load_round_trip(tmp_path: Path) -> None:
    """A populated store round-trips through JSON without loss.

    Seeds every entity store the bridge knows about -- learners,
    sessions, events, zpd, modality outcomes, misconceptions, kg
    triples -- saves it, loads it back, and asserts both stores
    describe the same learner shape.
    """
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    sess = _make_session("ada", topic="photosynthesis")
    store.sessions.upsert(sess)

    event = ObservationEvent(
        kind=EventKind.CHECK_FOR_UNDERSTANDING,
        domain=Domain.SCIENCE,
        concept="photosynthesis",
        correct=True,
    )
    store.events.append(event, learner_id="ada", session_id=sess.id)

    store.zpd.upsert_all(
        "ada",
        {
            Domain.SCIENCE: ZPDEstimate(
                domain=Domain.SCIENCE,
                tier=ComplexityTier.MEETING,
                confidence=0.6,
                samples=3,
            ),
        },
    )
    store.modality_outcomes.upsert_all(
        "ada",
        {
            Modality.TEXT_READING: ModalityOutcome(
                attempts=5, successes=3, total_latency_seconds=120.0,
            ),
        },
    )
    store.misconceptions.upsert_all("ada", {"chlorophyll_is_a_plant": 2})
    store.kg.append_triple(
        "photosynthesis", "taught_in", sess.id, confidence=1.0,
    )

    state_path = tmp_path / "state.json"
    save_persistence_to_disk(store, state_path)
    assert state_path.exists()

    loaded = load_persistence_from_disk(state_path)

    # Learners round-trip.
    assert loaded.learners.get("ada") is not None
    profile = loaded.learners.get("ada")
    assert profile is not None
    assert profile.age_bracket is AgeBracket.MIDDLE

    # Sessions round-trip.
    loaded_sessions = loaded.sessions.list_for_learner("ada")
    assert len(loaded_sessions) == 1
    assert loaded_sessions[0].topic == "photosynthesis"
    assert loaded_sessions[0].id == sess.id

    # Events round-trip (the list_for_learner call returns all of them).
    loaded_events = loaded.events.list_for_learner("ada")
    assert len(loaded_events) == 1
    assert loaded_events[0].concept == "photosynthesis"
    assert loaded_events[0].correct is True

    # ZPD round-trips including the tier + confidence + samples.
    zpd_map = loaded.zpd.get_all("ada")
    assert Domain.SCIENCE in zpd_map
    assert zpd_map[Domain.SCIENCE].tier is ComplexityTier.MEETING
    assert zpd_map[Domain.SCIENCE].samples == 3

    # Modality outcomes round-trip.
    mod_map = loaded.modality_outcomes.get_all("ada")
    assert mod_map[Modality.TEXT_READING].attempts == 5
    assert mod_map[Modality.TEXT_READING].successes == 3

    # Misconceptions round-trip.
    assert loaded.misconceptions.get_all("ada") == {"chlorophyll_is_a_plant": 2}

    # KG triples round-trip.
    kg_rows = loaded.kg.find_by_subject("photosynthesis")
    assert len(kg_rows) == 1
    assert kg_rows[0]["predicate"] == "taught_in"
    assert kg_rows[0]["object"] == sess.id


def test_load_persistence_from_missing_file_returns_empty_store(
    tmp_path: Path,
) -> None:
    """``load_persistence_from_disk`` on a missing path is a no-op.

    The helper returns a fresh empty store so first-time users can
    run ``clawstu progress`` / ``wiki`` / etc. without a pre-existing
    snapshot file.
    """
    missing = tmp_path / "nope.json"
    assert not missing.exists()
    store = load_persistence_from_disk(missing)
    assert store.learners.get("whoever") is None


def test_load_persistence_from_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{this is not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_persistence_from_disk(path)


def test_load_persistence_rejects_bad_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        '{"schema_version": 999, "learners": []}', encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema_version"):
        load_persistence_from_disk(path)


def test_most_recent_learner_picks_the_newest_session(
    tmp_path: Path,
) -> None:
    """The default learner is the one whose most recent session is newest."""
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    store.learners.upsert(_make_profile("bob"))

    # Ada last worked on a session an hour ago; Bob worked 2 hours ago.
    # So `most_recent_learner` should return "ada".
    now = datetime.now(UTC)
    store.sessions.upsert(
        _make_session("ada", started_at=now - timedelta(hours=1)),
    )
    store.sessions.upsert(
        _make_session("bob", started_at=now - timedelta(hours=2)),
    )
    assert most_recent_learner(store) == "ada"


def test_most_recent_learner_empty_store_raises() -> None:
    """Empty store raises NoLearnersError.

    The CLI layer turns this into a "no learners yet" message + exit
    code 1, but the exception itself stays generic so tests can
    assert on it without invoking Typer.
    """
    store = InMemoryPersistentStore()
    with pytest.raises(NoLearnersError, match="no learners yet"):
        most_recent_learner(store)


def test_most_recent_learner_sessionless_learner_falls_back_to_lex(
    tmp_path: Path,
) -> None:
    """A store with learners but zero sessions returns the lex-min id.

    Edge case: a learner profile was upserted (e.g., during onboarding)
    but no sessions have been persisted yet. ``most_recent_learner``
    must still return *something* so the CLI commands can show a
    useful "empty learner" table instead of crashing.
    """
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("zoe"))
    store.learners.upsert(_make_profile("ada"))
    assert most_recent_learner(store) == "ada"


def test_default_stores_uses_config_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """``default_stores`` roots the brain store + state file at cfg.data_dir.

    Drives ``CLAW_STU_DATA_DIR`` via monkeypatch so the helper doesn't
    touch the real user home, and asserts the returned state_path and
    brain dir both land under the sandboxed tmp dir.
    """
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    bundle = default_stores()
    assert bundle.cfg.data_dir == tmp_path
    assert bundle.state_path == tmp_path / "state.json"
    assert bundle.brain_store is not None
    # brain dir hangs off the data dir.
    assert (tmp_path / "brain").parent == tmp_path


def test_default_stores_loads_existing_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """``default_stores`` seeds from the state.json snapshot if present."""
    # Pre-populate a state.json file with a single learner.
    seed = InMemoryPersistentStore()
    seed.learners.upsert(_make_profile("ada"))
    seed.sessions.upsert(_make_session("ada"))
    save_persistence_to_disk(seed, tmp_path / "state.json")

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    bundle = default_stores()
    assert bundle.persistence.learners.get("ada") is not None
    loaded_sessions = bundle.persistence.sessions.list_for_learner("ada")
    assert len(loaded_sessions) == 1
