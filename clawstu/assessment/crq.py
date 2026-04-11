"""Constructed-response questions.

CRQ format: the student writes a short paragraph in response to a prompt
that requires evidence-based reasoning. The evaluator scores against a
rubric, not against a single canonical string match.

The MVP evaluator is deterministic: it looks for rubric-keyword presence
and a minimum length. That is intentionally dumb — it gets something
working that can be unit-tested today, and it is easy for the post-MVP
LLM-backed evaluator to match-or-beat.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from clawstu.assessment.generator import AssessmentItem, AssessmentType


class ConstructedResponseQuestion(BaseModel):
    """A CRQ wraps an assessment item that happens to be CRQ-typed.

    This class exists to give callers a type-safe handle when they know
    they are specifically working with a CRQ (e.g., for dispatching to
    the CRQ-specific evaluator path).
    """

    model_config = ConfigDict(frozen=True)

    item: AssessmentItem

    def __init__(self, item: AssessmentItem) -> None:
        if item.type is not AssessmentType.CRQ and item.type is not AssessmentType.SOURCE_ANALYSIS:
            raise ValueError(
                f"item {item.id} is type {item.type.value}, not a CRQ/source item"
            )
        super().__init__(item=item)

    @property
    def rubric(self) -> tuple[str, ...]:
        return self.item.rubric or ()


class CRQResponse(BaseModel):
    """A student's response to a CRQ."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    text: str
    latency_seconds: float | None = None
    rubric_hits: tuple[str, ...] = Field(default_factory=tuple)
