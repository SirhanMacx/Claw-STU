"""Per-learner concept wiki tests and capture_source smoke test."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstu.memory.capture import capture_source
from clawstu.memory.knowledge_graph import add_triple
from clawstu.memory.pages import (
    ConceptPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
    SourcePage,
)
from clawstu.memory.store import BrainStore
from clawstu.memory.wiki import generate_concept_wiki
from clawstu.persistence.store import InMemoryPersistentStore


@pytest.fixture
def store(tmp_path: Path) -> BrainStore:
    return BrainStore(tmp_path / "brain")


@pytest.fixture
def persist() -> InMemoryPersistentStore:
    return InMemoryPersistentStore()


def test_wiki_has_expected_sections_and_concept_name(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    # Empty brain — just the concept and learner id should appear.
    wiki = generate_concept_wiki(
        learner_id="test-learner",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
    )
    assert "# Concept: civil_war" in wiki
    assert "## What Stuart knows about civil_war" in wiki
    assert "## What test-learner knows" in wiki
    assert "## Recent sessions" in wiki
    assert "## Open misconceptions" in wiki
    assert "## Tied primary sources" in wiki


def test_wiki_includes_compiled_truth_sessions_misconceptions_sources(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        ConceptPage(
            learner_id="test-learner",
            concept_id="civil_war",
            compiled_truth="COMPILED_TRUTH_BODY: causes and consequences.",
        ),
        "test-learner",
    )
    store.put(
        SessionPage(
            session_id="sess-001",
            learner_id="test-learner",
            compiled_truth="SESSION_SUMMARY: covered causes.",
        ),
        "test-learner",
    )
    store.put(
        MisconceptionPage(
            learner_id="test-learner",
            misconception_id="civil_war_states_rights",
            concept_id="civil_war",
            occurrences=2,
            compiled_truth="MISC_BODY: states rights only.",
        ),
        "test-learner",
    )
    store.put(
        SourcePage(
            source_id="emp-proc",
            title="Emancipation Proclamation",
            attribution="Abraham Lincoln, 1863",
            age_bracket="late_high",
            compiled_truth="SOURCE_BODY",
        ),
        learner_id="test-learner",
    )
    add_triple(
        persist.kg,
        subject="civil_war",
        predicate="taught_in",
        object_="sess-001",
    )
    add_triple(
        persist.kg,
        subject="civil_war",
        predicate="has_source",
        object_="emp-proc",
    )
    wiki = generate_concept_wiki(
        learner_id="test-learner",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
    )
    assert "COMPILED_TRUTH_BODY" in wiki
    assert "sess-001" in wiki
    assert "SESSION_SUMMARY" in wiki
    assert "civil_war_states_rights" in wiki
    assert "seen 2x" in wiki
    assert "Emancipation Proclamation" in wiki
    assert "Abraham Lincoln" in wiki


def test_capture_source_writes_a_retrievable_source_page(
    store: BrainStore,
) -> None:
    page = capture_source(
        "When in the course of human events...",
        source_id="declaration",
        title="Declaration of Independence",
        age_bracket="late_high",
        brain_store=store,
        attribution="Thomas Jefferson et al, 1776",
    )
    assert isinstance(page, SourcePage)
    retrieved = store.get(PageKind.SOURCE, "declaration", "")
    assert isinstance(retrieved, SourcePage)
    assert retrieved.title == "Declaration of Independence"
    assert retrieved.attribution == "Thomas Jefferson et al, 1776"
    assert "human events" in retrieved.compiled_truth
