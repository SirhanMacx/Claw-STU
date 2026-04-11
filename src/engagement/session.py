"""Session lifecycle and the MVP teach-assess-adapt loop.

This is the module the Handoff calls out explicitly:

> The first test that should pass: Given a student who answers a
> calibration question incorrectly, the agent re-teaches via a
> different modality than the one that failed.

The session runner is deterministic and LLM-free. Every decision here
is auditable from a learner profile and an event stream.

Session lifecycle
-----------------

1. **onboard()** — create a profile, record the age bracket and the
   chosen domain.
2. **calibrate(answer_stream)** — present a small calibration set and
   record results. Produces an initial ZPD estimate.
3. **next_directive()** — returns a `SessionDirective` describing what
   Stuart should do next: teach a block, run a check, adapt, or close.
4. **record_check(result)** — apply the outcome of a check for
   understanding and update signals, profile, and pathway position.
5. **close()** — produce a session summary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.assessment.evaluator import EvaluationResult
from src.assessment.generator import AssessmentItem, QuestionGenerator
from src.curriculum.content import ContentSelector, LearningBlock
from src.curriculum.pathway import Pathway, PathwayPlanner
from src.engagement.modality import ModalityRotator
from src.engagement.signals import EngagementSignals
from src.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ObservationEvent,
)
from src.profile.observer import Observer
from src.profile.zpd import ZPDCalibrator


class SessionPhase(str, Enum):
    ONBOARDING = "onboarding"
    CALIBRATING = "calibrating"
    TEACHING = "teaching"
    CHECKING = "checking"
    CLOSING = "closing"
    CLOSED = "closed"


class SessionDirective(BaseModel):
    """What the session runner wants Stuart to do next."""

    model_config = ConfigDict(frozen=True)

    phase: SessionPhase
    block: LearningBlock | None = None
    check_item: AssessmentItem | None = None
    message: str | None = None


class TeachBlockResult(BaseModel):
    """Outcome of a single teach → check iteration."""

    model_config = ConfigDict(frozen=True)

    block: LearningBlock
    check: AssessmentItem
    evaluation: EvaluationResult
    reteach: bool


class Session(BaseModel):
    """Session state. Small and serializable so we can checkpoint it
    cheaply during long sessions."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    learner_id: str
    domain: Domain
    phase: SessionPhase = SessionPhase.ONBOARDING
    signals: EngagementSignals = Field(default_factory=EngagementSignals)
    pathway: Pathway | None = None
    current_tier: ComplexityTier = ComplexityTier.MEETING
    current_modality: Modality | None = None
    last_block_id: str | None = None
    last_check_item: AssessmentItem | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    blocks_presented: int = 0
    reteach_count: int = 0


class SessionRunner:
    """Deterministic session orchestrator.

    The runner composes a calibrator, observer, modality rotator,
    content selector, question generator, and pathway planner, and
    exposes a small number of methods to drive the teach-assess-adapt
    loop. This class must not import from `orchestrator` or `api` —
    those live higher in the dependency graph.
    """

    def __init__(
        self,
        *,
        observer: Observer | None = None,
        calibrator: ZPDCalibrator | None = None,
        rotator: ModalityRotator | None = None,
        content: ContentSelector | None = None,
        questions: QuestionGenerator | None = None,
        planner: PathwayPlanner | None = None,
    ) -> None:
        self._observer = observer or Observer()
        self._calibrator = calibrator or ZPDCalibrator()
        self._rotator = rotator or ModalityRotator(self._calibrator)
        self._content = content or ContentSelector()
        self._questions = questions or QuestionGenerator()
        self._planner = planner or PathwayPlanner()

    # -- lifecycle --------------------------------------------------------

    def onboard(
        self,
        *,
        learner_id: str,
        age: int,
        domain: Domain,
    ) -> tuple[LearnerProfile, Session]:
        """Create a fresh profile and session for a first-time learner."""
        profile = LearnerProfile(
            learner_id=learner_id,
            age_bracket=AgeBracket.from_age(age),
        )
        session = Session(learner_id=learner_id, domain=domain)
        session.pathway = self._planner.plan(domain, profile)
        self._observer.apply(
            profile,
            ObservationEvent(kind=EventKind.SESSION_START, domain=domain),
        )
        session.phase = SessionPhase.CALIBRATING
        return profile, session

    def calibration_items(self, session: Session, size: int = 3) -> tuple[AssessmentItem, ...]:
        """Return the calibration set for this session."""
        return self._questions.calibration_set(session.domain, size=size)

    def record_calibration_answer(
        self,
        profile: LearnerProfile,
        session: Session,
        item: AssessmentItem,
        result: EvaluationResult,
        *,
        latency_seconds: float | None = None,
    ) -> None:
        """Record one calibration answer. Updates profile, signals, ZPD."""
        event = ObservationEvent(
            kind=EventKind.CALIBRATION_ANSWER,
            domain=session.domain,
            modality=item.modality,
            tier=item.tier,
            correct=result.correct,
            latency_seconds=latency_seconds,
            concept=item.concept,
        )
        self._observer.apply(profile, event)
        session.signals.record_answer(
            correct=result.correct,
            latency_seconds=latency_seconds,
        )
        self._calibrator.update_estimate(profile, session.domain, correct=result.correct)
        session.current_tier = profile.zpd_for(session.domain).tier

    def finish_calibration(self, profile: LearnerProfile, session: Session) -> None:
        """Transition from CALIBRATING to TEACHING."""
        session.current_modality = self._rotator.initial(profile)
        session.phase = SessionPhase.TEACHING

    # -- teach / check / adapt -------------------------------------------

    def next_directive(
        self,
        profile: LearnerProfile,
        session: Session,
    ) -> SessionDirective:
        """Return the next thing Stuart should present."""
        if session.phase is SessionPhase.CLOSED:
            return SessionDirective(phase=SessionPhase.CLOSED)

        if session.phase in (SessionPhase.ONBOARDING, SessionPhase.CALIBRATING):
            return SessionDirective(phase=session.phase)

        if session.phase is SessionPhase.CLOSING:
            return SessionDirective(
                phase=SessionPhase.CLOSING,
                message="Wrapping up — here's what we covered.",
            )

        return self._next_teach_or_check(profile, session)

    def _next_teach_or_check(
        self,
        profile: LearnerProfile,
        session: Session,
    ) -> SessionDirective:
        if session.pathway is None:
            raise RuntimeError("session has no pathway; was onboard() called?")
        concept = session.pathway.current()
        if concept is None:
            session.phase = SessionPhase.CLOSING
            return SessionDirective(
                phase=SessionPhase.CLOSING,
                message="All planned concepts covered.",
            )
        if session.current_modality is None:
            session.current_modality = self._rotator.initial(profile)

        block = self._content.select(
            domain=session.domain,
            modality=session.current_modality,
            tier=session.current_tier,
            concept=concept,
        )
        if block is None:
            raise RuntimeError(
                f"no content available for domain={session.domain}, "
                f"modality={session.current_modality}, tier={session.current_tier}, "
                f"concept={concept}"
            )
        session.last_block_id = block.id
        session.blocks_presented += 1
        session.phase = SessionPhase.CHECKING
        return SessionDirective(phase=SessionPhase.TEACHING, block=block)

    def select_check(
        self,
        session: Session,
    ) -> AssessmentItem:
        """Pick a check-for-understanding item for the current block."""
        if session.pathway is None:
            raise RuntimeError("session has no pathway")
        concept = session.pathway.current()
        if concept is None:
            raise RuntimeError("no current concept to check")
        library = self._questions.seed_library(session.domain)
        candidates = [i for i in library if i.concept == concept]
        if not candidates:
            raise RuntimeError(f"no check items for concept: {concept}")
        # Prefer an item at the session's current tier, falling back to
        # whatever is available for that concept.
        tier_matches = [i for i in candidates if i.tier is session.current_tier]
        chosen = tier_matches[0] if tier_matches else candidates[0]
        session.last_check_item = chosen
        return chosen

    def record_check(
        self,
        profile: LearnerProfile,
        session: Session,
        item: AssessmentItem,
        result: EvaluationResult,
        *,
        latency_seconds: float | None = None,
    ) -> TeachBlockResult:
        """Apply the result of a check-for-understanding.

        This is where the foundational rule is enforced: on a failed
        check, the next modality MUST differ from the one that failed.
        """
        event = ObservationEvent(
            kind=EventKind.CHECK_FOR_UNDERSTANDING,
            domain=session.domain,
            modality=item.modality,
            tier=item.tier,
            correct=result.correct,
            latency_seconds=latency_seconds,
            concept=item.concept,
        )
        self._observer.apply(profile, event)
        session.signals.record_answer(
            correct=result.correct,
            latency_seconds=latency_seconds,
        )
        self._calibrator.update_estimate(
            profile, session.domain, correct=result.correct
        )

        block = self._require_last_block(session)
        reteach = not result.correct
        if reteach:
            session.reteach_count += 1
            session.current_modality = self._rotator.rotate_after_failure(
                profile, item.modality
            )
            # Back off on complexity too, but never below APPROACHING.
            session.current_tier = session.current_tier.stepped_down()
        else:
            session.pathway = session.pathway.advanced() if session.pathway else None
            session.current_tier = self._calibrator.recommend_tier(profile, session.domain)
            session.current_modality = self._rotator.next_of_same_kind(profile)
        session.phase = SessionPhase.TEACHING
        return TeachBlockResult(
            block=block,
            check=item,
            evaluation=result,
            reteach=reteach,
        )

    def close(
        self,
        profile: LearnerProfile,
        session: Session,
    ) -> str:
        """Close the session and return a short summary string."""
        self._observer.apply(
            profile,
            ObservationEvent(kind=EventKind.SESSION_CLOSE, domain=session.domain),
        )
        session.phase = SessionPhase.CLOSED
        accuracy = (
            session.signals.total_correct
            / max(1, session.signals.total_correct + session.signals.total_incorrect)
        )
        return (
            f"Session {session.id[:8]} complete. "
            f"Blocks presented: {session.blocks_presented}. "
            f"Re-teaches: {session.reteach_count}. "
            f"Overall accuracy: {accuracy:.0%}."
        )

    # -- helpers ----------------------------------------------------------

    def _require_last_block(self, session: Session) -> LearningBlock:
        if session.last_block_id is None:
            raise RuntimeError("no block has been presented yet")
        for block in self._content.blocks:
            if block.id == session.last_block_id:
                return block
        raise RuntimeError(f"unknown block id on session: {session.last_block_id}")
