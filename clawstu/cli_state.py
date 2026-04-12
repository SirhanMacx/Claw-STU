"""Cross-invocation JSON persistence bridge for the CLI layer.

Phase 8 Part 2B introduces a handful of companion commands --
``wiki``, ``progress``, ``history``, ``review``, ``ask``, plus real
``profile export/import`` -- that need learner data to survive
across CLI invocations. The Phase 3 ``PersistentStore`` is a SQLite-
backed entity store that satisfies that contract, but wiring SQLite
through the CLI is a larger undertaking (migrations, connection
lifetime, WAL file management) that belongs to a later phase.

This module is the bridge: a small JSON-on-disk helper that snapshots
an :class:`InMemoryPersistentStore` to ``~/.claw-stu/state.json`` and
round-trips it back on the next invocation. It is deliberately
boring -- one file, atomic write, strict pydantic validation on load.

Both :mod:`clawstu.cli_chat` (the Part 2A ``learn``/``resume`` loop)
and :mod:`clawstu.cli_companions` (the Part 2B command bodies) import
:func:`default_stores` to get a fresh in-memory store seeded from
the JSON snapshot, and :func:`save_persistence_to_disk` to flush
after a mutating command finishes.

The module sits in the ``_cli`` layer of the hierarchy guard and is
allowed to reach into ``persistence`` + ``profile`` + ``engagement``
+ ``memory``. Nothing below the CLI layer imports from here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from clawstu.engagement.session import Session
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig, ensure_data_dir, load_config
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import (
    Domain,
    LearnerProfile,
    Modality,
    ModalityOutcome,
    ObservationEvent,
    ZPDEstimate,
)

_STATE_FILENAME = "state.json"
_SCHEMA_VERSION = 1


class NoLearnersError(RuntimeError):
    """Raised when a CLI command needs a learner but the store is empty.

    The CLI layer turns this into a clean ``typer.Exit(1)`` with a
    friendly "no learners yet" message. Keeping the exception out of
    ``typer``-specific land lets tests assert on it without pulling
    in the whole Click/Typer runner scaffolding.
    """


@dataclass(frozen=True)
class StoreBundle:
    """The store quartet the CLI commands depend on.

    Groups the four things that have to be constructed together so a
    command body takes a single parameter instead of unpacking four
    arguments from a tuple. The ``state_path`` is returned alongside
    the stores so a mutating command can write back to the same file
    without having to re-derive the path from ``cfg``.
    """

    persistence: InMemoryPersistentStore
    brain_store: BrainStore
    cfg: AppConfig
    state_path: Path


def default_stores() -> StoreBundle:
    """Return a fresh :class:`StoreBundle` seeded from the disk snapshot.

    Resolves :class:`AppConfig` via :func:`load_config` so the same
    env-var / secrets.json precedence rules apply as the rest of the
    CLI. Calls :func:`ensure_data_dir` so the data directory exists
    with correct permissions before any file operation touches it.
    Returns a brand-new store quartet on every call -- callers MUST
    NOT cache the bundle because the tests drive ``CLAW_STU_DATA_DIR``
    through ``monkeypatch`` per-test.
    """
    cfg = load_config()
    ensure_data_dir(cfg)
    state_path = cfg.data_dir / _STATE_FILENAME
    persistence = load_persistence_from_disk(state_path)
    brain_store = BrainStore(base_dir=cfg.data_dir / "brain")
    return StoreBundle(
        persistence=persistence,
        brain_store=brain_store,
        cfg=cfg,
        state_path=state_path,
    )


def _read_and_validate_state_json(path: Path) -> dict:
    """Read the state JSON file and validate its schema version.

    Returns the parsed dict. Raises ValueError on bad JSON or
    unsupported schema version.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"clawstu state file at {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"clawstu state file at {path} must be a JSON object, "
            f"got {type(raw).__name__}"
        )
    version = raw.get("schema_version", _SCHEMA_VERSION)
    if version != _SCHEMA_VERSION:
        raise ValueError(
            f"clawstu state file at {path} has schema_version={version}, "
            f"expected {_SCHEMA_VERSION}"
        )
    return raw


def _load_learners_and_sessions(
    store: InMemoryPersistentStore, raw: dict,
) -> None:
    """Deserialize learners and sessions into the store."""
    for entry in raw.get("learners", []):
        store.learners.upsert(LearnerProfile.model_validate(entry))
    for entry in raw.get("sessions", []):
        store.sessions.upsert(Session.model_validate(entry))


def _load_events(store: InMemoryPersistentStore, raw: dict) -> None:
    """Deserialize observation events into the store.

    Events carry the (learner_id, session_id) tuple alongside the
    ObservationEvent body so we can restore the in-memory tuple
    storage exactly.
    """
    for entry in raw.get("events", []):
        event_data = entry.get("event")
        learner_id = entry.get("learner_id")
        session_id = entry.get("session_id")
        if not isinstance(event_data, dict) or not isinstance(learner_id, str):
            continue
        resolved_session: str | None = (
            session_id if isinstance(session_id, str) else None
        )
        store.events.append(
            ObservationEvent.model_validate(event_data),
            learner_id=learner_id,
            session_id=resolved_session,
        )


def _load_zpd_estimates(store: InMemoryPersistentStore, raw: dict) -> None:
    """Deserialize ZPD estimates per learner per domain into the store."""
    for learner_id, per_domain in (raw.get("zpd") or {}).items():
        if not isinstance(per_domain, dict):
            continue
        zpd_estimates: dict[Domain, ZPDEstimate] = {}
        for domain_key, estimate_data in per_domain.items():
            if not isinstance(estimate_data, dict):
                continue
            try:
                domain = Domain(domain_key)
            except ValueError:
                continue
            zpd_estimates[domain] = ZPDEstimate.model_validate(estimate_data)
        if zpd_estimates:
            store.zpd.upsert_all(learner_id, zpd_estimates)


def _load_modality_outcomes(
    store: InMemoryPersistentStore, raw: dict,
) -> None:
    """Deserialize modality outcomes per learner into the store."""
    for learner_id, per_modality in (raw.get("modality_outcomes") or {}).items():
        if not isinstance(per_modality, dict):
            continue
        modality_outcomes: dict[Modality, ModalityOutcome] = {}
        for modality_key, outcome_data in per_modality.items():
            if not isinstance(outcome_data, dict):
                continue
            try:
                modality = Modality(modality_key)
            except ValueError:
                continue
            modality_outcomes[modality] = ModalityOutcome.model_validate(
                outcome_data,
            )
        if modality_outcomes:
            store.modality_outcomes.upsert_all(learner_id, modality_outcomes)


def _load_misconceptions(store: InMemoryPersistentStore, raw: dict) -> None:
    """Deserialize misconception tallies per learner into the store."""
    for learner_id, tallies in (raw.get("misconceptions") or {}).items():
        if not isinstance(tallies, dict):
            continue
        coerced: dict[str, int] = {}
        for concept, count in tallies.items():
            if isinstance(count, int):
                coerced[concept] = count
        if coerced:
            store.misconceptions.upsert_all(learner_id, coerced)


def _load_kg_triples(store: InMemoryPersistentStore, raw: dict) -> None:
    """Deserialize knowledge-graph triples into the store."""
    for triple in raw.get("kg", []):
        if not isinstance(triple, dict):
            continue
        subject = triple.get("subject")
        predicate = triple.get("predicate")
        obj = triple.get("object")
        if not (
            isinstance(subject, str)
            and isinstance(predicate, str)
            and isinstance(obj, str)
        ):
            continue
        confidence = triple.get("confidence", 1.0)
        source_session = triple.get("source_session")
        store.kg.append_triple(
            subject,
            predicate,
            obj,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else 1.0,
            source_session=(
                source_session if isinstance(source_session, str) else None
            ),
        )


def load_persistence_from_disk(path: Path) -> InMemoryPersistentStore:
    """Load a JSON snapshot into a fresh :class:`InMemoryPersistentStore`.

    Returns an empty store if the file does not exist yet. A bad JSON
    payload or unknown ``schema_version`` raises ``ValueError`` so a
    corrupted state file fails loud instead of silently wiping history.
    """
    store = InMemoryPersistentStore()
    if not path.exists():
        return store

    raw = _read_and_validate_state_json(path)
    _load_learners_and_sessions(store, raw)
    _load_events(store, raw)
    _load_zpd_estimates(store, raw)
    _load_modality_outcomes(store, raw)
    _load_misconceptions(store, raw)
    _load_kg_triples(store, raw)
    return store


def save_persistence_to_disk(
    store: InMemoryPersistentStore, path: Path,
) -> None:
    """Atomically snapshot a store to ``path``.

    Called at the end of any CLI command that mutates state (``learn``,
    ``resume``, ``profile import``). Read-only commands (``wiki``,
    ``progress``, ``history``, ``review``, ``ask``, ``profile export``)
    should NOT call this -- their view of the world is a strict subset
    of what's already on disk and rewriting would be pure churn.

    The write is a temp-file + rename so a process kill mid-write
    cannot leave a partial snapshot. All in-memory substores are
    walked explicitly rather than introspected via ``vars()`` so the
    format stays stable even when the ``InMemoryPersistentStore``
    grows new private fields.
    """
    payload: dict[str, object] = {"schema_version": _SCHEMA_VERSION}

    learner_ids: list[str] = []
    learners_out: list[dict[str, object]] = []
    for learner_id, profile in _iter_learners(store):
        learner_ids.append(learner_id)
        learners_out.append(profile.model_dump(mode="json"))
    payload["learners"] = learners_out

    sessions_out: list[dict[str, object]] = []
    for session in _iter_sessions(store):
        sessions_out.append(session.model_dump(mode="json"))
    payload["sessions"] = sessions_out

    events_out: list[dict[str, object]] = []
    for learner_id, session_id, event in _iter_events(store):
        events_out.append(
            {
                "learner_id": learner_id,
                "session_id": session_id,
                "event": event.model_dump(mode="json"),
            }
        )
    payload["events"] = events_out

    zpd_out: dict[str, dict[str, dict[str, object]]] = {}
    modality_out: dict[str, dict[str, dict[str, object]]] = {}
    misc_out: dict[str, dict[str, int]] = {}
    for learner_id in learner_ids:
        per_domain: dict[str, dict[str, object]] = {}
        for domain, estimate in store.zpd.get_all(learner_id).items():
            per_domain[domain.value] = estimate.model_dump(mode="json")
        if per_domain:
            zpd_out[learner_id] = per_domain

        per_modality: dict[str, dict[str, object]] = {}
        for modality, outcome in store.modality_outcomes.get_all(
            learner_id,
        ).items():
            per_modality[modality.value] = outcome.model_dump(mode="json")
        if per_modality:
            modality_out[learner_id] = per_modality

        tallies = store.misconceptions.get_all(learner_id)
        if tallies:
            misc_out[learner_id] = dict(tallies)

    payload["zpd"] = zpd_out
    payload["modality_outcomes"] = modality_out
    payload["misconceptions"] = misc_out

    kg_out: list[dict[str, object]] = []
    for triple in _iter_kg_triples(store):
        kg_out.append(triple)
    payload["kg"] = kg_out

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def most_recent_learner(store: InMemoryPersistentStore) -> str:
    """Return the learner id whose most recent session is newest.

    Used by every Part 2B command to default ``--learner`` when the
    caller omits it. Raises :exc:`NoLearnersError` if the store has
    zero learners, or zero sessions for every known learner -- in
    either case the CLI layer turns the exception into a friendly
    "no learners yet" message pointing the student at ``clawstu learn``.

    Ties are broken by learner id (lexicographic) for determinism --
    the same snapshot should resolve to the same default regardless
    of iteration order.
    """
    learner_ids = [lid for lid, _profile in _iter_learners(store)]
    if not learner_ids:
        raise NoLearnersError("no learners yet")

    best_id: str | None = None
    best_started: datetime | None = None
    for learner_id in learner_ids:
        sessions = store.sessions.list_for_learner(learner_id)
        if not sessions:
            continue
        latest = max(sessions, key=lambda s: s.started_at)
        started = latest.started_at
        if best_id is None or best_started is None:
            best_id = learner_id
            best_started = started
            continue
        if started > best_started or (
            started == best_started and learner_id < best_id
        ):
            best_id = learner_id
            best_started = started

    if best_id is not None:
        return best_id

    # Every learner has zero sessions -- fall back to the lexicographic
    # minimum learner id so the result is still deterministic. This is
    # the "learner created but never taught" edge case.
    return sorted(learner_ids)[0]


# ---------------------------------------------------------------------------
# Internal store walkers
# ---------------------------------------------------------------------------
#
# The InMemoryPersistentStore exposes per-entity wrappers without a
# "list everything" method. We walk the private ``_rows`` attribute
# because writing our own iterators here would duplicate the store's
# state. These helpers are the only place we reach into the private
# dicts, which keeps the coupling localized.


def _iter_learners(
    store: InMemoryPersistentStore,
) -> list[tuple[str, LearnerProfile]]:
    """Return ``(learner_id, profile)`` pairs in insertion order."""
    raw: object = getattr(store.learners, "_rows", {})
    if not isinstance(raw, dict):
        return []
    out: list[tuple[str, LearnerProfile]] = []
    for learner_id, profile in raw.items():
        if isinstance(profile, LearnerProfile):
            out.append((learner_id, profile))
    return out


def _iter_sessions(store: InMemoryPersistentStore) -> list[Session]:
    """Return every persisted :class:`Session` in insertion order."""
    raw: object = getattr(store.sessions, "_rows", {})
    if not isinstance(raw, dict):
        return []
    return [s for s in raw.values() if isinstance(s, Session)]


def _iter_events(
    store: InMemoryPersistentStore,
) -> list[tuple[str, str | None, ObservationEvent]]:
    """Return every persisted observation event with its (learner, session)."""
    raw: object = getattr(store.events, "_rows", [])
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str | None, ObservationEvent]] = []
    for row in raw:
        if not (isinstance(row, tuple) and len(row) == 3):
            continue
        learner_id, session_id, event = row
        if not isinstance(learner_id, str):
            continue
        if not isinstance(event, ObservationEvent):
            continue
        resolved_session: str | None = (
            session_id if isinstance(session_id, str) else None
        )
        out.append((learner_id, resolved_session, event))
    return out


def _iter_kg_triples(
    store: InMemoryPersistentStore,
) -> list[dict[str, object]]:
    """Return every KG triple in insertion order."""
    raw: object = getattr(store.kg, "_rows", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, object]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "subject": row.get("subject"),
                "predicate": row.get("predicate"),
                "object": row.get("object"),
                "confidence": row.get("confidence", 1.0),
                "source_session": row.get("source_session"),
            }
        )
    return out


__all__ = [
    "NoLearnersError",
    "StoreBundle",
    "default_stores",
    "load_persistence_from_disk",
    "most_recent_learner",
    "save_persistence_to_disk",
]
