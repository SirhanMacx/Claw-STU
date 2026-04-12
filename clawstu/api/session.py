"""Session-lifecycle HTTP routes.

MVP endpoints:

- `POST /sessions`         — onboard a learner and start a session
- `GET  /sessions/{id}`    — fetch current session state
- `POST /sessions/{id}/calibration-answer` — submit a calibration answer
- `POST /sessions/{id}/finish-calibration` — transition to teaching
- `POST /sessions/{id}/next` — ask for the next teach/check directive
- `POST /sessions/{id}/check-answer` — submit a check-for-understanding answer
- `POST /sessions/{id}/socratic` — ad-hoc student question (Phase 5)
- `POST /sessions/{id}/close` — close the session

Every handler is a thin adapter around `SessionRunner`. The runner
contains the pedagogy; the handlers contain the HTTP.

Phase 5: every student-text entry point runs `_GATE.scan(...)`
before touching the runner. A crisis detection flips the session
into `CRISIS_PAUSE` and returns the escalation resources; a boundary
violation returns HTTP 400 with a restate message.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from clawstu.api.state import AppState, SessionBundle, get_state
from clawstu.assessment.evaluator import EvaluationResult, Evaluator
from clawstu.assessment.generator import AssessmentItem
from clawstu.engagement.session import Session, SessionDirective, SessionPhase
from clawstu.memory.writer import SessionSnapshot, write_session_to_memory
from clawstu.orchestrator.config import load_config
from clawstu.orchestrator.live_content import LiveContentGenerator
from clawstu.orchestrator.router import ModelRouter
from clawstu.profile.model import Domain, EventKind, LearnerProfile
from clawstu.safety.boundaries import BoundaryEnforcer
from clawstu.safety.escalation import EscalationHandler
from clawstu.safety.gate import InboundDecision, InboundSafetyGate

router = APIRouter(prefix="/sessions", tags=["sessions"])


class OnboardRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=128)
    age: int = Field(ge=5, le=120)
    domain: Domain
    # Optional free-text topic. When present, the handler uses the async
    # `onboard_with_topic` path to generate a live pathway via the LLM.
    # When absent, the sync `runner.onboard()` path runs deterministic
    # seed-library calibration.
    topic: str | None = Field(default=None, max_length=200)


class OnboardResponse(BaseModel):
    session_id: str
    phase: SessionPhase
    calibration_items: tuple[AssessmentItem, ...]


class AnswerRequest(BaseModel):
    item_id: str
    response: str
    latency_seconds: float | None = None


class AnswerResponse(BaseModel):
    correct: bool
    score: float
    phase: SessionPhase
    # Phase 5: crisis escalation payload. When `crisis` is True the
    # session has been flipped to CRISIS_PAUSE and `resources` contains
    # the escalation message. Other fields are zeroed.
    crisis: bool = False
    resources: str | None = None


class DirectiveResponse(BaseModel):
    directive: SessionDirective
    session: Session
    # Phase 5: mirrored crisis payload so clients that only call
    # /check-answer get a uniform crisis signal.
    crisis: bool = False
    resources: str | None = None


class SocraticRequest(BaseModel):
    student_input: str = Field(min_length=1, max_length=2000)


class SocraticResponse(BaseModel):
    response: str
    phase: SessionPhase
    crisis: bool = False
    resources: str | None = None


class CloseResponse(BaseModel):
    summary: str


_evaluator = Evaluator()

# Module-level gate. Stateless and safe to share across concurrent
# handlers. Tests can monkey-patch this with `api_session._GATE = ...`.
_GATE: InboundSafetyGate = InboundSafetyGate(
    EscalationHandler(), BoundaryEnforcer()
)


def _bundle(state: AppState, session_id: str) -> SessionBundle:
    try:
        return state.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _item_by_id(items: tuple[AssessmentItem, ...], item_id: str) -> AssessmentItem:
    for item in items:
        if item.id == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"unknown item: {item_id}")


def _halt_for_crisis(
    state: AppState,
    bundle: SessionBundle,
    decision: InboundDecision,
) -> str:
    """Flip the session into CRISIS_PAUSE and return the resource text.

    Called from every student-text handler when the gate reports a
    crisis. The handler then wraps the returned text in whatever
    response shape it's supposed to serialize.
    """
    assert decision.action == "crisis"
    assert decision.crisis_detection is not None
    bundle.session.phase = SessionPhase.CRISIS_PAUSE
    state.checkpoint(bundle.session.id)
    return _GATE.escalation.resources(decision.crisis_detection)


def _halt_for_boundary(decision: InboundDecision) -> HTTPException:
    """Convert a boundary violation into a 400 HTTPException.

    The detail surfaces the canonical restate message from the
    enforcer so the client has something to show the user.
    """
    assert decision.action == "boundary"
    assert decision.boundary_violation is not None
    restate = BoundaryEnforcer.restate(decision.boundary_violation)
    return HTTPException(status_code=400, detail=restate)


@router.post("", response_model=OnboardResponse, status_code=201)
async def onboard(
    request: OnboardRequest,
    state: AppState = Depends(get_state),
) -> OnboardResponse:
    try:
        if request.topic is not None:
            # Topic-aware path: use the live-content generator so
            # arbitrary topics go through the LLM-backed pathway.
            # If the provider is unreachable, fall back to the sync
            # path so the session still starts with the topic stored.
            from clawstu.api.main import build_providers

            cfg = load_config()
            providers = build_providers(cfg)
            router = ModelRouter(config=cfg, providers=providers)
            live = LiveContentGenerator(router=router)
            try:
                profile, session = await state.runner.onboard_with_topic(
                    learner_id=request.learner_id,
                    age=request.age,
                    domain=request.domain,
                    topic=request.topic,
                    live_content_override=live,
                )
            except Exception:
                profile, session = state.runner.onboard(
                    learner_id=request.learner_id,
                    age=request.age,
                    domain=request.domain,
                    topic=request.topic,
                )
        else:
            # No topic: deterministic seed-library path with calibration.
            profile, session = state.runner.onboard(
                learner_id=request.learner_id,
                age=request.age,
                domain=request.domain,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state.put(SessionBundle(profile=profile, session=session))
    items: tuple[AssessmentItem, ...] = ()
    if session.phase is SessionPhase.CALIBRATING:
        items = state.runner.calibration_items(session)
    return OnboardResponse(
        session_id=session.id,
        phase=session.phase,
        calibration_items=items,
    )


@router.get("/{session_id}", response_model=Session)
def get_session(
    session_id: str,
    state: AppState = Depends(get_state),
) -> Session:
    return _bundle(state, session_id).session


@router.post("/{session_id}/calibration-answer", response_model=AnswerResponse)
def submit_calibration_answer(
    session_id: str,
    request: AnswerRequest,
    state: AppState = Depends(get_state),
) -> AnswerResponse:
    bundle = _bundle(state, session_id)
    if bundle.session.phase is not SessionPhase.CALIBRATING:
        raise HTTPException(
            status_code=409,
            detail=f"session is in phase {bundle.session.phase}, not calibrating",
        )
    # Phase 5: every student-text entry point runs the inbound safety
    # gate BEFORE the runner sees the response.
    decision = _GATE.scan(request.response)
    if decision.action == "crisis":
        resources = _halt_for_crisis(state, bundle, decision)
        return AnswerResponse(
            correct=False,
            score=0.0,
            phase=bundle.session.phase,
            crisis=True,
            resources=resources,
        )
    if decision.action == "boundary":
        raise _halt_for_boundary(decision)

    items = state.runner.calibration_items(bundle.session)
    item = _item_by_id(items, request.item_id)
    result = _evaluator.evaluate(item, request.response)
    state.runner.record_calibration_answer(
        bundle.profile,
        bundle.session,
        item,
        result,
        latency_seconds=request.latency_seconds,
    )
    return AnswerResponse(
        correct=result.correct,
        score=result.score,
        phase=bundle.session.phase,
    )


@router.post("/{session_id}/finish-calibration", response_model=DirectiveResponse)
def finish_calibration(
    session_id: str,
    state: AppState = Depends(get_state),
) -> DirectiveResponse:
    bundle = _bundle(state, session_id)
    state.runner.finish_calibration(bundle.profile, bundle.session)
    directive = state.runner.next_directive(bundle.profile, bundle.session)
    return DirectiveResponse(directive=directive, session=bundle.session)


@router.post("/{session_id}/next", response_model=DirectiveResponse)
def next_directive(
    session_id: str,
    state: AppState = Depends(get_state),
) -> DirectiveResponse:
    bundle = _bundle(state, session_id)
    directive = state.runner.next_directive(bundle.profile, bundle.session)
    return DirectiveResponse(directive=directive, session=bundle.session)


@router.post("/{session_id}/check-answer", response_model=DirectiveResponse)
def submit_check_answer(
    session_id: str,
    request: AnswerRequest,
    state: AppState = Depends(get_state),
) -> DirectiveResponse:
    bundle = _bundle(state, session_id)
    # Phase 5: gate the inbound student text before anything else.
    decision = _GATE.scan(request.response)
    if decision.action == "crisis":
        resources = _halt_for_crisis(state, bundle, decision)
        # A crisis pause returns a CRISIS_PAUSE directive; the client
        # MUST interpret `crisis=True` and surface the resources.
        directive = state.runner.next_directive(bundle.profile, bundle.session)
        return DirectiveResponse(
            directive=directive,
            session=bundle.session,
            crisis=True,
            resources=resources,
        )
    if decision.action == "boundary":
        raise _halt_for_boundary(decision)

    item = state.runner.select_check(bundle.session)
    if item.id != request.item_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"item mismatch: expected {item.id}, got {request.item_id}"
            ),
        )
    result: EvaluationResult = _evaluator.evaluate(item, request.response)
    state.runner.record_check(
        bundle.profile,
        bundle.session,
        item,
        result,
        latency_seconds=request.latency_seconds,
    )
    directive = state.runner.next_directive(bundle.profile, bundle.session)
    return DirectiveResponse(directive=directive, session=bundle.session)


@router.post("/{session_id}/socratic", response_model=SocraticResponse)
async def socratic(
    session_id: str,
    request: SocraticRequest,
    state: AppState = Depends(get_state),
) -> SocraticResponse:
    """Ad-hoc student question routed through the safety gate and the
    real Socratic dialogue path via `ReasoningChain.ask()`.

    Safety ordering is preserved:
    1. crisis first — immediate pause + resources
    2. boundary second — HTTP 400 with restate
    3. allow — route through the orchestrator
    """
    from clawstu.api.main import build_providers
    from clawstu.orchestrator.chain import ReasoningChain
    from clawstu.orchestrator.task_kinds import TaskKind

    bundle = _bundle(state, session_id)
    decision = _GATE.scan(request.student_input)
    if decision.action == "crisis":
        resources = _halt_for_crisis(state, bundle, decision)
        return SocraticResponse(
            response=resources,
            phase=bundle.session.phase,
            crisis=True,
            resources=resources,
        )
    if decision.action == "boundary":
        raise _halt_for_boundary(decision)

    # Route through the real orchestrator-backed Socratic path.
    # If the primary provider is unreachable (e.g. Ollama not running),
    # fall back to Echo so the endpoint never returns an error for a
    # benign, non-crisis, non-boundary student question.
    from clawstu.orchestrator.providers import ProviderError

    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    chain = ReasoningChain(router=router)
    try:
        response_text = await chain.ask(
            request.student_input, task_kind=TaskKind.SOCRATIC_DIALOGUE,
        )
    except ProviderError:
        from clawstu.orchestrator.providers import EchoProvider, LLMProvider

        echo_providers: dict[str, LLMProvider] = {"echo": EchoProvider()}
        echo_router = ModelRouter(config=cfg, providers=echo_providers)
        fallback_chain = ReasoningChain(router=echo_router)
        response_text = await fallback_chain.ask(
            request.student_input, task_kind=TaskKind.SOCRATIC_DIALOGUE,
        )
    return SocraticResponse(
        response=response_text,
        phase=bundle.session.phase,
    )


def _adapt_session_for_memory(
    session: Session,
    profile: LearnerProfile,
    summary: str,
) -> SessionSnapshot:
    """Build a memory-layer `SessionSnapshot` from a finished session.

    The memory layer must not import from engagement (layer DAG), so
    the adapter lives here in the API layer. Concepts touched come
    from the pathway up to its current position; wrong-answer
    concepts are harvested from the profile's CHECK_FOR_UNDERSTANDING
    events for this session's domain where `correct=False`.
    """
    concepts_touched: tuple[str, ...] = ()
    if session.pathway is not None:
        # Positions 0..current are concepts that have been seen.
        position = session.pathway.position
        covered = session.pathway.concepts[: max(0, min(position + 1, len(session.pathway.concepts)))]
        # De-duplicate while preserving order.
        seen: list[str] = []
        for concept in covered:
            if concept not in seen:
                seen.append(concept)
        concepts_touched = tuple(seen)

    wrong_concepts: list[str] = []
    for event in profile.events:
        if (
            event.kind is EventKind.CHECK_FOR_UNDERSTANDING
            and event.domain is session.domain
            and event.concept
            and event.correct is False
            and event.concept not in wrong_concepts
        ):
            wrong_concepts.append(event.concept)

    return SessionSnapshot(
        session_id=session.id,
        learner_id=session.learner_id,
        concepts_touched=concepts_touched,
        wrong_answer_concepts=tuple(wrong_concepts),
        blocks_presented=session.blocks_presented,
        reteach_count=session.reteach_count,
        summary=summary,
    )


@router.post("/{session_id}/close", response_model=CloseResponse)
def close_session(
    session_id: str,
    state: AppState = Depends(get_state),
) -> CloseResponse:
    bundle = _bundle(state, session_id)
    summary = state.runner.close(bundle.profile, bundle.session)
    # Phase 5: if the app state has a brain store wired, mint the
    # post-session pages (learner + concept + session + misconception)
    # and emit KG triples. Best-effort: a brain-store failure must not
    # break the HTTP response — this is session hygiene, not a critical
    # path. We checkpoint first so the session-close event is durable
    # regardless of the memory write outcome.
    state.checkpoint(session_id)
    if state.brain_store is not None:
        snapshot = _adapt_session_for_memory(
            bundle.session, bundle.profile, summary
        )
        write_session_to_memory(
            profile=bundle.profile,
            snapshot=snapshot,
            brain_store=state.brain_store,
            kg_store=state.persistence.kg,
        )
    return CloseResponse(summary=summary)
