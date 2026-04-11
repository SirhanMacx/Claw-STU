"""write_session_to_memory tests — page minting + KG triple emission."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstu.memory.knowledge_graph import find_by_subject
from clawstu.memory.pages import (
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
)
from clawstu.memory.store import BrainStore
from clawstu.memory.writer import SessionSnapshot, write_session_to_memory
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import AgeBracket, LearnerProfile


@pytest.fixture
def store(tmp_path: Path) -> BrainStore:
    return BrainStore(tmp_path / "brain")


@pytest.fixture
def persist() -> InMemoryPersistentStore:
    return InMemoryPersistentStore()


def _profile() -> LearnerProfile:
    return LearnerProfile(
        learner_id="test-learner",
        age_bracket=AgeBracket.LATE_HIGH,
    )


def test_session_close_produces_expected_pages(
    store: BrainStore,
    persist: InMemoryPersistentStore,
) -> None:
    snapshot = SessionSnapshot(
        session_id="sess-0001",
        learner_id="test-learner",
        concepts_touched=("civil_war", "reconstruction"),
        wrong_answer_concepts=("reconstruction",),
        blocks_presented=4,
        reteach_count=1,
        summary="Covered civil war + reconstruction. One reteach on reconstruction.",
    )
    write_session_to_memory(
        profile=_profile(),
        snapshot=snapshot,
        brain_store=store,
        kg_store=persist.kg,
    )

    # SessionPage exists.
    session_page = store.get(PageKind.SESSION, "sess-0001", "test-learner")
    assert isinstance(session_page, SessionPage)
    assert "civil war + reconstruction" in session_page.compiled_truth
    assert len(session_page.timeline) == 1

    # LearnerPage has a timeline entry.
    learner_page = store.get(PageKind.LEARNER, "test-learner", "test-learner")
    assert isinstance(learner_page, LearnerPage)
    assert len(learner_page.timeline) == 1
    assert "sess-000" in learner_page.timeline[0].text

    # One ConceptPage per concept touched.
    civil_war = store.get(PageKind.CONCEPT, "civil_war", "test-learner")
    reconstruction = store.get(
        PageKind.CONCEPT, "reconstruction", "test-learner"
    )
    assert isinstance(civil_war, ConceptPage)
    assert isinstance(reconstruction, ConceptPage)

    # MisconceptionPage for the wrong-answer concept.
    misc = store.get(
        PageKind.MISCONCEPTION, "reconstruction_miss", "test-learner"
    )
    assert isinstance(misc, MisconceptionPage)
    assert misc.occurrences == 1
    assert misc.concept_id == "reconstruction"

    # KG triples — both directions for each concept.
    civil_war_triples = find_by_subject(persist.kg, "civil_war")
    assert any(
        t.predicate == "taught_in" and t.object == "sess-0001"
        for t in civil_war_triples
    )
    session_triples = find_by_subject(persist.kg, "sess-0001")
    assert any(
        t.predicate == "includes" and t.object == "civil_war"
        for t in session_triples
    )
    assert any(
        t.predicate == "includes" and t.object == "reconstruction"
        for t in session_triples
    )


def test_second_session_close_updates_learner_timeline(
    store: BrainStore,
    persist: InMemoryPersistentStore,
) -> None:
    profile = _profile()
    for i in range(3):
        snapshot = SessionSnapshot(
            session_id=f"sess-{i:04d}",
            learner_id="test-learner",
            concepts_touched=("civil_war",),
            blocks_presented=2,
        )
        write_session_to_memory(
            profile=profile,
            snapshot=snapshot,
            brain_store=store,
            kg_store=persist.kg,
        )
    learner_page = store.get(PageKind.LEARNER, "test-learner", "test-learner")
    assert isinstance(learner_page, LearnerPage)
    assert len(learner_page.timeline) == 3

    civil_war = store.get(PageKind.CONCEPT, "civil_war", "test-learner")
    assert isinstance(civil_war, ConceptPage)
    assert len(civil_war.timeline) == 3


def test_repeated_wrong_answer_increments_occurrences(
    store: BrainStore,
    persist: InMemoryPersistentStore,
) -> None:
    profile = _profile()
    snapshot_a = SessionSnapshot(
        session_id="sess-a",
        learner_id="test-learner",
        concepts_touched=("civil_war",),
        wrong_answer_concepts=("civil_war",),
    )
    snapshot_b = snapshot_a.model_copy(update={"session_id": "sess-b"})
    write_session_to_memory(
        profile=profile,
        snapshot=snapshot_a,
        brain_store=store,
        kg_store=persist.kg,
    )
    write_session_to_memory(
        profile=profile,
        snapshot=snapshot_b,
        brain_store=store,
        kg_store=persist.kg,
    )
    misc = store.get(
        PageKind.MISCONCEPTION, "civil_war_miss", "test-learner"
    )
    assert isinstance(misc, MisconceptionPage)
    assert misc.occurrences == 2
    assert len(misc.timeline) == 2
