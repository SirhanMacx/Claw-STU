"""BrainStore — atomic file-backed CRUD tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from clawstu.memory.pages import (
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
    SourcePage,
    TopicPage,
)
from clawstu.memory.store import BrainStore


@pytest.fixture
def store(tmp_path: Path) -> BrainStore:
    return BrainStore(tmp_path / "brain")


def test_put_and_get_round_trips_a_learner_page(store: BrainStore) -> None:
    page = LearnerPage(
        learner_id="test-learner",
        compiled_truth="Visual learner; avoid dense text.",
    )
    store.put(page, learner_id="test-learner")
    retrieved = store.get(PageKind.LEARNER, "test-learner", "test-learner")
    assert isinstance(retrieved, LearnerPage)
    assert retrieved.learner_id == "test-learner"
    assert retrieved.compiled_truth == "Visual learner; avoid dense text."


def test_get_returns_none_for_missing_page(store: BrainStore) -> None:
    assert store.get(PageKind.LEARNER, "ghost", "ghost") is None
    assert store.get(PageKind.CONCEPT, "civil_war", "ghost") is None
    assert store.get(PageKind.SOURCE, "no-such", "anyone") is None


def test_learner_directory_is_hashed_not_plaintext(
    store: BrainStore,
    tmp_path: Path,
) -> None:
    learner_id = "alice@example.com"
    page = LearnerPage(learner_id=learner_id, compiled_truth="x")
    store.put(page, learner_id=learner_id)
    # The learner id must NOT appear in any directory name on disk.
    disk_entries = {p.name for p in (tmp_path / "brain").rglob("*")}
    assert learner_id not in disk_entries
    assert "@" not in {entry for entry in disk_entries}
    # The hash should be the 12-char prefix.
    expected_hash = hashlib.sha256(learner_id.encode()).hexdigest()[:12]
    assert expected_hash in {p.name for p in (tmp_path / "brain").iterdir()}


def test_put_is_atomic_via_tmp_rename(
    store: BrainStore,
    tmp_path: Path,
) -> None:
    page = ConceptPage(
        learner_id="l1",
        concept_id="civil_war",
        compiled_truth="initial",
    )
    store.put(page, learner_id="l1")
    # No .tmp files should linger after a successful write.
    tmps = list((tmp_path / "brain").rglob("*.tmp"))
    assert tmps == []
    # Overwrite and re-check.
    page.compiled_truth = "updated"
    store.put(page, learner_id="l1")
    tmps = list((tmp_path / "brain").rglob("*.tmp"))
    assert tmps == []
    retrieved = store.get(PageKind.CONCEPT, "civil_war", "l1")
    assert retrieved is not None
    assert retrieved.compiled_truth == "updated"


def test_list_for_learner_returns_every_kind_except_sources(
    store: BrainStore,
) -> None:
    store.put(LearnerPage(learner_id="l1", compiled_truth="A"), "l1")
    store.put(
        ConceptPage(
            learner_id="l1", concept_id="civil_war", compiled_truth="B"
        ),
        "l1",
    )
    store.put(
        SessionPage(
            session_id="s1", learner_id="l1", compiled_truth="C"
        ),
        "l1",
    )
    store.put(
        MisconceptionPage(
            learner_id="l1",
            misconception_id="m1",
            concept_id="civil_war",
            compiled_truth="D",
        ),
        "l1",
    )
    store.put(
        TopicPage(
            learner_id="l1", topic_id="reform_movements", compiled_truth="E"
        ),
        "l1",
    )
    store.put(
        SourcePage(
            source_id="emp-proc",
            title="Emancipation Proclamation",
            age_bracket="late_high",
            compiled_truth="F",
        ),
        learner_id="l1",  # ignored for sources
    )

    pages = store.list_for_learner("l1")
    kinds = {p.kind for p in pages}
    # SourcePage is global — excluded from the per-learner listing.
    assert PageKind.SOURCE not in kinds
    assert PageKind.LEARNER in kinds
    assert PageKind.CONCEPT in kinds
    assert PageKind.SESSION in kinds
    assert PageKind.MISCONCEPTION in kinds
    assert PageKind.TOPIC in kinds
    assert len(pages) == 5


def test_list_for_learner_with_kind_filter(store: BrainStore) -> None:
    store.put(
        ConceptPage(
            learner_id="l1", concept_id="civil_war", compiled_truth="A"
        ),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="reconstruction",
            compiled_truth="B",
        ),
        "l1",
    )
    store.put(LearnerPage(learner_id="l1", compiled_truth="C"), "l1")

    concepts = store.list_for_learner("l1", kind=PageKind.CONCEPT)
    assert len(concepts) == 2
    assert {p.kind for p in concepts} == {PageKind.CONCEPT}


def test_list_for_learner_isolates_between_learners(store: BrainStore) -> None:
    store.put(LearnerPage(learner_id="alice", compiled_truth="A"), "alice")
    store.put(LearnerPage(learner_id="bob", compiled_truth="B"), "bob")
    store.put(
        ConceptPage(learner_id="alice", concept_id="c1", compiled_truth="x"),
        "alice",
    )

    alice_pages = store.list_for_learner("alice")
    bob_pages = store.list_for_learner("bob")
    assert len(alice_pages) == 2
    assert len(bob_pages) == 1


def test_list_sources_returns_global_sources(store: BrainStore) -> None:
    store.put(
        SourcePage(
            source_id="emp-proc",
            title="Emancipation Proclamation",
            age_bracket="late_high",
            compiled_truth="x",
        ),
        learner_id="anyone",
    )
    store.put(
        SourcePage(
            source_id="gettysburg",
            title="Gettysburg Address",
            age_bracket="late_high",
            compiled_truth="y",
        ),
        learner_id="someone-else",
    )
    sources = store.list_sources()
    assert len(sources) == 2
    assert {s.source_id for s in sources} == {"emp-proc", "gettysburg"}


def test_delete_returns_true_on_hit_false_on_miss(
    store: BrainStore,
) -> None:
    store.put(
        ConceptPage(
            learner_id="l1", concept_id="civil_war", compiled_truth="x"
        ),
        "l1",
    )
    assert store.delete(PageKind.CONCEPT, "civil_war", "l1") is True
    assert store.delete(PageKind.CONCEPT, "civil_war", "l1") is False
    assert store.get(PageKind.CONCEPT, "civil_war", "l1") is None


def test_slug_sanitizes_unsafe_characters(store: BrainStore) -> None:
    # IDs with slashes or dots should not escape the subdirectory.
    page = ConceptPage(
        learner_id="l1",
        concept_id="../evil",
        compiled_truth="x",
    )
    store.put(page, "l1")
    retrieved = store.get(PageKind.CONCEPT, "../evil", "l1")
    assert retrieved is not None
    assert retrieved.concept_id == "../evil"
