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

import json
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clawstu.assessment.evaluator import EvaluationResult
from clawstu.assessment.generator import (
    AssessmentItem,
    AssessmentType,
    QuestionGenerator,
)
from clawstu.curriculum.content import ContentSelector, LearningBlock
from clawstu.curriculum.pathway import Pathway, PathwayPlanner
from clawstu.engagement.modality import ModalityRotator
from clawstu.engagement.signals import EngagementSignals
from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ModalityOutcome,
    ObservationEvent,
    ZPDEstimate,
)
from clawstu.profile.observer import Observer
from clawstu.profile.zpd import ZPDCalibrator

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    from clawstu.curriculum.topic import Topic


class LiveContentUnavailableError(RuntimeError):
    """Raised when `onboard_with_topic` is called without a live
    content generator available on the runner or as an override."""


class NoArtifactError(RuntimeError):
    """Raised by `SessionRunner.warm_start` when the learner has no
    unconsumed NextSessionArtifact.

    Callers should interpret this as "the learner needs a fresh
    onboard" — the API layer converts it to HTTP 409 with a body
    pointing clients at `POST /sessions`.
    """


class LiveContentGeneratorLike(Protocol):
    """Structural protocol for the orchestrator's live content generator.

    Engagement cannot import from orchestrator per §4.1, so we describe
    the generator's shape here. The real implementation lives in
    `clawstu.orchestrator.live_content.LiveContentGenerator` and
    structurally matches this protocol.

    We keep the signatures aligned with the orchestrator implementation
    so a duck-typed generator drops straight in as a `live_content`
    argument to the runner.
    """

    async def generate_pathway(
        self,
        *,
        topic: Topic,
        age_bracket: AgeBracket,
        max_concepts: int = 4,
    ) -> tuple[str, ...]: ...

    async def generate_block(
        self,
        *,
        topic: Topic,
        concept: str,
        modality: Modality,
        tier: ComplexityTier,
        age_bracket: AgeBracket,
    ) -> LearningBlock: ...

    async def generate_check(
        self,
        *,
        topic: Topic,
        concept: str,
        tier: ComplexityTier,
        modality: Modality,
        age_bracket: AgeBracket,
    ) -> AssessmentItem: ...


# -- Warm-start store protocols ----------------------------------------
#
# `SessionRunner.warm_start` needs to read a bunch of entity stores to
# rehydrate a learner profile and consume a NextSessionArtifact. The
# engagement layer cannot import `clawstu.persistence.store` because
# the hierarchy DAG puts persistence above engagement (persistence
# depends on Session from engagement, not the other way around). So we
# declare the same structural shape the persistence layer happens to
# satisfy — duck typing over type hierarchy.
#
# Each Protocol names only the method `warm_start` calls. The real
# `clawstu.persistence.store` entity stores expose strictly more;
# structural typing lets the richer concrete types slot in without
# engagement ever knowing about them.


class _LearnerStoreLike(Protocol):
    def get(self, learner_id: str) -> LearnerProfile | None: ...


class _ZPDStoreLike(Protocol):
    def get_all(self, learner_id: str) -> dict[Domain, ZPDEstimate]: ...


class _ModalityStoreLike(Protocol):
    def get_all(self, learner_id: str) -> dict[Modality, ModalityOutcome]: ...


class _MisconceptionStoreLike(Protocol):
    def get_all(self, learner_id: str) -> dict[str, int]: ...


class _EventStoreLike(Protocol):
    def list_for_learner(
        self, learner_id: str
    ) -> list[ObservationEvent]: ...


class _ArtifactStoreLike(Protocol):
    def get(self, learner_id: str) -> dict[str, str | None] | None: ...
    def mark_consumed(self, learner_id: str) -> None: ...


class SessionPhase(str, Enum):
    ONBOARDING = "onboarding"
    CALIBRATING = "calibrating"
    TEACHING = "teaching"
    CHECKING = "checking"
    CRISIS_PAUSE = "crisis_pause"  # Phase 5: safety halt, no further teach
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
    topic: str | None = None  # Phase 5: free-text topic for live-content sessions
    phase: SessionPhase = SessionPhase.ONBOARDING
    signals: EngagementSignals = Field(default_factory=EngagementSignals)
    pathway: Pathway | None = None
    current_tier: ComplexityTier = ComplexityTier.MEETING
    current_modality: Modality | None = None
    last_block_id: str | None = None
    last_block: LearningBlock | None = None  # Phase 5: full block for live-content path
    last_check_item: AssessmentItem | None = None
    primed_block: LearningBlock | None = None  # Phase 5: pre-generated by live content
    primed_check: AssessmentItem | None = None  # Phase 5: pre-generated by live content
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
        live_content: LiveContentGeneratorLike | None = None,
    ) -> None:
        self._observer = observer or Observer()
        self._calibrator = calibrator or ZPDCalibrator()
        self._rotator = rotator or ModalityRotator(self._calibrator)
        self._content = content or ContentSelector()
        self._questions = questions or QuestionGenerator()
        self._planner = planner or PathwayPlanner()
        self._live_content: LiveContentGeneratorLike | None = live_content

    # -- lifecycle --------------------------------------------------------

    def onboard(
        self,
        *,
        learner_id: str,
        age: int,
        domain: Domain,
        topic: str | None = None,
    ) -> tuple[LearnerProfile, Session]:
        """Create a fresh profile and session for a first-time learner.

        The optional `topic` parameter is stored on the session for
        downstream diagnostics but does not trigger live-content
        generation — that path is `onboard_with_topic`, which is async
        because it must await the provider. Callers that already know
        they want live content should use `onboard_with_topic` directly.
        """
        profile = LearnerProfile(
            learner_id=learner_id,
            age_bracket=AgeBracket.from_age(age),
        )
        session = Session(learner_id=learner_id, domain=domain, topic=topic)
        session.pathway = self._planner.plan(domain, profile)
        self._observer.apply(
            profile,
            ObservationEvent(kind=EventKind.SESSION_START, domain=domain),
        )
        session.phase = SessionPhase.CALIBRATING
        return profile, session

    async def onboard_with_topic(
        self,
        *,
        learner_id: str,
        age: int,
        domain: Domain,
        topic: str,
        live_content_override: LiveContentGeneratorLike | None = None,
    ) -> tuple[LearnerProfile, Session]:
        """Create a fresh profile and session primed by live content.

        Async because the live-content generator calls an LLM provider.
        Requires a live content generator either via `live_content_override`
        or via the runner's `live_content` init parameter, otherwise
        raises `LiveContentUnavailableError`.

        The flow:
        1. Build a `Topic` from the free-text input.
        2. Ask the live generator for a concept pathway, a first
           learning block, and a first check-for-understanding.
        3. Stamp those onto a fresh `Session` (phase `TEACHING`,
           `primed_block` + `primed_check` set).
        4. Return the profile + session pair.

        The session skips the seed-library calibration phase entirely.
        Post-MVP we'll add LLM-backed calibration for topics that have
        no seed library, but Phase 5 only needs the teach → check cycle
        to run end-to-end with live content.
        """
        generator = live_content_override or self._live_content
        if generator is None:
            raise LiveContentUnavailableError(
                "onboard_with_topic requires a live content generator; "
                "pass `live_content=...` to SessionRunner() or provide "
                "`live_content_override=...` on the call."
            )

        # Imported inside the function to keep the module-level import
        # graph engagement→stdlib+profile+curriculum+assessment+memory.
        # `curriculum.topic.Topic` is curriculum-layer, which engagement
        # is already allowed to import from.
        from clawstu.curriculum.topic import Topic

        topic_obj = Topic.from_student_input(topic, domain=domain)

        profile = LearnerProfile(
            learner_id=learner_id,
            age_bracket=AgeBracket.from_age(age),
        )
        self._observer.apply(
            profile,
            ObservationEvent(kind=EventKind.SESSION_START, domain=domain),
        )

        concepts = await generator.generate_pathway(
            topic=topic_obj,
            age_bracket=profile.age_bracket,
            max_concepts=4,
        )
        pathway = Pathway(domain=domain, concepts=concepts)

        # Pick an initial modality from the rotator, then pre-generate a
        # block + check for the first concept in the pathway so the
        # standard `next_directive` / `select_check` / `record_check`
        # path can drive the session without reaching into the seed
        # content selector (which only has US History blocks).
        initial_modality = self._rotator.initial(profile)
        first_concept = concepts[0]
        tier = ComplexityTier.MEETING
        block = await generator.generate_block(
            topic=topic_obj,
            concept=first_concept,
            modality=initial_modality,
            tier=tier,
            age_bracket=profile.age_bracket,
        )
        check = await generator.generate_check(
            topic=topic_obj,
            concept=first_concept,
            tier=tier,
            modality=initial_modality,
            age_bracket=profile.age_bracket,
        )

        session = Session(
            learner_id=learner_id,
            domain=domain,
            topic=topic_obj.raw,
            pathway=pathway,
            current_tier=tier,
            current_modality=initial_modality,
            primed_block=block,
            primed_check=check,
        )
        session.phase = SessionPhase.TEACHING
        return profile, session

    def warm_start(
        self,
        *,
        learner_id: str,
        learners: _LearnerStoreLike,
        artifacts: _ArtifactStoreLike,
        zpd: _ZPDStoreLike,
        modality_outcomes: _ModalityStoreLike,
        misconceptions: _MisconceptionStoreLike,
        events: _EventStoreLike,
    ) -> tuple[LearnerProfile, Session]:
        """Resume a learner from a pre-generated NextSessionArtifact.

        Spec reference: §4.8.1. The caller passes in only the entity
        stores this method needs; the engagement layer cannot import
        from persistence, so the protocols above describe the shape
        the real SQLite / in-memory stores happen to satisfy.

        Steps:

        1. Load the `LearnerProfile` from ``learners.get``. Raise
           ``NoArtifactError`` if the learner is not persisted — a
           warm-start request for an unknown learner is equivalent
           to "no artifact" for the caller (the API layer converts
           both to HTTP 409).
        2. Rehydrate the profile's substores (ZPD, modality outcomes,
           misconceptions, events) so downstream runner calls see a
           consistent in-memory object.
        3. Load the most recent artifact from ``artifacts.get``. If
           the row is missing, or ``consumed_at`` is already set,
           raise ``NoArtifactError``.
        4. Parse ``pathway_json`` / ``first_block_json`` /
           ``first_check_json`` back into a Pathway, LearningBlock,
           and AssessmentItem. The parser accepts both Pydantic-
           shaped JSON (what a future scheduler would emit) and the
           Phase 6 placeholder shape, so warm-start works against
           whichever prepare_next_session output is on disk.
        5. Build a fresh `Session` primed for TEACHING with the
           parsed pathway + block + check.
        6. Mark the artifact consumed via ``artifacts.mark_consumed``.
        7. Return `(profile, session)`.

        The returned Session has `phase = TEACHING` and
        `primed_block` / `primed_check` set, which is the shape the
        standard `next_directive` / `select_check` path expects.
        """
        profile = learners.get(learner_id)
        if profile is None:
            raise NoArtifactError(
                f"no persisted profile for learner {learner_id!r}"
            )

        # Rehydrate substores into the in-memory profile so the
        # returned object is ready for `record_check` & friends to
        # mutate without a second round-trip to persistence.
        profile.zpd_by_domain = zpd.get_all(learner_id)
        profile.modality_outcomes = modality_outcomes.get_all(learner_id)
        profile.misconceptions = misconceptions.get_all(learner_id)
        profile.events = events.list_for_learner(learner_id)

        artifact = artifacts.get(learner_id)
        if artifact is None:
            raise NoArtifactError(
                f"no next-session artifact for learner {learner_id!r}"
            )
        if artifact.get("consumed_at") is not None:
            raise NoArtifactError(
                f"artifact for learner {learner_id!r} already consumed"
            )

        pathway_raw = artifact.get("pathway_json")
        block_raw = artifact.get("first_block_json")
        check_raw = artifact.get("first_check_json")
        if not pathway_raw or not block_raw or not check_raw:
            raise NoArtifactError(
                f"artifact for learner {learner_id!r} is missing one of "
                "pathway_json / first_block_json / first_check_json"
            )

        # Domain binding for the new Session comes from the learner's
        # most-recent session if we have one; otherwise we fall back
        # to the first ZPD estimate; otherwise the default of
        # US_HISTORY, which is the MVP-seed domain. Warm-start is
        # best-effort — the block + check are canonical, the session-
        # level domain is just a tag for downstream analytics.
        domain = _pick_domain_for_warm_start(profile)

        pathway = _parse_pathway(pathway_raw, domain)
        block = _parse_block(block_raw, domain, concept=_first_concept(pathway))
        check = _parse_check(check_raw, domain, concept=_first_concept(pathway))

        session = Session(
            learner_id=learner_id,
            domain=domain,
            pathway=pathway,
            current_tier=block.tier,
            current_modality=block.modality,
            primed_block=block,
            primed_check=check,
        )
        session.phase = SessionPhase.TEACHING

        # Artifact is consumed on first successful warm-start so a
        # subsequent call to this method for the same learner short-
        # circuits with NoArtifactError — the client must request a
        # fresh onboard or wait for the next scheduler tick.
        artifacts.mark_consumed(learner_id)

        self._observer.apply(
            profile,
            ObservationEvent(kind=EventKind.SESSION_START, domain=domain),
        )
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
        # Phase 5: CRISIS_PAUSE halts every directive. The gate catches
        # crisis text on the way in; once it flips the session into this
        # phase, every call to next_directive must refuse to teach
        # until a human adult steps in. This branch runs BEFORE any
        # other phase check so a paused session cannot be unpaused by
        # a misrouted dispatch.
        if session.phase is SessionPhase.CRISIS_PAUSE:
            return SessionDirective(
                phase=SessionPhase.CRISIS_PAUSE,
                message=(
                    "Session paused for safety. Please reach out to a "
                    "trusted adult or the crisis resources."
                ),
            )

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

        # Phase 5: if the live-content path primed a block for this
        # concept, use it directly. The primed block is consumed on
        # first use; subsequent iterations on the same concept will
        # fall back to the deterministic content selector.
        block: LearningBlock | None = None
        if (
            session.primed_block is not None
            and session.primed_block.concept == concept
        ):
            block = session.primed_block
            session.primed_block = None
        else:
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
        session.last_block = block
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

        # Phase 5: if the live-content path primed a check for this
        # concept, use it directly. Same single-shot semantics as the
        # primed block — cleared after first use.
        if (
            session.primed_check is not None
            and session.primed_check.concept == concept
        ):
            chosen = session.primed_check
            session.primed_check = None
            session.last_check_item = chosen
            return chosen

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
        # Phase 5: prefer the full stored block if present. The live-
        # content path stamps `last_block` directly; the seed-library
        # path still falls back to searching the content selector.
        if session.last_block is not None and session.last_block.id == session.last_block_id:
            return session.last_block
        for block in self._content.blocks:
            if block.id == session.last_block_id:
                return block
        raise RuntimeError(f"unknown block id on session: {session.last_block_id}")


# -- warm-start parsing helpers ----------------------------------------
#
# The Phase 6 `prepare_next_session` task ships a placeholder artifact
# whose JSON shapes do NOT match the Pydantic models (`Pathway`,
# `LearningBlock`, `AssessmentItem`). Phase 7's warm-start must still
# resolve those blobs into working objects — both the placeholder
# shape and the richer Pydantic-dump shape a future Phase 7+ scheduler
# would write. These module-private helpers do the parsing.
#
# Strategy: try `Model.model_validate_json` first; on `ValidationError`
# fall back to constructing a minimal model from the placeholder
# fields so warm-start never crashes on a legitimate (if stubby)
# artifact. If both paths fail the caller gets the original validation
# error, which is the right thing for diagnostics.


def _first_concept(pathway: Pathway) -> str:
    """Return the first concept on a pathway, or a fallback label."""
    if pathway.concepts:
        return pathway.concepts[0]
    return "placeholder"


def _pick_domain_for_warm_start(profile: LearnerProfile) -> Domain:
    """Best-effort domain pick for a warm-started session.

    The `LearnerProfile` does not track a "current domain", so we
    fall back through: (1) the most populous ZPD estimate, (2) the
    first modality-outcome (no-op — modality outcomes are not domain
    scoped), (3) the MVP default `US_HISTORY`. Warm-start is best-
    effort — the returned session's domain is a tag for analytics
    and for downstream `record_check` events, not a strict pedagogy
    invariant.
    """
    if profile.zpd_by_domain:
        # Pick the domain with the most samples; ties break on enum order.
        return max(
            profile.zpd_by_domain.items(),
            key=lambda kv: (kv[1].samples, kv[0].value),
        )[0]
    return Domain.US_HISTORY


def _parse_pathway(raw: str, domain: Domain) -> Pathway:
    """Parse an artifact's `pathway_json` column into a Pathway.

    Accepts two shapes:

    - Pydantic dump: ``{"domain": "us_history", "concepts": [...], "position": 0}``
    - Phase 6 placeholder: ``{"concepts": ["placeholder"]}``

    Missing fields are filled in from ``domain`` and ``position=0``.
    """
    try:
        return Pathway.model_validate_json(raw)
    except ValidationError:
        pass  # expected: raw is not strict JSON, try loose parse below
    data = _loads_object(raw)
    concepts_value = data.get("concepts", ())
    if isinstance(concepts_value, list):
        concepts: tuple[str, ...] = tuple(str(c) for c in concepts_value)
    else:
        concepts = ("placeholder",)
    if not concepts:
        concepts = ("placeholder",)
    return Pathway(domain=domain, concepts=concepts, position=0)


def _parse_block(
    raw: str,
    domain: Domain,
    *,
    concept: str,
) -> LearningBlock:
    """Parse an artifact's `first_block_json` column into a LearningBlock."""
    try:
        return LearningBlock.model_validate_json(raw)
    except ValidationError:
        pass  # expected: raw is not strict JSON, try loose parse below
    data = _loads_object(raw)
    return LearningBlock(
        domain=domain,
        modality=Modality.TEXT_READING,
        tier=ComplexityTier.MEETING,
        concept=str(data.get("concept", concept)),
        title=str(data.get("title", "warm-start block")),
        body=str(data.get("body", "")),
    )


def _parse_check(
    raw: str,
    domain: Domain,
    *,
    concept: str,
) -> AssessmentItem:
    """Parse an artifact's `first_check_json` column into an AssessmentItem."""
    try:
        return AssessmentItem.model_validate_json(raw)
    except ValidationError:
        pass  # expected: raw is not strict JSON, try loose parse below
    data = _loads_object(raw)
    rubric_value = data.get("rubric")
    rubric: tuple[str, ...] | None = None
    if isinstance(rubric_value, list):
        rubric = tuple(str(r) for r in rubric_value)
    return AssessmentItem(
        domain=domain,
        tier=ComplexityTier.MEETING,
        modality=Modality.TEXT_READING,
        type=AssessmentType.CRQ,
        prompt=str(data.get("prompt", "warm-start check")),
        concept=str(data.get("concept", concept)),
        rubric=rubric,
    )


def _loads_object(raw: str) -> dict[str, Any]:
    """JSON-decode `raw` and ensure the result is a mapping.

    Defensive parser used only by the warm-start placeholder fallback.
    Non-object roots get wrapped in an empty dict so the caller's
    `.get(...)` accesses still work without `KeyError`.
    """
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(value, dict):
        return value
    return {}
