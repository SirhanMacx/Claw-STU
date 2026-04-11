"""Process-local app state with identity-cached persistence (spec §4.6.4).

The previous version of this module was a thin dict around the
session bundle map. Phase 3 wires it to a `PersistentStore` (or its
in-memory drop-in `InMemoryPersistentStore`) while preserving the
contract that `SessionRunner.record_check` and friends rely on:
`AppState.get(session_id)` must return the SAME object on repeated
calls so in-place mutations to `bundle.session` and `bundle.profile`
propagate.

The mechanism is a bounded LRU identity cache:

- `put(bundle)`        — store the bundle, persist it, evict if full.
- `get(session_id)`    — return the cached bundle, or rehydrate from
                          persistence and cache the result.
- `checkpoint(id)`     — re-persist without evicting (call after each
                          mutator).
- `drop(session_id)`   — flush, then evict.

`SessionBundle._persisted_event_count` tracks how many of the
profile's events have already been written to the event store, so
each call to `_persist` only appends new events instead of dumping
the whole list every time.

For backwards compatibility with `clawstu.api.admin.health`, the
class still exposes a `sessions` property that returns the in-cache
bundles as a dict view (read-only — modifications must go through
`put`/`drop`).
"""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import RLock

from clawstu.engagement.session import Session, SessionRunner
from clawstu.persistence.store import (
    AbstractPersistentStore,
    InMemoryPersistentStore,
)
from clawstu.profile.model import LearnerProfile

_DEFAULT_CACHE_SIZE = 1024


@dataclass
class SessionBundle:
    profile: LearnerProfile
    session: Session
    _persisted_event_count: int = field(default=0, repr=False)


class AppState:
    """Identity-cached session state backed by a persistent store.

    The cache is keyed by `session_id` and uses an `OrderedDict` for
    LRU tracking. The default cache size is `_DEFAULT_CACHE_SIZE`,
    overridable via the `STU_SESSION_CACHE_SIZE` environment variable
    or the `cache_size` constructor argument.

    The default persistence backend is `InMemoryPersistentStore`,
    which gives the same behavioral contract as the SQLite-backed
    store but does not touch the filesystem. SQLite wiring waits
    until a later phase introduces the config/CLI plumbing.
    """

    def __init__(
        self,
        persistence: AbstractPersistentStore | None = None,
        *,
        cache_size: int | None = None,
        runner: SessionRunner | None = None,
    ) -> None:
        self._persistence: AbstractPersistentStore = (
            persistence if persistence is not None else InMemoryPersistentStore()
        )
        self._cache: OrderedDict[str, SessionBundle] = OrderedDict()
        if cache_size is None:
            env_value = os.environ.get("STU_SESSION_CACHE_SIZE")
            cache_size = int(env_value) if env_value else _DEFAULT_CACHE_SIZE
        self._cache_size = cache_size
        self._lock = RLock()
        self.runner: SessionRunner = runner or SessionRunner()

    # -- Read-only views ------------------------------------------------

    @property
    def sessions(self) -> Mapping[str, SessionBundle]:
        """Return a snapshot of cached bundles for read-only inspection.

        `clawstu.api.admin.health` calls `len(state.sessions)` to
        report the active session count. Returning a dict copy keeps
        callers from mutating the underlying cache by accident.
        """
        with self._lock:
            return dict(self._cache)

    # -- Mutators -------------------------------------------------------

    def put(self, bundle: SessionBundle) -> None:
        """Add a fresh bundle, persist it, and evict if needed."""
        with self._lock:
            self._cache[bundle.session.id] = bundle
            self._cache.move_to_end(bundle.session.id)
            self._persist(bundle)
            self._evict_if_needed()

    def get(self, session_id: str) -> SessionBundle:
        """Return the cached bundle, rehydrating from persistence if necessary.

        Raises `KeyError` if the session is unknown to both the cache
        and the persistent store.
        """
        with self._lock:
            cached = self._cache.get(session_id)
            if cached is not None:
                self._cache.move_to_end(session_id)
                return cached
            session = self._persistence.sessions.get(session_id)
            if session is None:
                raise KeyError(f"unknown session: {session_id}")
            profile = self._persistence.learners.get(session.learner_id)
            if profile is None:
                raise KeyError(
                    f"session's profile missing: {session.learner_id}"
                )
            # Rehydrate the substores into the in-memory profile so
            # downstream code keeps seeing one consistent object.
            profile.zpd_by_domain = self._persistence.zpd.get_all(
                session.learner_id
            )
            profile.modality_outcomes = self._persistence.modality_outcomes.get_all(
                session.learner_id
            )
            profile.misconceptions = self._persistence.misconceptions.get_all(
                session.learner_id
            )
            profile.events = self._persistence.events.list_for_learner(
                session.learner_id
            )
            bundle = SessionBundle(
                profile=profile,
                session=session,
                _persisted_event_count=len(profile.events),
            )
            self._cache[session_id] = bundle
            self._cache.move_to_end(session_id)
            self._evict_if_needed()
            return bundle

    def drop(self, session_id: str) -> None:
        """Flush the cached bundle to persistence and evict it."""
        with self._lock:
            cached = self._cache.pop(session_id, None)
            if cached is not None:
                self._persist(cached)

    def checkpoint(self, session_id: str) -> None:
        """Re-persist the cached bundle without evicting it.

        Called by API handlers after every mutating runner call so
        that bundle changes survive a process restart.
        """
        with self._lock:
            cached = self._cache.get(session_id)
            if cached is not None:
                self._persist(cached)

    # -- Internal -------------------------------------------------------

    def _persist(self, bundle: SessionBundle) -> None:
        self._persistence.learners.upsert(bundle.profile)
        self._persistence.sessions.upsert(bundle.session)
        # Append only events that have not yet been persisted. The
        # bundle tracks the high-water mark, so each checkpoint pushes
        # exactly the new events from this run.
        new_events = bundle.profile.events[bundle._persisted_event_count :]
        for event in new_events:
            self._persistence.events.append(
                event,
                learner_id=bundle.profile.learner_id,
                session_id=bundle.session.id,
            )
        bundle._persisted_event_count = len(bundle.profile.events)
        self._persistence.zpd.upsert_all(
            bundle.profile.learner_id, bundle.profile.zpd_by_domain
        )
        self._persistence.modality_outcomes.upsert_all(
            bundle.profile.learner_id, bundle.profile.modality_outcomes
        )
        self._persistence.misconceptions.upsert_all(
            bundle.profile.learner_id, bundle.profile.misconceptions
        )

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self._cache_size:
            _evicted_id, evicted_bundle = self._cache.popitem(last=False)
            self._persist(evicted_bundle)


_APP_STATE = AppState()


def get_state() -> AppState:
    """Return the process-local app state.

    FastAPI dependency-injects this. Tests can replace the global
    state by constructing their own `AppState` and passing it in
    via `app.dependency_overrides`.
    """
    return _APP_STATE
