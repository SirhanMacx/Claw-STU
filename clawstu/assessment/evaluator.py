"""Response evaluation.

Two paths:

- **Objective items** (multiple choice, short answer with canonical
  answer): exact-match comparison, normalized.
- **Constructed-response items** (CRQ, source analysis): rubric-keyword
  scan with a minimum-length threshold.

Both paths return the same `EvaluationResult` so the engagement loop
doesn't need to branch. That matters: a single "did the student get it?"
boolean is what the ZPD calibrator and session adapter consume.

This module is deterministic and does not call an LLM. The LLM-backed
rubric evaluator is a post-MVP replacement that slots in behind the same
interface.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from clawstu.assessment.generator import AssessmentItem, AssessmentType

_CRQ_MIN_CHARS = 40
_CRQ_RUBRIC_PASS_FRACTION = 0.5  # hit at least half the rubric points to pass

_TOKEN_RE = re.compile(r"[a-z0-9']+")


class EvaluationResult(BaseModel):
    """Result of evaluating a student's response to an assessment item."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    correct: bool
    score: float  # 0.0 to 1.0, fractional credit for rubric-scored items
    rubric_hits: tuple[str, ...] = Field(default_factory=tuple)
    notes: str | None = None


class Evaluator:
    """Deterministic formative evaluator.

    The contract: given an item and a student response, produce an
    `EvaluationResult`. Never raise on student input — malformed
    responses are an "incorrect with zero credit" result, not an
    exception. (Malformed *items*, on the other hand, do raise. Those
    are programmer errors.)
    """

    def evaluate(self, item: AssessmentItem, response: str) -> EvaluationResult:
        normalized_response = response.strip()
        if item.type is AssessmentType.MULTIPLE_CHOICE:
            return self._evaluate_exact(item, normalized_response)
        if item.type is AssessmentType.SHORT_ANSWER:
            return self._evaluate_exact(item, normalized_response)
        if item.type in (AssessmentType.CRQ, AssessmentType.SOURCE_ANALYSIS):
            return self._evaluate_rubric(item, normalized_response)
        raise ValueError(f"unknown assessment type: {item.type}")

    @staticmethod
    def _evaluate_exact(item: AssessmentItem, response: str) -> EvaluationResult:
        if item.canonical_answer is None:
            raise ValueError(
                f"item {item.id} has no canonical answer for exact evaluation"
            )
        correct = _normalize(response) == _normalize(item.canonical_answer)
        return EvaluationResult(
            item_id=item.id,
            correct=correct,
            score=1.0 if correct else 0.0,
        )

    @staticmethod
    def _evaluate_rubric(item: AssessmentItem, response: str) -> EvaluationResult:
        rubric = item.rubric or ()
        if not rubric:
            raise ValueError(f"item {item.id} has no rubric for CRQ evaluation")

        if len(response) < _CRQ_MIN_CHARS:
            return EvaluationResult(
                item_id=item.id,
                correct=False,
                score=0.0,
                notes=(
                    f"response under minimum length "
                    f"({len(response)} < {_CRQ_MIN_CHARS} chars)"
                ),
            )

        response_tokens = set(_tokenize(response))
        hits: list[str] = []
        for point in rubric:
            point_tokens = set(_tokenize(point))
            if not point_tokens:
                continue
            overlap = point_tokens & response_tokens
            # A rubric point "hits" when at least one content token from
            # the point appears in the response. This is intentionally
            # generous — the MVP evaluator should not penalize a student
            # for phrasing.
            if overlap:
                hits.append(point)

        score = len(hits) / len(rubric) if rubric else 0.0
        correct = score >= _CRQ_RUBRIC_PASS_FRACTION
        return EvaluationResult(
            item_id=item.id,
            correct=correct,
            score=score,
            rubric_hits=tuple(hits),
        )


# Small token-normalization helpers. Kept free-function so the evaluator
# class stays short and the tokenizer can be unit-tested on its own.


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())
