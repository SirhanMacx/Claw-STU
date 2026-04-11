"""Knowledge graph wrapper tests.

Exercises memory.knowledge_graph against the real in-memory KGStore
from clawstu.persistence. The persistence store's KGStore structurally
satisfies the `KGStoreProto` Protocol defined in the memory layer, so
passing it into the memory-layer helpers is the canonical call pattern.
"""

from __future__ import annotations

from clawstu.memory.knowledge_graph import (
    Triple,
    add_triple,
    find_by_subject,
    find_related,
)
from clawstu.persistence.store import InMemoryPersistentStore


def test_add_triple_round_trips_via_find_by_subject() -> None:
    store = InMemoryPersistentStore()
    add_triple(
        store.kg,
        subject="civil_war",
        predicate="taught_in",
        object_="sess-001",
        confidence=0.9,
        source_session="sess-001",
    )
    triples = find_by_subject(store.kg, "civil_war")
    assert len(triples) == 1
    assert isinstance(triples[0], Triple)
    assert triples[0].subject == "civil_war"
    assert triples[0].predicate == "taught_in"
    assert triples[0].object == "sess-001"
    assert triples[0].confidence == 0.9
    assert triples[0].source_session == "sess-001"


def test_find_related_walks_one_hop_by_default() -> None:
    store = InMemoryPersistentStore()
    # civil_war -> reconstruction (prereq)
    # civil_war -> emancipation (taught_in session has this as object)
    # reconstruction -> jim_crow
    add_triple(
        store.kg,
        subject="civil_war",
        predicate="prerequisite_for",
        object_="reconstruction",
    )
    add_triple(
        store.kg,
        subject="civil_war",
        predicate="covers",
        object_="emancipation",
    )
    add_triple(
        store.kg,
        subject="reconstruction",
        predicate="prerequisite_for",
        object_="jim_crow",
    )

    one_hop = find_related(store.kg, "civil_war", depth=1)
    assert one_hop == {"reconstruction", "emancipation"}

    two_hop = find_related(store.kg, "civil_war", depth=2)
    assert two_hop == {"reconstruction", "emancipation", "jim_crow"}

    zero_hop = find_related(store.kg, "civil_war", depth=0)
    assert zero_hop == set()


def test_find_related_returns_empty_set_for_unknown_subject() -> None:
    store = InMemoryPersistentStore()
    add_triple(
        store.kg,
        subject="civil_war",
        predicate="prerequisite_for",
        object_="reconstruction",
    )
    assert find_related(store.kg, "unknown_concept") == set()
