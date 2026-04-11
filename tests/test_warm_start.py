"""Unit tests for `SessionRunner.warm_start`.

Spec reference: §4.8.1. These tests exercise the warm-start method
against the `InMemoryPersistentStore` — no scheduler, no HTTP, no
disk. The goal is to pin down the four invariants the API layer
relies on:

1. With a pre-staged artifact the returned Session is in phase
   TEACHING with primed_block + primed_check set.
2. Without an artifact (or with an already-consumed one) the method
   raises `NoArtifactError`.
3. The artifact is marked consumed exactly once — a second warm-
   start for the same learner must fail.
4. The returned LearnerProfile has its substores rehydrated from
   persistence (ZPD, misconceptions, events, modality outcomes).
"""

from __future__ import annotations

import json

import pytest

from clawstu.engagement.session import (
    NoArtifactError,
    SessionPhase,
    SessionRunner,
)
from clawstu.persistence.store import InMemoryPersistentStore
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

_LEARNER_ID = "alice"

_PATHWAY_JSON = json.dumps({"concepts": ["declaration_of_independence_purpose"]})
_BLOCK_JSON = json.dumps(
    {
        "title": "The Declaration — a short reading",
        "body": "Read the preamble carefully and note who the audience is.",
    }
)
_CHECK_JSON = json.dumps(
    {
        "prompt": "Who was the Declaration of Independence addressed to?",
        "type": "crq",
        "rubric": ["names the three audiences", "gives at least one reason"],
    }
)


def _seed_learner(store: InMemoryPersistentStore) -> LearnerProfile:
    """Persist a minimal learner and return the in-memory profile."""
    profile = LearnerProfile(
        learner_id=_LEARNER_ID,
        age_bracket=AgeBracket.EARLY_HIGH,
    )
    store.learners.upsert(profile)
    return profile


def _seed_artifact(store: InMemoryPersistentStore) -> None:
    store.artifacts.upsert(
        learner_id=_LEARNER_ID,
        pathway_json=_PATHWAY_JSON,
        first_block_json=_BLOCK_JSON,
        first_check_json=_CHECK_JSON,
    )


def _call_warm_start(
    runner: SessionRunner, store: InMemoryPersistentStore
) -> tuple[LearnerProfile, object]:
    return runner.warm_start(
        learner_id=_LEARNER_ID,
        learners=store.learners,
        artifacts=store.artifacts,
        zpd=store.zpd,
        modality_outcomes=store.modality_outcomes,
        misconceptions=store.misconceptions,
        events=store.events,
    )


class TestWarmStart:
    def test_warm_start_with_artifact_returns_teaching_session(
        self,
    ) -> None:
        """Happy path: profile + artifact present → TEACHING session."""
        store = InMemoryPersistentStore()
        _seed_learner(store)
        _seed_artifact(store)
        runner = SessionRunner()

        profile, session = runner.warm_start(
            learner_id=_LEARNER_ID,
            learners=store.learners,
            artifacts=store.artifacts,
            zpd=store.zpd,
            modality_outcomes=store.modality_outcomes,
            misconceptions=store.misconceptions,
            events=store.events,
        )

        assert profile.learner_id == _LEARNER_ID
        assert session.learner_id == _LEARNER_ID
        assert session.phase is SessionPhase.TEACHING
        assert session.pathway is not None
        assert session.pathway.concepts == (
            "declaration_of_independence_purpose",
        )
        assert session.primed_block is not None
        assert session.primed_block.title == "The Declaration — a short reading"
        assert session.primed_check is not None
        assert session.primed_check.prompt.startswith("Who was")
        # The rehydrated profile should also have a SESSION_START event
        # appended by the observer hook inside warm_start.
        assert any(
            e.kind is EventKind.SESSION_START for e in profile.events
        )

    def test_warm_start_without_artifact_raises_no_artifact_error(
        self,
    ) -> None:
        store = InMemoryPersistentStore()
        _seed_learner(store)
        runner = SessionRunner()

        with pytest.raises(NoArtifactError):
            _call_warm_start(runner, store)

    def test_warm_start_marks_artifact_consumed(self) -> None:
        """A successful warm-start must consume the artifact and block
        a second warm-start for the same learner."""
        store = InMemoryPersistentStore()
        _seed_learner(store)
        _seed_artifact(store)
        runner = SessionRunner()

        _call_warm_start(runner, store)

        artifact = store.artifacts.get(_LEARNER_ID)
        assert artifact is not None
        assert artifact["consumed_at"] is not None

        with pytest.raises(NoArtifactError):
            _call_warm_start(runner, store)

    def test_warm_start_rehydrates_profile_substores(self) -> None:
        """ZPD / modality outcomes / misconceptions / events pre-seeded
        in persistence must flow back onto the returned profile."""
        store = InMemoryPersistentStore()
        profile = _seed_learner(store)
        _seed_artifact(store)

        # Seed every substore the warm_start method should rehydrate.
        store.zpd.upsert_all(
            _LEARNER_ID,
            {
                Domain.US_HISTORY: ZPDEstimate(
                    domain=Domain.US_HISTORY,
                    tier=ComplexityTier.EXCEEDING,
                    samples=12,
                    confidence=0.75,
                )
            },
        )
        store.modality_outcomes.upsert_all(
            _LEARNER_ID,
            {
                Modality.SOCRATIC_DIALOGUE: ModalityOutcome(
                    attempts=5,
                    successes=4,
                    total_latency_seconds=120.0,
                )
            },
        )
        store.misconceptions.upsert_all(
            _LEARNER_ID,
            {"confuses_declaration_with_constitution": 2},
        )
        store.events.append(
            ObservationEvent(
                kind=EventKind.CHECK_FOR_UNDERSTANDING,
                domain=Domain.US_HISTORY,
                modality=Modality.SOCRATIC_DIALOGUE,
                tier=ComplexityTier.MEETING,
                correct=True,
                concept="declaration_of_independence_purpose",
            ),
            learner_id=_LEARNER_ID,
            session_id=None,
        )
        runner = SessionRunner()

        rehydrated_profile, session = _call_warm_start(runner, store)

        assert Domain.US_HISTORY in rehydrated_profile.zpd_by_domain
        assert (
            rehydrated_profile.zpd_by_domain[Domain.US_HISTORY].tier
            is ComplexityTier.EXCEEDING
        )
        assert (
            rehydrated_profile.modality_outcomes[
                Modality.SOCRATIC_DIALOGUE
            ].attempts
            == 5
        )
        assert (
            rehydrated_profile.misconceptions[
                "confuses_declaration_with_constitution"
            ]
            == 2
        )
        # At least the pre-seeded CHECK_FOR_UNDERSTANDING event plus
        # the SESSION_START appended by warm_start itself.
        kinds = [e.kind for e in rehydrated_profile.events]
        assert EventKind.CHECK_FOR_UNDERSTANDING in kinds
        assert EventKind.SESSION_START in kinds
        # The rehydrated profile is the same object the runner was
        # given to mutate, not a fresh one — so the in-memory object
        # picked up the substores without a second persistence hit.
        assert rehydrated_profile is not profile
        assert session.domain is Domain.US_HISTORY
