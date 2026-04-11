"""End-to-end session flow tests."""

from __future__ import annotations

from clawstu.assessment.evaluator import EvaluationResult
from clawstu.engagement.session import SessionPhase, SessionRunner
from clawstu.profile.model import Domain


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
