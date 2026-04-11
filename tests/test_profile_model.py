"""Unit tests for the learner profile data model."""

from __future__ import annotations

import pytest

from src.profile.export import export_to_json, import_from_json
from src.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ObservationEvent,
)
from src.profile.observer import Observer


class TestAgeBracket:
    @pytest.mark.parametrize(
        ("age", "expected"),
        [
            (5, AgeBracket.EARLY_ELEMENTARY),
            (7, AgeBracket.EARLY_ELEMENTARY),
            (8, AgeBracket.LATE_ELEMENTARY),
            (10, AgeBracket.LATE_ELEMENTARY),
            (11, AgeBracket.MIDDLE),
            (13, AgeBracket.MIDDLE),
            (14, AgeBracket.EARLY_HIGH),
            (15, AgeBracket.EARLY_HIGH),
            (16, AgeBracket.LATE_HIGH),
            (17, AgeBracket.LATE_HIGH),
            (18, AgeBracket.ADULT),
            (45, AgeBracket.ADULT),
        ],
    )
    def test_from_age(self, age: int, expected: AgeBracket) -> None:
        assert AgeBracket.from_age(age) is expected

    def test_from_age_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            AgeBracket.from_age(-1)
        with pytest.raises(ValueError):
            AgeBracket.from_age(200)


class TestComplexityTier:
    def test_step_up_from_approaching(self) -> None:
        assert ComplexityTier.APPROACHING.stepped_up() is ComplexityTier.MEETING

    def test_step_up_from_meeting(self) -> None:
        assert ComplexityTier.MEETING.stepped_up() is ComplexityTier.EXCEEDING

    def test_step_up_at_top_saturates(self) -> None:
        assert ComplexityTier.EXCEEDING.stepped_up() is ComplexityTier.EXCEEDING

    def test_step_down_at_bottom_saturates(self) -> None:
        assert ComplexityTier.APPROACHING.stepped_down() is ComplexityTier.APPROACHING


class TestObserver:
    def _profile(self) -> LearnerProfile:
        return LearnerProfile(learner_id="l1", age_bracket=AgeBracket.EARLY_HIGH)

    def test_apply_correct_calibration_updates_modality_outcome(self) -> None:
        profile = self._profile()
        observer = Observer()
        observer.apply(
            profile,
            ObservationEvent(
                kind=EventKind.CALIBRATION_ANSWER,
                domain=Domain.US_HISTORY,
                modality=Modality.TEXT_READING,
                correct=True,
                latency_seconds=8.0,
                concept="concept_a",
            ),
        )
        outcome = profile.outcome_for(Modality.TEXT_READING)
        assert outcome.attempts == 1
        assert outcome.successes == 1
        assert outcome.mean_latency == 8.0

    def test_apply_wrong_answer_accumulates_misconception(self) -> None:
        profile = self._profile()
        observer = Observer()
        wrong = ObservationEvent(
            kind=EventKind.CHECK_FOR_UNDERSTANDING,
            domain=Domain.US_HISTORY,
            modality=Modality.SOCRATIC_DIALOGUE,
            correct=False,
            concept="tricky_concept",
        )
        observer.apply(profile, wrong)
        observer.apply(profile, wrong.model_copy())
        assert profile.misconceptions["tricky_concept"] == 2

    def test_correct_answer_reduces_misconception(self) -> None:
        profile = self._profile()
        observer = Observer()
        concept = "shaky"
        observer.apply(
            profile,
            ObservationEvent(
                kind=EventKind.CHECK_FOR_UNDERSTANDING,
                domain=Domain.US_HISTORY,
                modality=Modality.PRIMARY_SOURCE,
                correct=False,
                concept=concept,
            ),
        )
        observer.apply(
            profile,
            ObservationEvent(
                kind=EventKind.CHECK_FOR_UNDERSTANDING,
                domain=Domain.US_HISTORY,
                modality=Modality.PRIMARY_SOURCE,
                correct=True,
                concept=concept,
            ),
        )
        assert profile.misconceptions[concept] == 0

    def test_voluntary_questions_are_counted(self) -> None:
        profile = self._profile()
        observer = Observer()
        for _ in range(3):
            observer.apply(
                profile,
                ObservationEvent(
                    kind=EventKind.VOLUNTARY_QUESTION,
                    domain=Domain.US_HISTORY,
                ),
            )
        assert profile.voluntary_question_count == 3


class TestExportRoundTrip:
    def test_empty_profile_round_trips(self) -> None:
        profile = LearnerProfile(learner_id="l1", age_bracket=AgeBracket.MIDDLE)
        raw = export_to_json(profile)
        restored = import_from_json(raw)
        assert restored.learner_id == profile.learner_id
        assert restored.age_bracket is profile.age_bracket

    def test_populated_profile_round_trips(self) -> None:
        profile = LearnerProfile(
            learner_id="l2",
            age_bracket=AgeBracket.EARLY_HIGH,
        )
        observer = Observer()
        observer.apply(
            profile,
            ObservationEvent(
                kind=EventKind.CALIBRATION_ANSWER,
                domain=Domain.US_HISTORY,
                modality=Modality.PRIMARY_SOURCE,
                correct=True,
                concept="c1",
                latency_seconds=5.0,
            ),
        )
        raw = export_to_json(profile)
        restored = import_from_json(raw)
        assert restored.modality_outcomes[Modality.PRIMARY_SOURCE].attempts == 1
        assert len(restored.events) == 1

    def test_import_rejects_malformed_json(self) -> None:
        with pytest.raises(ValueError):
            import_from_json("not json at all")

    def test_import_rejects_non_object(self) -> None:
        with pytest.raises(ValueError):
            import_from_json("[1, 2, 3]")
