"""Zone of Proximal Development calibration.

This is the beating heart of the pedagogical loop. At every decision point,
the ZPD calibrator answers two questions:

1. What complexity tier should Stuart present next, for this domain?
2. Which modality is the student most likely to engage with right now,
   optionally excluding a modality that just failed?

The ZPD is not a global scalar. It is domain-specific and concept-specific.
A student may be at `EXCEEDING` in map interpretation and `APPROACHING` in
constructed-response writing within the same session.

No LLM calls happen here. This is deterministic, testable, local logic.
It takes a `LearnerProfile` and returns decisions.
"""

from __future__ import annotations

from clawstu.profile.model import (
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ObservationEvent,
)

# Tunables. Kept as module-level constants so tests can monkeypatch them
# and so the pedagogical meaning of each number is explicit.
STEP_UP_SUCCESS_RATE = 0.85
STEP_DOWN_SUCCESS_RATE = 0.45
MIN_SAMPLES_FOR_CONFIDENT_STEP = 3
DEFAULT_MODALITY = Modality.SOCRATIC_DIALOGUE
COLD_START_CONFIDENCE = 0.0
MAX_CONFIDENCE = 0.95


class ZPDCalibrator:
    """Decides what complexity and modality Stuart should use next.

    Stateless. Takes a profile, returns decisions. Mutations to the
    profile happen via the Observer, not here.
    """

    def recommend_tier(
        self,
        profile: LearnerProfile,
        domain: Domain,
    ) -> ComplexityTier:
        """Return the tier Stuart should present next for this domain.

        Cold start defaults to MEETING. Once we have evidence, we step up
        if the student is cruising and step down if they're grinding.
        """
        estimate = profile.zpd_for(domain)
        if estimate.samples < MIN_SAMPLES_FOR_CONFIDENT_STEP:
            return estimate.tier

        domain_events = self._domain_events(profile, domain)
        if not domain_events:
            return estimate.tier
        success_rate = self._success_rate(domain_events)
        if success_rate >= STEP_UP_SUCCESS_RATE:
            return estimate.tier.stepped_up()
        if success_rate <= STEP_DOWN_SUCCESS_RATE:
            return estimate.tier.stepped_down()
        return estimate.tier

    def update_estimate(
        self,
        profile: LearnerProfile,
        domain: Domain,
        *,
        correct: bool,
    ) -> None:
        """Record a sample and recompute confidence for a domain.

        Confidence grows slowly and saturates; a single right or wrong
        answer never pushes confidence above `MAX_CONFIDENCE`.
        """
        estimate = profile.zpd_for(domain)
        estimate.samples += 1
        new_conf = estimate.confidence + (0.1 if correct else 0.05)
        estimate.confidence = min(MAX_CONFIDENCE, new_conf)
        estimate.tier = self.recommend_tier(profile, domain)

    def recommend_modality(
        self,
        profile: LearnerProfile,
        *,
        exclude: Modality | None = None,
    ) -> Modality:
        """Recommend the modality most likely to engage the student.

        If `exclude` is given, that modality is never returned — this is
        how re-teach-after-failure works. The first foundational test of
        the whole project depends on this behavior.
        """
        candidates = [m for m in Modality if m is not exclude]
        if not candidates:
            # Degenerate case: only one modality exists and it was excluded.
            # Return the default, which is always guaranteed to be a valid
            # Modality member.
            return DEFAULT_MODALITY

        # Prefer modalities the student has engaged with successfully.
        scored = [
            (self._score_modality(profile, m), m) for m in candidates
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _score_modality(profile: LearnerProfile, modality: Modality) -> float:
        outcome = profile.modality_outcomes.get(modality)
        if outcome is None or outcome.attempts == 0:
            # Untried modalities get a neutral exploration bonus so Stuart
            # doesn't collapse into a single preferred modality before we
            # have data.
            return 0.5
        return outcome.success_rate

    @staticmethod
    def _domain_events(
        profile: LearnerProfile,
        domain: Domain,
    ) -> list[ObservationEvent]:
        relevant = {
            EventKind.CALIBRATION_ANSWER,
            EventKind.CHECK_FOR_UNDERSTANDING,
        }
        return [
            e for e in profile.events
            if e.domain is domain and e.kind in relevant and e.correct is not None
        ]

    @staticmethod
    def _success_rate(events: list[ObservationEvent]) -> float:
        if not events:
            return 0.0
        correct_count = sum(1 for e in events if e.correct)
        return correct_count / len(events)
