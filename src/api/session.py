"""Session-lifecycle HTTP routes.

MVP endpoints:

- `POST /sessions`         — onboard a learner and start a session
- `GET  /sessions/{id}`    — fetch current session state
- `POST /sessions/{id}/calibration-answer` — submit a calibration answer
- `POST /sessions/{id}/finish-calibration` — transition to teaching
- `POST /sessions/{id}/next` — ask for the next teach/check directive
- `POST /sessions/{id}/check-answer` — submit a check-for-understanding answer
- `POST /sessions/{id}/close` — close the session

Every handler is a thin adapter around `SessionRunner`. The runner
contains the pedagogy; the handlers contain the HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.state import AppState, SessionBundle, get_state
from src.assessment.evaluator import Evaluator
from src.assessment.generator import AssessmentItem
from src.engagement.session import Session, SessionDirective, SessionPhase
from src.profile.model import Domain

router = APIRouter(prefix="/sessions", tags=["sessions"])


class OnboardRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=128)
    age: int = Field(ge=5, le=120)
    domain: Domain


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


class DirectiveResponse(BaseModel):
    directive: SessionDirective
    session: Session


class CloseResponse(BaseModel):
    summary: str


_evaluator = Evaluator()


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


@router.post("", response_model=OnboardResponse, status_code=201)
def onboard(
    request: OnboardRequest,
    state: AppState = Depends(get_state),
) -> OnboardResponse:
    try:
        profile, session = state.runner.onboard(
            learner_id=request.learner_id,
            age=request.age,
            domain=request.domain,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state.put(SessionBundle(profile=profile, session=session))
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
    item = state.runner.select_check(bundle.session)
    if item.id != request.item_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"item mismatch: expected {item.id}, got {request.item_id}"
            ),
        )
    result = _evaluator.evaluate(item, request.response)
    state.runner.record_check(
        bundle.profile,
        bundle.session,
        item,
        result,
        latency_seconds=request.latency_seconds,
    )
    directive = state.runner.next_directive(bundle.profile, bundle.session)
    return DirectiveResponse(directive=directive, session=bundle.session)


@router.post("/{session_id}/close", response_model=CloseResponse)
def close_session(
    session_id: str,
    state: AppState = Depends(get_state),
) -> CloseResponse:
    bundle = _bundle(state, session_id)
    summary = state.runner.close(bundle.profile, bundle.session)
    return CloseResponse(summary=summary)
