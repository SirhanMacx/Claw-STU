"""Tests for engagement signal tracking.

Covers the uncovered lines: mean_latency property (37-39),
record_voluntary_question (55), looks_frustrated (58),
and looks_cruising (61).
"""

from __future__ import annotations

from clawstu.engagement.signals import EngagementSignals


class TestMeanLatency:
    """Cover lines 37-39: mean_latency property."""

    def test_mean_latency_zero_when_no_responses(self) -> None:
        signals = EngagementSignals()
        assert signals.mean_latency == 0.0

    def test_mean_latency_single_response(self) -> None:
        signals = EngagementSignals()
        signals.record_answer(correct=True, latency_seconds=4.0)
        assert signals.mean_latency == 4.0

    def test_mean_latency_multiple_responses(self) -> None:
        signals = EngagementSignals()
        signals.record_answer(correct=True, latency_seconds=2.0)
        signals.record_answer(correct=False, latency_seconds=6.0)
        assert signals.mean_latency == 4.0

    def test_mean_latency_excludes_none_latency(self) -> None:
        """Answers with latency_seconds=None should not affect total."""
        signals = EngagementSignals()
        signals.record_answer(correct=True, latency_seconds=3.0)
        signals.record_answer(correct=True, latency_seconds=None)
        # total_latency_seconds=3.0, response_count=2
        assert signals.mean_latency == 1.5


class TestRecordVoluntaryQuestion:
    """Cover line 55: record_voluntary_question."""

    def test_initial_voluntary_questions_is_zero(self) -> None:
        signals = EngagementSignals()
        assert signals.voluntary_questions == 0

    def test_record_voluntary_question_increments(self) -> None:
        signals = EngagementSignals()
        signals.record_voluntary_question()
        assert signals.voluntary_questions == 1
        signals.record_voluntary_question()
        signals.record_voluntary_question()
        assert signals.voluntary_questions == 3


class TestLooksFrustrated:
    """Cover line 58: looks_frustrated threshold."""

    def test_not_frustrated_initially(self) -> None:
        signals = EngagementSignals()
        assert signals.looks_frustrated() is False

    def test_not_frustrated_after_one_wrong(self) -> None:
        signals = EngagementSignals()
        signals.record_answer(correct=False, latency_seconds=1.0)
        assert signals.consecutive_incorrect == 1
        assert signals.looks_frustrated() is False

    def test_frustrated_after_two_consecutive_wrong(self) -> None:
        signals = EngagementSignals()
        signals.record_answer(correct=False, latency_seconds=1.0)
        signals.record_answer(correct=False, latency_seconds=1.0)
        assert signals.consecutive_incorrect == 2
        assert signals.looks_frustrated() is True

    def test_frustrated_resets_on_correct(self) -> None:
        signals = EngagementSignals()
        signals.record_answer(correct=False, latency_seconds=1.0)
        signals.record_answer(correct=False, latency_seconds=1.0)
        assert signals.looks_frustrated() is True
        signals.record_answer(correct=True, latency_seconds=1.0)
        assert signals.looks_frustrated() is False


class TestLooksCruising:
    """Cover line 61: looks_cruising threshold."""

    def test_not_cruising_initially(self) -> None:
        signals = EngagementSignals()
        assert signals.looks_cruising() is False

    def test_not_cruising_after_two_correct(self) -> None:
        signals = EngagementSignals()
        signals.record_answer(correct=True, latency_seconds=1.0)
        signals.record_answer(correct=True, latency_seconds=1.0)
        assert signals.consecutive_correct == 2
        assert signals.looks_cruising() is False

    def test_cruising_after_three_consecutive_correct(self) -> None:
        signals = EngagementSignals()
        for _ in range(3):
            signals.record_answer(correct=True, latency_seconds=1.0)
        assert signals.consecutive_correct == 3
        assert signals.looks_cruising() is True

    def test_cruising_resets_on_incorrect(self) -> None:
        signals = EngagementSignals()
        for _ in range(3):
            signals.record_answer(correct=True, latency_seconds=1.0)
        assert signals.looks_cruising() is True
        signals.record_answer(correct=False, latency_seconds=1.0)
        assert signals.looks_cruising() is False


class TestRecordAnswerCounters:
    """Additional coverage for record_answer side-effects."""

    def test_total_correct_and_incorrect_accumulate(self) -> None:
        signals = EngagementSignals()
        signals.record_answer(correct=True, latency_seconds=1.0)
        signals.record_answer(correct=True, latency_seconds=1.0)
        signals.record_answer(correct=False, latency_seconds=1.0)
        assert signals.total_correct == 2
        assert signals.total_incorrect == 1
        assert signals.response_count == 3
