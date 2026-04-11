"""Unit tests for the ZPD calibrator."""

from __future__ import annotations

from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ObservationEvent,
)
from clawstu.profile.zpd import ZPDCalibrator


def _profile() -> LearnerProfile:
    return LearnerProfile(learner_id="l", age_bracket=AgeBracket.EARLY_HIGH)


class TestRecommendTier:
    def test_cold_start_defaults_to_meeting(self) -> None:
        calibrator = ZPDCalibrator()
        assert (
            calibrator.recommend_tier(_profile(), Domain.US_HISTORY)
            is ComplexityTier.MEETING
        )

    def test_many_correct_answers_step_up(self) -> None:
        profile = _profile()
        calibrator = ZPDCalibrator()
        for _ in range(5):
            profile.record_event(
                ObservationEvent(
                    kind=EventKind.CALIBRATION_ANSWER,
                    domain=Domain.US_HISTORY,
                    correct=True,
                )
            )
            calibrator.update_estimate(profile, Domain.US_HISTORY, correct=True)
        assert (
            calibrator.recommend_tier(profile, Domain.US_HISTORY)
            is ComplexityTier.EXCEEDING
        )

    def test_many_wrong_answers_step_down(self) -> None:
        profile = _profile()
        calibrator = ZPDCalibrator()
        for _ in range(5):
            profile.record_event(
                ObservationEvent(
                    kind=EventKind.CALIBRATION_ANSWER,
                    domain=Domain.US_HISTORY,
                    correct=False,
                )
            )
            calibrator.update_estimate(profile, Domain.US_HISTORY, correct=False)
        assert (
            calibrator.recommend_tier(profile, Domain.US_HISTORY)
            is ComplexityTier.APPROACHING
        )


class TestRecommendModality:
    def test_excluded_modality_is_never_returned(self) -> None:
        calibrator = ZPDCalibrator()
        profile = _profile()
        for modality in Modality:
            chosen = calibrator.recommend_modality(profile, exclude=modality)
            assert chosen is not modality

    def test_successful_modality_is_preferred(self) -> None:
        profile = _profile()
        calibrator = ZPDCalibrator()
        # Build a strong success record for SOCRATIC_DIALOGUE
        for _ in range(5):
            profile.outcome_for(Modality.SOCRATIC_DIALOGUE).record(
                correct=True, latency_seconds=5.0
            )
        chosen = calibrator.recommend_modality(profile)
        assert chosen is Modality.SOCRATIC_DIALOGUE

    def test_exploration_bonus_for_untried_modalities(self) -> None:
        """Untried modalities should be viable picks on cold start so we
        don't collapse into a single modality too early."""
        profile = _profile()
        calibrator = ZPDCalibrator()
        # Nothing recorded. The calibrator should still pick *some*
        # modality without crashing.
        chosen = calibrator.recommend_modality(profile)
        assert chosen in set(Modality)
