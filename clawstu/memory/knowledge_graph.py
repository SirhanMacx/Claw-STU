"""Thin knowledge-graph wrapper for the memory layer.

Why this module exists
----------------------
Memory wants to read / write knowledge-graph triples, but the concrete
triple store lives in `clawstu.persistence.store.KGStore`, which — per
the layering DAG in `tests/test_hierarchy.py` — transitively imports
`clawstu.engagement.session.Session` (persistence owns Session
serialization). A direct import would either create a layer cycle or
require expanding memory's allowed set to include persistence, which
re-introduces the same cycle.

The solution is a local `KGStoreProto` Protocol that declares only the
two KGStore methods memory uses (``append_triple`` and
``find_by_subject``). Memory code type-hints against this protocol;
call sites from the API / scheduler layers pass in a real
`persistence.store.KGStore`, which structurally satisfies the protocol.

This is the same trick `clawstu.orchestrator` uses for `LLMProvider`
and that the test suite uses in `async_router_for_testing` — define the
minimal shape you need at the caller layer, let the concrete
implementation in the lower layer structurally satisfy it.

Triple data model
-----------------
``Triple`` is a frozen pydantic model with five fields. It is used as
both the return value of `find_by_subject` and the input dict for
`add_triple` — keeps the memory layer from re-parsing raw dicts at
every call site. A ``source_session`` field lets the writer tag
triples with the session they came from for audit trails (the spec
writes `(concept, taught_in, session_id)` triples on session close).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Triple(BaseModel):
    """A single knowledge-graph triple."""

    model_config = ConfigDict(frozen=True)

    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    source_session: str | None = None


class KGStoreProto(Protocol):
    """Narrow structural interface memory uses from KGStore.

    Concrete callers pass in a `clawstu.persistence.store.KGStore`
    instance, which satisfies this protocol via its existing method
    signatures. Memory code never imports KGStore directly.
    """

    def append_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        confidence: float = 1.0,
        source_session: str | None = None,
    ) -> None: ...

    def find_by_subject(
        self,
        subject: str,
    ) -> list[dict[str, object]]: ...


def add_triple(
    kg: KGStoreProto,
    *,
    subject: str,
    predicate: str,
    object_: str,
    confidence: float = 1.0,
    source_session: str | None = None,
) -> None:
    """Add a triple to the knowledge graph.

    Thin pass-through. Factored out here so writer.py and capture.py
    don't each need to keep the exact KGStore keyword argument order
    in mind.
    """
    kg.append_triple(
        subject,
        predicate,
        object_,
        confidence=confidence,
        source_session=source_session,
    )


def find_by_subject(kg: KGStoreProto, subject: str) -> list[Triple]:
    """Return every triple with the given subject, as typed Triples.

    Unwraps the underlying `list[dict[str, object]]` into
    `list[Triple]` and validates the confidence field. Missing optional
    fields default to the `Triple` defaults.
    """
    rows = kg.find_by_subject(subject)
    triples: list[Triple] = []
    for row in rows:
        subject_raw = row.get("subject")
        predicate_raw = row.get("predicate")
        object_raw = row.get("object")
        confidence_raw = row.get("confidence", 1.0)
        session_raw = row.get("source_session")
        if not (
            isinstance(subject_raw, str)
            and isinstance(predicate_raw, str)
            and isinstance(object_raw, str)
        ):
            # Corrupt row — skip rather than crash. A corrupt triple
            # should never stop the dream cycle or a context build.
            continue
        confidence = (
            float(confidence_raw)
            if isinstance(confidence_raw, (int, float))
            else 1.0
        )
        source_session = session_raw if isinstance(session_raw, str) else None
        triples.append(
            Triple(
                subject=subject_raw,
                predicate=predicate_raw,
                object=object_raw,
                confidence=confidence,
                source_session=source_session,
            )
        )
    return triples


def find_related(
    kg: KGStoreProto,
    concept: str,
    *,
    depth: int = 1,
) -> set[str]:
    """Return concept ids related to ``concept`` via KG edges.

    Walks outgoing triples starting from ``concept`` up to ``depth``
    hops. At depth 1 (the default) this is just the immediate
    neighbors reachable via any predicate. The result always excludes
    the starting concept itself so callers can union this set with
    ``{concept}`` if they want the full reachable set.

    Edge direction is subject -> object; the walker does not try to
    invert predicates like ``prerequisite_of`` vs ``prerequisite_for``.
    If a caller wants bidirectional reachability, they should index
    both directions at write time.

    ``depth=0`` returns an empty set (you asked for zero hops).
    ``depth < 0`` also returns an empty set — it's not a programmer
    error, just "don't walk".
    """
    if depth <= 0:
        return set()
    visited: set[str] = {concept}
    frontier: set[str] = {concept}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for node in frontier:
            for triple in find_by_subject(kg, node):
                if triple.object not in visited:
                    next_frontier.add(triple.object)
                    visited.add(triple.object)
        frontier = next_frontier
        if not frontier:
            break
    visited.discard(concept)
    return visited
