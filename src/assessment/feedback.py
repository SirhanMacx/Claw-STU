"""Formative feedback generation.

Feedback in Claw-STU is:

- **Specific.** References exactly what the student said, not a template.
- **Strategy-focused.** Praises effort and approach, not innate ability.
- **Forward-pointing.** Tells the student what to try next, not just
  whether they were right.
- **Non-judgmental.** Mistakes are information, never a moral failing.

The MVP feedback generator is template-driven and deterministic. An
LLM-backed generator plugs in later without breaking this interface.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.assessment.evaluator import EvaluationResult
from src.assessment.generator import AssessmentItem


class Feedback(BaseModel):
    """A formative feedback packet ready to show the student."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    message: str
    advance: bool  # True if Stuart should move forward, False if reteach


class FeedbackGenerator:
    """Produces feedback given an item and its evaluation result.

    The output text is short, concrete, and never uses phrases like
    "I'm proud of you" or "great job!" — see SOUL.md §Voice.
    """

    def generate(
        self,
        item: AssessmentItem,
        result: EvaluationResult,
    ) -> Feedback:
        if result.correct:
            return self._success_feedback(item, result)
        return self._growth_feedback(item, result)

    @staticmethod
    def _success_feedback(
        item: AssessmentItem,
        result: EvaluationResult,
    ) -> Feedback:
        if result.rubric_hits:
            hit_summary = "; ".join(result.rubric_hits[:3])
            message = (
                f"That response lands the following points: {hit_summary}. "
                f"Let's push into something harder on the same concept."
            )
        else:
            message = (
                "That's the right call. Next we'll try a slightly harder "
                "version of the same idea."
            )
        return Feedback(item_id=item.id, message=message, advance=True)

    @staticmethod
    def _growth_feedback(
        item: AssessmentItem,
        result: EvaluationResult,
    ) -> Feedback:
        # Intentionally neutral phrasing. A wrong answer is information,
        # not failure. See SOUL.md §"Behavioral constraints (soft)".
        if result.notes and "minimum length" in result.notes:
            message = (
                "I need a fuller response before I can tell whether you've "
                "got this. Try again with at least a few sentences — you "
                "can think aloud."
            )
        else:
            message = (
                "Not quite. Let's come at this from a different angle and "
                "rebuild from what you already know."
            )
        return Feedback(item_id=item.id, message=message, advance=False)
