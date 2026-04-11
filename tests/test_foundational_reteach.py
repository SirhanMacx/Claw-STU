"""The foundational test.

From Handoff.md:

    The first test that should pass: Given a student who answers a
    calibration question incorrectly, the agent re-teaches via a
    different modality than the one that failed.

Everything else flows from this. If this test ever regresses, the
project is broken in its stated core purpose.
"""

from __future__ import annotations

from src.assessment.evaluator import EvaluationResult, Evaluator
from src.assessment.generator import QuestionGenerator
from src.engagement.session import SessionRunner
from src.profile.model import Domain, Modality


def test_reteach_uses_different_modality_than_failed_one() -> None:
    runner = SessionRunner()
    generator = QuestionGenerator()
    evaluator = Evaluator()

    profile, session = runner.onboard(
        learner_id="learner-reteach-test",
        age=15,
        domain=Domain.US_HISTORY,
    )

    # Seed the profile with a calibration attempt so the session has some
    # prior context, and finish calibration so we can enter TEACHING.
    calibration = generator.calibration_set(Domain.US_HISTORY, size=1)
    first_item = calibration[0]
    # Deliberately submit a wrong response.
    wrong = evaluator.evaluate(first_item, "wrong on purpose")
    assert wrong.correct is False
    runner.record_calibration_answer(
        profile, session, first_item, wrong, latency_seconds=12.0
    )
    runner.finish_calibration(profile, session)

    # Ask for a learning block — the session picks a modality and block.
    directive = runner.next_directive(profile, session)
    assert directive.block is not None
    presented_modality = directive.block.modality

    # Now build a failing check for that exact modality. We do this by
    # picking any assessment item in the library that matches the
    # presented modality — and if none exists, force the match by using
    # `select_check` (which returns whatever the concept library has).
    check_item = runner.select_check(session)
    # Force the failing modality to match what we just presented.
    # `record_check` inspects the item's modality when rotating.
    forced_item = check_item.model_copy(update={"modality": presented_modality})

    failing_result = EvaluationResult(
        item_id=forced_item.id,
        correct=False,
        score=0.0,
    )
    outcome = runner.record_check(
        profile, session, forced_item, failing_result, latency_seconds=20.0
    )

    # The foundational invariant:
    assert outcome.reteach is True, "a failed check must produce a reteach"
    new_modality = session.current_modality
    assert new_modality is not None
    assert new_modality is not presented_modality, (
        f"re-teach must use a different modality; "
        f"failed={presented_modality}, new={new_modality}"
    )


def test_reteach_invariant_holds_across_every_modality() -> None:
    """Rotation must avoid the failed modality regardless of which one
    just failed. We exercise every Modality value to make sure the
    invariant is unconditional."""
    runner = SessionRunner()
    for failed in Modality:
        profile, session = runner.onboard(
            learner_id=f"learner-{failed.value}",
            age=15,
            domain=Domain.US_HISTORY,
        )
        runner.finish_calibration(profile, session)

        directive = runner.next_directive(profile, session)
        assert directive.block is not None

        check_item = runner.select_check(session)
        forced_item = check_item.model_copy(update={"modality": failed})

        failing_result = EvaluationResult(
            item_id=forced_item.id,
            correct=False,
            score=0.0,
        )
        runner.record_check(profile, session, forced_item, failing_result)

        assert session.current_modality is not failed, (
            f"reteach invariant violated when failed modality was {failed}"
        )
