"""Interaction observer.

The observer is the only component that writes to a `LearnerProfile`. It
takes structured `ObservationEvent`s and updates the profile's aggregate
state (modality outcomes, misconception counters, voluntary question count).

Keeping this logic in one module makes profile mutation auditable — if a
field changes, it's because the observer put it there, and you can trace
*which* event caused the change.
"""

from __future__ import annotations

from src.profile.model import (
    EventKind,
    LearnerProfile,
    ObservationEvent,
)


class Observer:
    """Applies observation events to a learner profile.

    Stateless by design. The profile is the state; the observer is pure
    transformation logic on top of it.
    """

    def apply(self, profile: LearnerProfile, event: ObservationEvent) -> None:
        """Apply a single event. This is the only public entry point."""
        profile.record_event(event)

        if event.kind in (
            EventKind.CALIBRATION_ANSWER,
            EventKind.CHECK_FOR_UNDERSTANDING,
            EventKind.MODALITY_ENGAGEMENT,
        ):
            self._update_modality_outcome(profile, event)
            self._update_misconceptions(profile, event)

        if event.kind is EventKind.VOLUNTARY_QUESTION:
            profile.voluntary_question_count += 1

    def apply_many(
        self,
        profile: LearnerProfile,
        events: list[ObservationEvent],
    ) -> None:
        """Apply a batch of events in order."""
        for event in events:
            self.apply(profile, event)

    @staticmethod
    def _update_modality_outcome(
        profile: LearnerProfile,
        event: ObservationEvent,
    ) -> None:
        if event.modality is None or event.correct is None:
            return
        outcome = profile.outcome_for(event.modality)
        outcome.record(correct=event.correct, latency_seconds=event.latency_seconds)

    @staticmethod
    def _update_misconceptions(
        profile: LearnerProfile,
        event: ObservationEvent,
    ) -> None:
        # A misconception tally only grows when an answer was wrong and the
        # event identified the concept in question. Right answers reduce
        # the counter but never below zero — a previously-wrong concept
        # that's now right is evidence of learning, not a fresh state.
        if event.concept is None or event.correct is None:
            return
        concept = event.concept
        if event.correct:
            if concept in profile.misconceptions:
                profile.misconceptions[concept] = max(
                    0, profile.misconceptions[concept] - 1
                )
            return
        profile.misconceptions[concept] = profile.misconceptions.get(concept, 0) + 1
