"""Context assembly tests — build_learner_context priority + truncation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from clawstu.memory.context import build_learner_context
from clawstu.memory.knowledge_graph import add_triple
from clawstu.memory.pages import (
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    SessionPage,
    SourcePage,
)
from clawstu.memory.store import BrainStore
from clawstu.persistence.store import InMemoryPersistentStore


@pytest.fixture
def store(tmp_path: Path) -> BrainStore:
    return BrainStore(tmp_path / "brain")


@pytest.fixture
def persist() -> InMemoryPersistentStore:
    return InMemoryPersistentStore()


def test_context_includes_learner_and_concept_pages_always(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        LearnerPage(
            learner_id="l1",
            compiled_truth="LEARNER_BODY: prefers primary sources.",
        ),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="civil_war",
            compiled_truth="CONCEPT_BODY: causes and consequences.",
        ),
        "l1",
    )
    ctx = build_learner_context(
        learner_id="l1",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
    )
    assert "LEARNER_BODY" in ctx.text
    assert "CONCEPT_BODY" in ctx.text
    assert "learner:l1" in ctx.source_pages
    assert "concept:civil_war" in ctx.source_pages


def test_context_pulls_related_concepts_via_kg(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        LearnerPage(learner_id="l1", compiled_truth="learner x"),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="civil_war",
            compiled_truth="concept x",
        ),
        "l1",
    )
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="reconstruction",
            compiled_truth="RELATED_BODY: reconstruction amendments",
        ),
        "l1",
    )
    add_triple(
        persist.kg,
        subject="civil_war",
        predicate="prerequisite_for",
        object_="reconstruction",
    )
    ctx = build_learner_context(
        learner_id="l1",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
    )
    assert "RELATED_BODY" in ctx.text
    assert "concept:reconstruction" in ctx.source_pages


def test_context_includes_last_three_sessions(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        LearnerPage(learner_id="l1", compiled_truth="x"),
        "l1",
    )
    store.put(
        ConceptPage(learner_id="l1", concept_id="civil_war", compiled_truth="y"),
        "l1",
    )
    # Create 5 session pages with increasing updated_at so the 3 newest
    # are s3, s4, s5.
    for i in range(1, 6):
        store.put(
            SessionPage(
                session_id=f"s{i}",
                learner_id="l1",
                updated_at=datetime(2026, 4, 11, 10, i, 0, tzinfo=UTC),
                compiled_truth=f"SESSION_{i}",
            ),
            "l1",
        )
    ctx = build_learner_context(
        learner_id="l1",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
    )
    assert "SESSION_5" in ctx.text
    assert "SESSION_4" in ctx.text
    assert "SESSION_3" in ctx.text
    assert "SESSION_2" not in ctx.text


def test_context_includes_misconceptions_tied_to_concept(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        LearnerPage(learner_id="l1", compiled_truth="x"),
        "l1",
    )
    store.put(
        ConceptPage(learner_id="l1", concept_id="civil_war", compiled_truth="y"),
        "l1",
    )
    store.put(
        MisconceptionPage(
            learner_id="l1",
            misconception_id="civil_war_states_rights",
            concept_id="civil_war",
            compiled_truth="MISCONCEPTION_BODY: states rights only",
        ),
        "l1",
    )
    # Also a misconception tied to a DIFFERENT concept — must be skipped.
    store.put(
        MisconceptionPage(
            learner_id="l1",
            misconception_id="unrelated",
            concept_id="great_depression",
            compiled_truth="WRONG_CONCEPT_BODY",
        ),
        "l1",
    )
    ctx = build_learner_context(
        learner_id="l1",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
    )
    assert "MISCONCEPTION_BODY" in ctx.text
    assert "WRONG_CONCEPT_BODY" not in ctx.text


def test_context_includes_sources_tagged_via_kg(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        LearnerPage(learner_id="l1", compiled_truth="x"),
        "l1",
    )
    store.put(
        ConceptPage(learner_id="l1", concept_id="civil_war", compiled_truth="y"),
        "l1",
    )
    store.put(
        SourcePage(
            source_id="emp-proc",
            title="Emancipation Proclamation",
            age_bracket="late_high",
            compiled_truth="SOURCE_BODY: primary source text.",
        ),
        learner_id="l1",
    )
    add_triple(
        persist.kg,
        subject="civil_war",
        predicate="has_source",
        object_="emp-proc",
    )
    ctx = build_learner_context(
        learner_id="l1",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
    )
    assert "SOURCE_BODY" in ctx.text
    assert "source:emp-proc" in ctx.source_pages


def test_context_respects_max_chars_budget(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        LearnerPage(
            learner_id="l1",
            compiled_truth="LEARNER_BODY small",
        ),
        "l1",
    )
    # A huge concept page that by itself would exceed the budget.
    big_body = "C" * 500
    store.put(
        ConceptPage(
            learner_id="l1",
            concept_id="civil_war",
            compiled_truth=big_body,
        ),
        "l1",
    )
    ctx = build_learner_context(
        learner_id="l1",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
        max_chars=120,
    )
    # The assembled text must not exceed the budget.
    assert len(ctx.text) <= 120
    # Learner page should have made it in (highest priority).
    assert "learner:l1" in ctx.source_pages


def test_context_zero_max_chars_returns_empty(
    store: BrainStore, persist: InMemoryPersistentStore
) -> None:
    store.put(
        LearnerPage(learner_id="l1", compiled_truth="x"),
        "l1",
    )
    ctx = build_learner_context(
        learner_id="l1",
        concept="civil_war",
        brain_store=store,
        kg_store=persist.kg,
        max_chars=0,
    )
    assert ctx.text == ""
    assert ctx.source_pages == ()
