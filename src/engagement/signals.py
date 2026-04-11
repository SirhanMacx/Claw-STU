"""Engagement signal tracking.

Engagement signals are the "temperature check" for a session. They tell
Stuart, without asking the student directly, whether the student is:

- Cruising (too easy — consider escalating)
- Grinding productively (right in the ZPD — stay)
- Frustrated / shutting down (too hard — back off and switch modality)
- Disengaged / distracted (wrong modality or wrong time)

The MVP tracks four scalars: consecutive correct, consecutive incorrect,
mean response latency, and voluntary-question count. That's enough to
drive the session loop's decisions without pretending we can read
affect through a screen.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EngagementSignals(BaseModel):
    """Rolling engagement state for a single session."""

    model_config = ConfigDict(validate_assignment=True)

    consecutive_correct: int = 0
    consecutive_incorrect: int = 0
    total_correct: int = 0
    total_incorrect: int = 0
    total_latency_seconds: float = 0.0
    response_count: int = 0
    voluntary_questions: int = 0

    @property
    def mean_latency(self) -> float:
        if self.response_count == 0:
            return 0.0
        return self.total_latency_seconds / self.response_count

    def record_answer(self, *, correct: bool, latency_seconds: float | None) -> None:
        self.response_count += 1
        if latency_seconds is not None:
            self.total_latency_seconds += latency_seconds
        if correct:
            self.total_correct += 1
            self.consecutive_correct += 1
            self.consecutive_incorrect = 0
        else:
            self.total_incorrect += 1
            self.consecutive_incorrect += 1
            self.consecutive_correct = 0

    def record_voluntary_question(self) -> None:
        self.voluntary_questions += 1

    def looks_frustrated(self) -> bool:
        return self.consecutive_incorrect >= 2

    def looks_cruising(self) -> bool:
        return self.consecutive_correct >= 3
