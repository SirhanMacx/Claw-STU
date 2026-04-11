"""End-to-end session flow tests."""

from __future__ import annotations

import pytest

from clawstu.assessment.evaluator import EvaluationResult
from clawstu.engagement.session import (
    LiveContentUnavailableError,
    Session,
    SessionPhase,
    SessionRunner,
)
from clawstu.orchestrator.live_content import LiveContentGenerator
from clawstu.profile.model import Domain, LearnerProfile
from tests.conftest import async_router_for_testing


def test_full_happy_path_session() -> None:
    """A fully correct run through onboard → calibrate → teach → check
    → close. No re-teaches."""
    runner = SessionRunner()

    profile, session = runner.onboard(
        learner_id="happy",
        age=15,
        domain=Domain.US_HISTORY,
    )
    assert session.phase is SessionPhase.CALIBRATING

    for item in runner.calibration_items(session):
        # For CRQ items the learner-writes-something path isn't exercised
        # here; we fabricate a correct evaluation directly. The assessment
        # layer is unit-tested separately.
        result = EvaluationResult(item_id=item.id, correct=True, score=1.0)
        runner.record_calibration_answer(profile, session, item, result)

    runner.finish_calibration(profile, session)
    assert session.phase is SessionPhase.TEACHING
    assert session.current_modality is not None

    directive = runner.next_directive(profile, session)
    assert directive.block is not None
    check = runner.select_check(session)
    good_result = EvaluationResult(item_id=check.id, correct=True, score=1.0)
    outcome = runner.record_check(profile, session, check, good_result)
    assert outcome.reteach is False

    summary = runner.close(profile, session)
    assert session.phase is SessionPhase.CLOSED
    assert "Session" in summary


def test_session_records_reteach_counter_on_failure() -> None:
    runner = SessionRunner()
    profile, session = runner.onboard(
        learner_id="sad",
        age=15,
        domain=Domain.US_HISTORY,
    )
    runner.finish_calibration(profile, session)

    directive = runner.next_directive(profile, session)
    assert directive.block is not None
    check = runner.select_check(session)
    fail = EvaluationResult(item_id=check.id, correct=False, score=0.0)
    runner.record_check(profile, session, check, fail)
    assert session.reteach_count == 1


def test_close_writes_session_close_event() -> None:
    runner = SessionRunner()
    profile, session = runner.onboard(
        learner_id="l",
        age=15,
        domain=Domain.US_HISTORY,
    )
    runner.close(profile, session)
    from clawstu.profile.model import EventKind

    kinds = {e.kind for e in profile.events}
    assert EventKind.SESSION_CLOSE in kinds
    assert session.phase is SessionPhase.CLOSED


# --------------------------------------------------------------------------- #
# Phase 5: live-content topic path + CRISIS_PAUSE phase
# --------------------------------------------------------------------------- #


class TestLiveTopicPath:
    """`onboard_with_topic` + primed block/check flow.

    These tests drive the full onboard → teach → check → close cycle
    via `LiveContentGenerator(router=async_router_for_testing())`,
    which hits the offline EchoProvider stub so no network is touched.
    The live path skips the seed-library calibration phase (post-MVP
    will add LLM-backed calibration for arbitrary topics).
    """

    async def _drive_full_cycle(
        self, topic: str, domain: Domain
    ) -> tuple[LearnerProfile, Session]:
        live = LiveContentGenerator(router=async_router_for_testing())
        runner = SessionRunner(live_content=live)
        profile, session = await runner.onboard_with_topic(
            learner_id="test-learner",
            age=15,
            domain=domain,
            topic=topic,
        )
        # The live path skips calibration and lands directly in TEACHING.
        assert session.phase is SessionPhase.TEACHING
        assert session.pathway is not None
        assert len(session.pathway.concepts) > 0
        assert session.topic == topic
        assert session.primed_block is not None
        assert session.primed_check is not None

        directive = runner.next_directive(profile, session)
        assert directive.block is not None
        assert directive.block.concept == session.pathway.concepts[0]

        check = runner.select_check(session)
        good = EvaluationResult(item_id=check.id, correct=True, score=1.0)
        outcome = runner.record_check(profile, session, check, good)
        assert outcome.reteach is False
        assert outcome.evaluation.correct is True

        runner.close(profile, session)
        assert session.phase is SessionPhase.CLOSED
        return profile, session

    async def test_haitian_revolution_topic_onboards_and_teaches(self) -> None:
        _, session = await self._drive_full_cycle(
            "The Haitian Revolution", Domain.GLOBAL_HISTORY
        )
        assert session.topic == "The Haitian Revolution"
        assert session.domain is Domain.GLOBAL_HISTORY

    async def test_water_cycle_topic_onboards_and_teaches(self) -> None:
        _, session = await self._drive_full_cycle(
            "The water cycle", Domain.SCIENCE
        )
        assert session.topic == "The water cycle"
        assert session.domain is Domain.SCIENCE

    async def test_mitosis_topic_onboards_and_teaches(self) -> None:
        _, session = await self._drive_full_cycle("Mitosis", Domain.SCIENCE)
        assert session.topic == "Mitosis"
        assert session.blocks_presented == 1

    async def test_missing_live_content_raises(self) -> None:
        """Calling `onboard_with_topic` on a runner with no live content
        raises `LiveContentUnavailableError` — it does NOT silently fall
        back to the seed library."""
        runner = SessionRunner()  # no live_content=...
        with pytest.raises(LiveContentUnavailableError):
            await runner.onboard_with_topic(
                learner_id="lt",
                age=15,
                domain=Domain.GLOBAL_HISTORY,
                topic="The Haitian Revolution",
            )


class TestCrisisPausePhase:
    def test_crisis_paused_session_refuses_next_directive(self) -> None:
        """A session in `CRISIS_PAUSE` returns a safety-halt directive
        from `next_directive` regardless of pathway position. The branch
        runs BEFORE any other phase dispatch so the halt cannot be
        accidentally bypassed."""
        runner = SessionRunner()
        profile, session = runner.onboard(
            learner_id="paused",
            age=15,
            domain=Domain.US_HISTORY,
        )
        # Manually flip the session into CRISIS_PAUSE (the API wiring
        # that actually causes this flip lands in commit 3).
        session.phase = SessionPhase.CRISIS_PAUSE

        directive = runner.next_directive(profile, session)
        assert directive.phase is SessionPhase.CRISIS_PAUSE
        assert directive.block is None
        assert directive.check_item is None
        assert directive.message is not None
        assert "Session paused for safety" in directive.message
        assert "trusted adult" in directive.message
