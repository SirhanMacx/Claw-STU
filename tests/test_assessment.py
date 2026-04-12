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

    def test_calibration_set_size_one_returns_approaching(self) -> None:
        """size=1 hits early return at line 176-177 on the first tier.

        The tier loop picks APPROACHING first; once len(picked)==1 >= size==1
        the method returns immediately without visiting MEETING or EXCEEDING.
        """
        generator = QuestionGenerator()
        items = generator.calibration_set(Domain.US_HISTORY, size=1)
        assert len(items) == 1
        assert items[0].tier == ComplexityTier.APPROACHING

    def test_calibration_set_size_two_returns_approaching_and_meeting(self) -> None:
        """size=2 hits early return at line 176-177 after the MEETING tier.

        Covers the path where the tier loop terminates after two tiers
        because size is reached before EXCEEDING.
        """
        generator = QuestionGenerator()
        items = generator.calibration_set(Domain.US_HISTORY, size=2)
        assert len(items) == 2
        assert items[0].tier == ComplexityTier.APPROACHING
        assert items[1].tier == ComplexityTier.MEETING

    def test_calibration_set_larger_than_library_uses_fill_loop(self) -> None:
        """size > library size exercises lines 179-184 (fill leftover loop).

        The US History seed library has 3 items. Requesting size=5 means
        the tier loop picks 3 items, then the fill loop looks for extras
        but finds none (all items already picked), so the result is
        capped at the library size.
        """
        generator = QuestionGenerator()
        items = generator.calibration_set(Domain.US_HISTORY, size=5)
        # Library only has 3 items, so max we can get is 3.
        assert len(items) == 3
        tiers = [i.tier for i in items]
        assert ComplexityTier.APPROACHING in tiers
        assert ComplexityTier.MEETING in tiers
        assert ComplexityTier.EXCEEDING in tiers

    def test_calibration_set_fill_loop_picks_unpicked_items(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cover lines 181-183: the fill loop picks items not selected by tier.

        The seed library is patched to contain 4 items but only 2 tiers,
        so the tier loop picks 2 items (APPROACHING + MEETING). With
        size=4, the fill loop must pick 2 more unpicked items from the
        library, exercising the append + break paths.
        """
        from clawstu.assessment import generator as gen_mod

        extra_approaching = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.APPROACHING,
            modality=Modality.TEXT_READING,
            type=AssessmentType.MULTIPLE_CHOICE,
            prompt="Extra approaching question?",
            choices=("a", "b"),
            canonical_answer="a",
            concept="extra_approaching",
        )
        extra_meeting = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.MEETING,
            modality=Modality.TEXT_READING,
            type=AssessmentType.SHORT_ANSWER,
            prompt="Extra meeting question?",
            canonical_answer="answer",
            concept="extra_meeting",
        )
        first_approaching = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.APPROACHING,
            modality=Modality.TEXT_READING,
            type=AssessmentType.MULTIPLE_CHOICE,
            prompt="First approaching?",
            choices=("x", "y"),
            canonical_answer="x",
            concept="first_approaching",
        )
        first_meeting = AssessmentItem(
            domain=Domain.US_HISTORY,
            tier=ComplexityTier.MEETING,
            modality=Modality.PRIMARY_SOURCE,
            type=AssessmentType.SOURCE_ANALYSIS,
            prompt="First meeting?",
            rubric=("r1",),
            concept="first_meeting",
        )
        patched_library = (
            first_approaching,
            extra_approaching,
            first_meeting,
            extra_meeting,
        )
        monkeypatch.setattr(
            gen_mod,
            "_SEED_LIBRARIES",
            {Domain.US_HISTORY: patched_library},
        )
        generator = QuestionGenerator()
        items = generator.calibration_set(Domain.US_HISTORY, size=4)
        assert len(items) == 4
        # Tier loop picks first_approaching and first_meeting.
        # Fill loop picks extra_approaching and extra_meeting.
        concepts = [i.concept for i in items]
        assert "first_approaching" in concepts
        assert "first_meeting" in concepts
        assert "extra_approaching" in concepts
        assert "extra_meeting" in concepts

    def test_seed_library_returns_empty_for_unknown_domain(self) -> None:
        generator = QuestionGenerator()
        assert generator.seed_library(Domain.MATH) == ()


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
