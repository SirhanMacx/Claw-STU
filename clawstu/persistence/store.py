"""Typed entity stores (spec §4.6.3).

This module defines:

- A Protocol (`AbstractPersistentStore`) that both backends satisfy, so
  callers — including `clawstu.api.state.AppState` — can be typed
  against the interface instead of a concrete class.
- Concrete `LearnerStore`, `SessionStore`, `EventStore`, `ZPDStore`,
  `ModalityStore`, `MisconceptionStore`, `ArtifactStore`, `KGStore`,
  and `SchedulerRunStore` entity wrappers for SQLite.
- `PersistentStore` — aggregates the SQLite entity stores and owns
  the connection lifecycle.
- `InMemoryPersistentStore` — a dict-backed test double that exposes
  the same attribute surface and behavioral contract as
  `PersistentStore`. Used by the test suite via a pytest fixture and
  by `AppState` when no SQLite path is configured.

All method signatures are explicitly typed. No `Any` leaks out
through a return type. Raw SQL lives only here and in `schema.py`.
"""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol

from clawstu.engagement.session import Session
from clawstu.persistence.connection import initialize_database
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


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


# -- Protocols ---------------------------------------------------------


class _LearnerStoreProto(Protocol):
    def upsert(self, profile: LearnerProfile) -> None: ...
    def get(self, learner_id: str) -> LearnerProfile | None: ...


class _SessionStoreProto(Protocol):
    def upsert(self, session: Session) -> None: ...
    def get(self, session_id: str) -> Session | None: ...
    def list_for_learner(self, learner_id: str) -> list[Session]: ...


class _EventStoreProto(Protocol):
    def append(
        self,
        event: ObservationEvent,
        *,
        learner_id: str,
        session_id: str | None,
    ) -> None: ...
    def list_for_learner(self, learner_id: str) -> list[ObservationEvent]: ...


class _ZPDStoreProto(Protocol):
    def upsert_all(
        self, learner_id: str, estimates: dict[Domain, ZPDEstimate]
    ) -> None: ...
    def get_all(self, learner_id: str) -> dict[Domain, ZPDEstimate]: ...


class _ModalityStoreProto(Protocol):
    def upsert_all(
        self, learner_id: str, outcomes: dict[Modality, ModalityOutcome]
    ) -> None: ...
    def get_all(self, learner_id: str) -> dict[Modality, ModalityOutcome]: ...


class _MisconceptionStoreProto(Protocol):
    def upsert_all(self, learner_id: str, tallies: dict[str, int]) -> None: ...
    def get_all(self, learner_id: str) -> dict[str, int]: ...


class _ArtifactStoreProto(Protocol):
    def upsert(
        self,
        learner_id: str,
        *,
        pathway_json: str,
        first_block_json: str,
        first_check_json: str,
    ) -> None: ...
    def get(self, learner_id: str) -> dict[str, str | None] | None: ...
    def mark_consumed(self, learner_id: str) -> None: ...


class _KGStoreProto(Protocol):
    def append_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        confidence: float = 1.0,
        source_session: str | None = None,
    ) -> None: ...
    def find_by_subject(self, subject: str) -> list[dict[str, object]]: ...


class _SchedulerRunStoreProto(Protocol):
    def append(
        self,
        *,
        task_name: str,
        learner_id_hash: str | None,
        outcome: str,
        duration_ms: int,
        token_cost_input: int = 0,
        token_cost_output: int = 0,
        error_message: str | None = None,
    ) -> None: ...
    def list_recent(self, limit: int = 50) -> list[dict[str, object]]: ...


class AbstractPersistentStore(Protocol):
    """The shared shape of the SQLite and in-memory stores.

    Every attribute is one of the entity-store protocols above. This
    lets `AppState` take `AbstractPersistentStore` without caring
    which backend is in use.
    """

    learners: _LearnerStoreProto
    sessions: _SessionStoreProto
    events: _EventStoreProto
    zpd: _ZPDStoreProto
    modality_outcomes: _ModalityStoreProto
    misconceptions: _MisconceptionStoreProto
    artifacts: _ArtifactStoreProto
    kg: _KGStoreProto
    scheduler_runs: _SchedulerRunStoreProto

    def initialize(self) -> None: ...
    def close(self) -> None: ...


# -- SQLite implementation --------------------------------------------


class LearnerStore:
    """SQLite-backed CRUD for `learners`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, profile: LearnerProfile) -> None:
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO learners (learner_id, age_bracket, created_at, last_active_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(learner_id) DO UPDATE SET
                    age_bracket = excluded.age_bracket,
                    last_active_at = excluded.last_active_at
                """,
                (
                    profile.learner_id,
                    profile.age_bracket.value,
                    profile.created_at.isoformat(),
                    now,
                ),
            )

    def get(self, learner_id: str) -> LearnerProfile | None:
        row = self._conn.execute(
            "SELECT learner_id, age_bracket, created_at FROM learners "
            "WHERE learner_id = ?",
            (learner_id,),
        ).fetchone()
        if row is None:
            return None
        return LearnerProfile(
            learner_id=row[0],
            age_bracket=AgeBracket(row[1]),
            created_at=datetime.fromisoformat(row[2]),
        )


class SessionStore:
    """SQLite-backed CRUD for `sessions`.

    The full `Session` model is serialized to JSON in the
    `pathway_json` column. Structured columns (`domain`, `phase`,
    `started_at`, `closed_at`) are kept in sync so future queries
    can filter without parsing the blob, but the blob is the source
    of truth on read.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, session: Session) -> None:
        blob = session.model_dump_json()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, learner_id, domain, topic, phase,
                    pathway_json, started_at, closed_at, crisis_paused
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(session_id) DO UPDATE SET
                    domain = excluded.domain,
                    phase = excluded.phase,
                    pathway_json = excluded.pathway_json,
                    closed_at = excluded.closed_at
                """,
                (
                    session.id,
                    session.learner_id,
                    session.domain.value,
                    None,
                    session.phase.value,
                    blob,
                    session.started_at.isoformat(),
                    None,
                ),
            )

    def get(self, session_id: str) -> Session | None:
        row = self._conn.execute(
            "SELECT pathway_json FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return Session.model_validate_json(row[0])

    def list_for_learner(self, learner_id: str) -> list[Session]:
        rows = self._conn.execute(
            "SELECT pathway_json FROM sessions WHERE learner_id = ? "
            "AND pathway_json IS NOT NULL ORDER BY started_at ASC",
            (learner_id,),
        ).fetchall()
        return [Session.model_validate_json(row[0]) for row in rows]


class EventStore:
    """SQLite-backed append log for `observation_events`.

    Events are never updated. `append` always inserts a new row.
    `list_for_learner` returns events ordered by their autoincrement
    primary key so insertion order is preserved across ties in
    `timestamp`.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(
        self,
        event: ObservationEvent,
        *,
        learner_id: str,
        session_id: str | None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO observation_events (
                    learner_id, session_id, kind, domain, modality, tier,
                    correct, latency_seconds, concept, notes, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    learner_id,
                    session_id,
                    event.kind.value,
                    event.domain.value,
                    event.modality.value if event.modality else None,
                    event.tier.value if event.tier else None,
                    int(event.correct) if event.correct is not None else None,
                    event.latency_seconds,
                    event.concept,
                    event.notes,
                    event.timestamp.isoformat(),
                ),
            )

    def list_for_learner(self, learner_id: str) -> list[ObservationEvent]:
        rows = self._conn.execute(
            """
            SELECT kind, domain, modality, tier, correct,
                   latency_seconds, concept, notes, timestamp
              FROM observation_events
             WHERE learner_id = ?
             ORDER BY id ASC
            """,
            (learner_id,),
        ).fetchall()
        events: list[ObservationEvent] = []
        for row in rows:
            events.append(
                ObservationEvent(
                    kind=EventKind(row[0]),
                    domain=Domain(row[1]),
                    modality=Modality(row[2]) if row[2] is not None else None,
                    tier=ComplexityTier(row[3]) if row[3] is not None else None,
                    correct=bool(row[4]) if row[4] is not None else None,
                    latency_seconds=row[5],
                    concept=row[6],
                    notes=row[7],
                    timestamp=datetime.fromisoformat(row[8]),
                )
            )
        return events


class ZPDStore:
    """SQLite-backed per-(learner, domain) ZPD estimate store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_all(
        self, learner_id: str, estimates: dict[Domain, ZPDEstimate]
    ) -> None:
        with self._conn:
            for domain, estimate in estimates.items():
                self._conn.execute(
                    """
                    INSERT INTO zpd_estimates (
                        learner_id, domain, tier, confidence, samples, last_updated
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(learner_id, domain) DO UPDATE SET
                        tier = excluded.tier,
                        confidence = excluded.confidence,
                        samples = excluded.samples,
                        last_updated = excluded.last_updated
                    """,
                    (
                        learner_id,
                        domain.value,
                        estimate.tier.value,
                        estimate.confidence,
                        estimate.samples,
                        estimate.last_updated.isoformat(),
                    ),
                )

    def get_all(self, learner_id: str) -> dict[Domain, ZPDEstimate]:
        rows = self._conn.execute(
            "SELECT domain, tier, confidence, samples, last_updated "
            "FROM zpd_estimates WHERE learner_id = ?",
            (learner_id,),
        ).fetchall()
        out: dict[Domain, ZPDEstimate] = {}
        for row in rows:
            domain = Domain(row[0])
            out[domain] = ZPDEstimate(
                domain=domain,
                tier=ComplexityTier(row[1]),
                confidence=row[2],
                samples=row[3],
                last_updated=datetime.fromisoformat(row[4]),
            )
        return out


class ModalityStore:
    """SQLite-backed per-(learner, modality) modality outcome store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_all(
        self, learner_id: str, outcomes: dict[Modality, ModalityOutcome]
    ) -> None:
        with self._conn:
            for modality, outcome in outcomes.items():
                self._conn.execute(
                    """
                    INSERT INTO modality_outcomes (
                        learner_id, modality, attempts, successes, total_latency_seconds
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(learner_id, modality) DO UPDATE SET
                        attempts = excluded.attempts,
                        successes = excluded.successes,
                        total_latency_seconds = excluded.total_latency_seconds
                    """,
                    (
                        learner_id,
                        modality.value,
                        outcome.attempts,
                        outcome.successes,
                        outcome.total_latency_seconds,
                    ),
                )

    def get_all(self, learner_id: str) -> dict[Modality, ModalityOutcome]:
        rows = self._conn.execute(
            "SELECT modality, attempts, successes, total_latency_seconds "
            "FROM modality_outcomes WHERE learner_id = ?",
            (learner_id,),
        ).fetchall()
        out: dict[Modality, ModalityOutcome] = {}
        for row in rows:
            modality = Modality(row[0])
            out[modality] = ModalityOutcome(
                attempts=row[1],
                successes=row[2],
                total_latency_seconds=row[3],
            )
        return out


class MisconceptionStore:
    """SQLite-backed per-(learner, concept) misconception tally store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_all(self, learner_id: str, tallies: dict[str, int]) -> None:
        now = _utc_now_iso()
        with self._conn:
            for concept, count in tallies.items():
                self._conn.execute(
                    """
                    INSERT INTO misconception_tally (
                        learner_id, concept, count, last_seen_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(learner_id, concept) DO UPDATE SET
                        count = excluded.count,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (learner_id, concept, count, now),
                )

    def get_all(self, learner_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT concept, count FROM misconception_tally WHERE learner_id = ?",
            (learner_id,),
        ).fetchall()
        return {row[0]: row[1] for row in rows}


class ArtifactStore:
    """SQLite-backed next-session artifact store.

    Used by the Phase 4+ proactive planner to stage a first block and
    first check for a learner's next session. Phase 3 exposes the
    round-trip interface only.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        learner_id: str,
        *,
        pathway_json: str,
        first_block_json: str,
        first_check_json: str,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO next_session_artifacts (
                    learner_id, pathway_json, first_block_json,
                    first_check_json, created_at, consumed_at
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(learner_id) DO UPDATE SET
                    pathway_json = excluded.pathway_json,
                    first_block_json = excluded.first_block_json,
                    first_check_json = excluded.first_check_json,
                    created_at = excluded.created_at,
                    consumed_at = NULL
                """,
                (
                    learner_id,
                    pathway_json,
                    first_block_json,
                    first_check_json,
                    _utc_now_iso(),
                ),
            )

    def get(self, learner_id: str) -> dict[str, str | None] | None:
        row = self._conn.execute(
            """
            SELECT pathway_json, first_block_json, first_check_json,
                   created_at, consumed_at
              FROM next_session_artifacts
             WHERE learner_id = ?
            """,
            (learner_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "pathway_json": row[0],
            "first_block_json": row[1],
            "first_check_json": row[2],
            "created_at": row[3],
            "consumed_at": row[4],
        }

    def mark_consumed(self, learner_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE next_session_artifacts SET consumed_at = ? WHERE learner_id = ?",
                (_utc_now_iso(), learner_id),
            )


class KGStore:
    """SQLite-backed append-only knowledge graph triple store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        confidence: float = 1.0,
        source_session: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO knowledge_graph_triples (
                    subject, predicate, object, confidence,
                    source_session, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    subject,
                    predicate,
                    object_,
                    confidence,
                    source_session,
                    _utc_now_iso(),
                ),
            )

    def find_by_subject(self, subject: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT subject, predicate, object, confidence,
                   source_session, created_at
              FROM knowledge_graph_triples
             WHERE subject = ?
             ORDER BY id ASC
            """,
            (subject,),
        ).fetchall()
        return [
            {
                "subject": row[0],
                "predicate": row[1],
                "object": row[2],
                "confidence": row[3],
                "source_session": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]


class SchedulerRunStore:
    """SQLite-backed scheduler-run history store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(
        self,
        *,
        task_name: str,
        learner_id_hash: str | None,
        outcome: str,
        duration_ms: int,
        token_cost_input: int = 0,
        token_cost_output: int = 0,
        error_message: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO scheduler_runs (
                    task_name, learner_id_hash, outcome, duration_ms,
                    token_cost_input, token_cost_output, run_at, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_name,
                    learner_id_hash,
                    outcome,
                    duration_ms,
                    token_cost_input,
                    token_cost_output,
                    _utc_now_iso(),
                    error_message,
                ),
            )

    def list_recent(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT task_name, learner_id_hash, outcome, duration_ms,
                   token_cost_input, token_cost_output, run_at, error_message
              FROM scheduler_runs
             ORDER BY id DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "task_name": row[0],
                "learner_id_hash": row[1],
                "outcome": row[2],
                "duration_ms": row[3],
                "token_cost_input": row[4],
                "token_cost_output": row[5],
                "run_at": row[6],
                "error_message": row[7],
            }
            for row in rows
        ]


class PersistentStore:
    """SQLite-backed aggregate store.

    Holds the connection and every entity store. `initialize()` runs
    the schema DDL; `close()` releases the connection. The caller
    can also pass an already-initialized connection and skip the
    `initialize()` step.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.learners = LearnerStore(conn)
        self.sessions = SessionStore(conn)
        self.events = EventStore(conn)
        self.zpd = ZPDStore(conn)
        self.modality_outcomes = ModalityStore(conn)
        self.misconceptions = MisconceptionStore(conn)
        self.artifacts = ArtifactStore(conn)
        self.kg = KGStore(conn)
        self.scheduler_runs = SchedulerRunStore(conn)

    def initialize(self) -> None:
        initialize_database(self._conn)

    def close(self) -> None:
        self._conn.close()


# -- In-memory implementation -----------------------------------------


class _InMemoryLearnerStore:
    def __init__(self) -> None:
        self._rows: dict[str, LearnerProfile] = {}

    def upsert(self, profile: LearnerProfile) -> None:
        # Store a shallow copy so that later mutations of the in-memory
        # profile don't retroactively change the stored row.
        self._rows[profile.learner_id] = LearnerProfile(
            learner_id=profile.learner_id,
            age_bracket=profile.age_bracket,
            created_at=profile.created_at,
        )

    def get(self, learner_id: str) -> LearnerProfile | None:
        found = self._rows.get(learner_id)
        if found is None:
            return None
        return LearnerProfile(
            learner_id=found.learner_id,
            age_bracket=found.age_bracket,
            created_at=found.created_at,
        )


class _InMemorySessionStore:
    def __init__(self) -> None:
        self._rows: dict[str, Session] = {}

    def upsert(self, session: Session) -> None:
        # Round-trip through JSON so that mutating the caller's copy
        # doesn't silently mutate our stored copy.
        self._rows[session.id] = Session.model_validate_json(
            session.model_dump_json()
        )

    def get(self, session_id: str) -> Session | None:
        found = self._rows.get(session_id)
        if found is None:
            return None
        return Session.model_validate_json(found.model_dump_json())

    def list_for_learner(self, learner_id: str) -> list[Session]:
        return [
            Session.model_validate_json(s.model_dump_json())
            for s in self._rows.values()
            if s.learner_id == learner_id
        ]


class _InMemoryEventStore:
    def __init__(self) -> None:
        self._rows: list[tuple[str, str | None, ObservationEvent]] = []

    def append(
        self,
        event: ObservationEvent,
        *,
        learner_id: str,
        session_id: str | None,
    ) -> None:
        self._rows.append((learner_id, session_id, event))

    def list_for_learner(self, learner_id: str) -> list[ObservationEvent]:
        return [evt for lid, _sid, evt in self._rows if lid == learner_id]


class _InMemoryZPDStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[Domain, ZPDEstimate]] = {}

    def upsert_all(
        self, learner_id: str, estimates: dict[Domain, ZPDEstimate]
    ) -> None:
        # Merge rather than replace: repeated upserts for one domain
        # should overwrite that domain only. This mirrors the SQL
        # ON CONFLICT behavior.
        bucket = self._rows.setdefault(learner_id, {})
        for domain, estimate in estimates.items():
            bucket[domain] = estimate.model_copy()

    def get_all(self, learner_id: str) -> dict[Domain, ZPDEstimate]:
        bucket = self._rows.get(learner_id, {})
        return {domain: estimate.model_copy() for domain, estimate in bucket.items()}


class _InMemoryModalityStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[Modality, ModalityOutcome]] = {}

    def upsert_all(
        self, learner_id: str, outcomes: dict[Modality, ModalityOutcome]
    ) -> None:
        bucket = self._rows.setdefault(learner_id, {})
        for modality, outcome in outcomes.items():
            bucket[modality] = outcome.model_copy()

    def get_all(self, learner_id: str) -> dict[Modality, ModalityOutcome]:
        bucket = self._rows.get(learner_id, {})
        return {
            modality: outcome.model_copy() for modality, outcome in bucket.items()
        }


class _InMemoryMisconceptionStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, int]] = {}

    def upsert_all(self, learner_id: str, tallies: dict[str, int]) -> None:
        bucket = self._rows.setdefault(learner_id, {})
        for concept, count in tallies.items():
            bucket[concept] = count

    def get_all(self, learner_id: str) -> dict[str, int]:
        return dict(self._rows.get(learner_id, {}))


class _InMemoryArtifactStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, str | None]] = {}

    def upsert(
        self,
        learner_id: str,
        *,
        pathway_json: str,
        first_block_json: str,
        first_check_json: str,
    ) -> None:
        self._rows[learner_id] = {
            "pathway_json": pathway_json,
            "first_block_json": first_block_json,
            "first_check_json": first_check_json,
            "created_at": _utc_now_iso(),
            "consumed_at": None,
        }

    def get(self, learner_id: str) -> dict[str, str | None] | None:
        found = self._rows.get(learner_id)
        if found is None:
            return None
        return deepcopy(found)

    def mark_consumed(self, learner_id: str) -> None:
        if learner_id in self._rows:
            self._rows[learner_id]["consumed_at"] = _utc_now_iso()


class _InMemoryKGStore:
    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []

    def append_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        confidence: float = 1.0,
        source_session: str | None = None,
    ) -> None:
        self._rows.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object_,
                "confidence": confidence,
                "source_session": source_session,
                "created_at": _utc_now_iso(),
            }
        )

    def find_by_subject(self, subject: str) -> list[dict[str, object]]:
        return [deepcopy(row) for row in self._rows if row["subject"] == subject]


class _InMemorySchedulerRunStore:
    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []

    def append(
        self,
        *,
        task_name: str,
        learner_id_hash: str | None,
        outcome: str,
        duration_ms: int,
        token_cost_input: int = 0,
        token_cost_output: int = 0,
        error_message: str | None = None,
    ) -> None:
        self._rows.append(
            {
                "task_name": task_name,
                "learner_id_hash": learner_id_hash,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "token_cost_input": token_cost_input,
                "token_cost_output": token_cost_output,
                "run_at": _utc_now_iso(),
                "error_message": error_message,
            }
        )

    def list_recent(self, limit: int = 50) -> list[dict[str, object]]:
        return [deepcopy(row) for row in reversed(self._rows[-limit:])]


class InMemoryPersistentStore:
    """Dict-backed drop-in for `PersistentStore`.

    Exposes the same entity-store attributes, same method signatures,
    and same behavioral contract (round-trip fidelity, isolation
    between instances). Used in tests and as the default backend for
    `AppState` when no SQLite path is configured.
    """

    def __init__(self) -> None:
        self.learners: _LearnerStoreProto = _InMemoryLearnerStore()
        self.sessions: _SessionStoreProto = _InMemorySessionStore()
        self.events: _EventStoreProto = _InMemoryEventStore()
        self.zpd: _ZPDStoreProto = _InMemoryZPDStore()
        self.modality_outcomes: _ModalityStoreProto = _InMemoryModalityStore()
        self.misconceptions: _MisconceptionStoreProto = _InMemoryMisconceptionStore()
        self.artifacts: _ArtifactStoreProto = _InMemoryArtifactStore()
        self.kg: _KGStoreProto = _InMemoryKGStore()
        self.scheduler_runs: _SchedulerRunStoreProto = _InMemorySchedulerRunStore()

    def initialize(self) -> None:
        """No-op for parity with `PersistentStore.initialize()`."""

    def close(self) -> None:
        """No-op for parity with `PersistentStore.close()`."""


