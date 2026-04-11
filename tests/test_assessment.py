"""Unit tests for the assessment engine."""

from __future__ import annotations

import pytest

from clawstu.assessment.crq import ConstructedResponseQuestion
from clawstu.assessment.evaluator import Evaluator
from clawstu.assessment.feedback import FeedbackGenerator
from clawstu.assessment.generator import (
    AssessmentItem,
    AssessmentType,
    QuestionGenerator,
)
from clawstu.profile.model import ComplexityTier, Domain, Modality


class TestQuestionGenerator:
    def test_calibration_set_spans_tiers(self) -> None:
        generator = QuestionGenerator()
        items = generator.calibration_set(Domain.US_HISTORY, size=3)
        tiers = {i.tier for i in items}
        assert ComplexityTier.APPROACHING in tiers
        assert ComplexityTier.MEETING in tiers

    def test_calibration_set_unknown_domain_raises(self) -> None:
        generator = QuestionGenerator()
        with pytest.raises(ValueError):
            generator.calibration_set(Domain.MATH)

    def test_calibration_set_invalid_size_raises(self) -> None:
        generator = QuestionGenerator()
        with pytest.raises(ValueError):
            generator.calibration_set(Domain.US_HISTORY, size=0)


class TestEvaluator:
    def test_multiple_choice_exact_match(self) -> None:
        item = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.APPROACHING,
            modality=Modality.TEXT_READING,
            type=AssessmentType.MULTIPLE_CHOICE,
            prompt="q?",
            choices=("a", "b", "c"),
            canonical_answer="b",
            concept="c",
        )
        evaluator = Evaluator()
        assert evaluator.evaluate(item, "b").correct is True
        assert evaluator.evaluate(item, " B ").correct is True
        assert evaluator.evaluate(item, "a").correct is False

    def test_crq_rubric_scoring(self) -> None:
        item = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.MEETING,
            modality=Modality.SOCRATIC_DIALOGUE,
            type=AssessmentType.CRQ,
            prompt="explain why the Declaration was controversial",
            rubric=(
                "mentions slavery or enslaved people",
                "identifies audience of colonists or king",
                "addresses tension between ideals and reality",
            ),
            concept="c",
        )
        evaluator = Evaluator()
        strong = (
            "The Declaration claimed all men are equal while slavery was "
            "legal in every colony. The audience was both the king of "
            "Britain and the colonists themselves, creating a tension "
            "between stated ideals and the reality of enslaved people."
        )
        result = evaluator.evaluate(item, strong)
        assert result.correct is True
        assert result.score >= 0.5
        assert len(result.rubric_hits) >= 2

    def test_crq_too_short_is_not_correct(self) -> None:
        item = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.MEETING,
            modality=Modality.SOCRATIC_DIALOGUE,
            type=AssessmentType.CRQ,
            prompt="explain",
            rubric=("point one", "point two"),
            concept="c",
        )
        evaluator = Evaluator()
        result = evaluator.evaluate(item, "idk")
        assert result.correct is False
        assert result.score == 0.0
        assert result.notes is not None and "minimum length" in result.notes


class TestCRQWrapper:
    def test_rejects_non_crq_item(self) -> None:
        item = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.APPROACHING,
            modality=Modality.TEXT_READING,
            type=AssessmentType.MULTIPLE_CHOICE,
            prompt="q?",
            choices=("a",),
            canonical_answer="a",
            concept="c",
        )
        with pytest.raises(ValueError):
            ConstructedResponseQuestion(item)


class TestFeedbackGenerator:
    def test_success_feedback_advances(self) -> None:
        from clawstu.assessment.evaluator import EvaluationResult

        item = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.MEETING,
            modality=Modality.PRIMARY_SOURCE,
            type=AssessmentType.SOURCE_ANALYSIS,
            prompt="p",
            rubric=("one", "two"),
            concept="c",
        )
        result = EvaluationResult(
            item_id=item.id,
            correct=True,
            score=1.0,
            rubric_hits=("one", "two"),
        )
        feedback = FeedbackGenerator().generate(item, result)
        assert feedback.advance is True
        assert "proud" not in feedback.message.lower()  # SOUL.md §Voice

    def test_growth_feedback_does_not_advance(self) -> None:
        from clawstu.assessment.evaluator import EvaluationResult

        item = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.MEETING,
            modality=Modality.TEXT_READING,
            type=AssessmentType.MULTIPLE_CHOICE,
            prompt="q",
            choices=("a",),
            canonical_answer="a",
            concept="c",
        )
        result = EvaluationResult(item_id=item.id, correct=False, score=0.0)
        feedback = FeedbackGenerator().generate(item, result)
        assert feedback.advance is False
        assert "not quite" in feedback.message.lower()
