"""AppState identity cache + persistence wiring tests (spec §4.6.4).

These tests pin down the contract that resolves spec-review item B3:

1. `AppState.get(session_id)` returns the SAME object on repeated
   calls so that mutators like `SessionRunner.record_check` can
   continue mutating bundles in place.
2. `AppState.checkpoint(session_id)` flushes the cached bundle to
   the persistent store without evicting it from cache.
3. `AppState.drop(session_id)` flushes and then evicts.
4. The LRU cache evicts the oldest entry when it grows past
   `cache_size`, but re-persists it before dropping it from memory.
"""

from __future__ import annotations

import pytest

from clawstu.api.state import AppState, SessionBundle
from clawstu.engagement.session import SessionPhase, SessionRunner
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import Domain


def _new_bundle(runner: SessionRunner, learner_id: str) -> SessionBundle:
    profile, session = runner.onboard(
        learner_id=learner_id,
        age=15,
        domain=Domain.US_HISTORY,
    )
    return SessionBundle(profile=profile, session=session)


def test_put_then_get_returns_same_object_by_identity() -> None:
    state = AppState(persistence=InMemoryPersistentStore())
    bundle = _new_bundle(state.runner, "learner-1")
    state.put(bundle)
    first = state.get(bundle.session.id)
    second = state.get(bundle.session.id)
    assert first is second
    assert first is bundle


def test_mutation_in_place_propagates() -> None:
    state = AppState(persistence=InMemoryPersistentStore())
    bundle = _new_bundle(state.runner, "learner-2")
    state.put(bundle)
    fetched = state.get(bundle.session.id)
    fetched.session.phase = SessionPhase.TEACHING
    refetched = state.get(bundle.session.id)
    assert refetched.session.phase is SessionPhase.TEACHING


def test_checkpoint_writes_to_persistence_without_eviction() -> None:
    persistence = InMemoryPersistentStore()
    state = AppState(persistence=persistence)
    bundle = _new_bundle(state.runner, "learner-3")
    state.put(bundle)

    bundle.session.phase = SessionPhase.TEACHING
    state.checkpoint(bundle.session.id)

    persisted = persistence.sessions.get(bundle.session.id)
    assert persisted is not None
    assert persisted.phase is SessionPhase.TEACHING

    # Still cached — get() returns the same object.
    assert state.get(bundle.session.id) is bundle


def test_drop_flushes_then_evicts() -> None:
    persistence = InMemoryPersistentStore()
    state = AppState(persistence=persistence)
    bundle = _new_bundle(state.runner, "learner-4")
    state.put(bundle)

    bundle.session.phase = SessionPhase.TEACHING
    state.drop(bundle.session.id)

    # The persisted copy reflects the in-place mutation.
    persisted = persistence.sessions.get(bundle.session.id)
    assert persisted is not None
    assert persisted.phase is SessionPhase.TEACHING

    # The cache is empty for this session, so a new get() must rehydrate
    # from persistence and return a *new* object.
    rehydrated = state.get(bundle.session.id)
    assert rehydrated is not bundle
    assert rehydrated.session.phase is SessionPhase.TEACHING


def test_cache_eviction_re_persists() -> None:
    persistence = InMemoryPersistentStore()
    state = AppState(persistence=persistence, cache_size=2)
    bundles = [_new_bundle(state.runner, f"learner-{i}") for i in range(3)]
    for b in bundles:
        state.put(b)

    # The first bundle should have been evicted from the cache and
    # re-persisted on the way out.
    persisted = persistence.sessions.get(bundles[0].session.id)
    assert persisted is not None

    # Calling get() rehydrates a fresh copy that is NOT the original
    # in-memory object.
    rehydrated = state.get(bundles[0].session.id)
    assert rehydrated is not bundles[0]
    assert rehydrated.session.learner_id == "learner-0"


def test_get_unknown_session_raises_keyerror() -> None:
    state = AppState(persistence=InMemoryPersistentStore())
    with pytest.raises(KeyError):
        state.get("does-not-exist")
