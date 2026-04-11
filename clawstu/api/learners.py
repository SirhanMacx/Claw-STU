"""Phase 7 learner-facing endpoints.

Spec reference: §4.9.2. Four routes, all gated on
`require_learner_auth`:

- `GET  /learners/{learner_id}/wiki/{concept}` — per-student concept
  wiki rendered from the brain store and the knowledge graph.
- `POST /learners/{learner_id}/resume` — warm-start from a pre-
  generated NextSessionArtifact. Returns the first block immediately
  with no provider call in the hot path.
- `GET  /learners/{learner_id}/queue` — a compact scheduler view for
  the learner: pending spaced reviews, whether a pre-generated
  artifact is waiting, and a placeholder for flagged gap concepts.
- `POST /learners/{learner_id}/capture` — student-shared source text.
  Gated by `InboundSafetyGate`, then persisted via
  `clawstu.memory.capture.capture_source`.

All handlers return typed pydantic responses. The inbound safety gate
is imported from `clawstu.api.session` so there's one shared choke
point for every student-text entry point instead of two independent
copies with slightly-different rules.

Layering note: `api` is the top layer, so importing from memory,
engagement, curriculum, safety, and persistence is allowed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from clawstu.api.auth import require_learner_auth
from clawstu.api.session import _GATE
from clawstu.api.state import AppState, SessionBundle, get_state
from clawstu.curriculum.content import LearningBlock
from clawstu.engagement.session import NoArtifactError, SessionPhase
from clawstu.memory.capture import capture_source
from clawstu.memory.wiki import generate_concept_wiki
from clawstu.profile.model import EventKind

router = APIRouter(prefix="/learners", tags=["learners"])


# -- response models ----------------------------------------------------


class ResumeResponse(BaseModel):
    """Payload returned by `POST /learners/{id}/resume`.

    `warm_start` is always True on a successful response — the field
    is there so clients can mirror the spec §4.8.2 shape and so that
    a future "hybrid" onboard path can set it False without having
    to invent a new response model.
    """

    session_id: str
    phase: SessionPhase
    block: LearningBlock | None
    warm_start: bool = True


class LearnerQueueResponse(BaseModel):
    """Payload returned by `GET /learners/{id}/queue`.

    The queue is a forward-looking summary of what the scheduler has
    ready for the learner. Phase 7 ships the three buckets the spec
    calls out; any one of them can be empty.
    """

    learner_id: str
    pending_reviews: int
    pending_artifact: bool
    flagged_gaps: list[str]


class CaptureRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10_000)


class CaptureResponse(BaseModel):
    source_id: str


# -- helpers -----------------------------------------------------------


def _source_id_for(learner_id: str, title: str, text: str) -> str:
    """Derive a stable-ish slug for a captured source.

    We combine the learner id, title, and a short hash of the body
    text so two captures with identical titles from the same student
    land in different SourcePages. The result is used as both the
    URL-safe source_id and the filename in the brain store.
    """
    body_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    slug = "".join(
        c if c.isalnum() or c in "-_" else "-" for c in title.lower()
    ).strip("-")
    if not slug:
        slug = "source"
    slug = slug[:40]
    return f"{slug}-{body_hash}"


def _count_pending_reviews(state: AppState, learner_id: str) -> int:
    """Count concepts whose last CHECK_FOR_UNDERSTANDING is > 7 days old.

    Mirrors the Phase 6 `spaced_review` task's spacing policy inline
    so the queue route does not depend on the scheduler subsystem.
    The calculation is O(n) in the number of observation events for
    a learner.
    """
    cutoff = datetime.now(UTC) - timedelta(days=7)
    last_seen: dict[str, datetime] = {}
    for event in state.persistence.events.list_for_learner(learner_id):
        if event.kind is not EventKind.CHECK_FOR_UNDERSTANDING:
            continue
        if event.concept is None:
            continue
        prior = last_seen.get(event.concept)
        if prior is None or event.timestamp > prior:
            last_seen[event.concept] = event.timestamp
    return sum(1 for ts in last_seen.values() if ts < cutoff)


# -- routes ------------------------------------------------------------


@router.get("/{learner_id}/wiki/{concept}")
def get_concept_wiki(
    learner_id: str,
    concept: str,
    _auth: None = Depends(require_learner_auth),
    state: AppState = Depends(get_state),
) -> Response:
    """Render a per-student concept wiki as markdown.

    The wiki generator pulls from both the brain store (for the
    ConceptPage compiled truth and session references) and the
    knowledge graph (for `taught_in` / `has_source` triples), so the
    route requires a brain store to be configured on `AppState`. If
    the app was built without one it returns 503 — the wiki is a
    Phase 5 surface and there is no sensible no-op fallback.
    """
    if state.brain_store is None:
        raise HTTPException(status_code=503, detail="brain store not configured")
    markdown = generate_concept_wiki(
        learner_id=learner_id,
        concept=concept,
        brain_store=state.brain_store,
        kg_store=state.persistence.kg,
    )
    return Response(content=markdown, media_type="text/markdown")


@router.post("/{learner_id}/resume", response_model=ResumeResponse)
def resume_learner(
    learner_id: str,
    _auth: None = Depends(require_learner_auth),
    state: AppState = Depends(get_state),
) -> ResumeResponse:
    """Warm-start a learner from a pre-generated artifact.

    Calls `SessionRunner.warm_start` and translates its
    `NoArtifactError` into HTTP 409 with a body telling the client
    to fall back to `POST /sessions` (normal onboard). On success
    the returned session is primed for TEACHING, so the next call
    from the client is typically `POST /sessions/{id}/check-answer`.
    """
    try:
        profile, session = state.runner.warm_start(
            learner_id=learner_id,
            learners=state.persistence.learners,
            artifacts=state.persistence.artifacts,
            zpd=state.persistence.zpd,
            modality_outcomes=state.persistence.modality_outcomes,
            misconceptions=state.persistence.misconceptions,
            events=state.persistence.events,
        )
    except NoArtifactError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "No pre-generated session. "
                "Use POST /sessions to onboard."
            ),
        ) from exc
    state.put(SessionBundle(profile=profile, session=session))
    return ResumeResponse(
        session_id=session.id,
        phase=session.phase,
        block=session.primed_block,
        warm_start=True,
    )


@router.get("/{learner_id}/queue", response_model=LearnerQueueResponse)
def get_queue(
    learner_id: str,
    _auth: None = Depends(require_learner_auth),
    state: AppState = Depends(get_state),
) -> LearnerQueueResponse:
    """Return a compact forward-looking queue for the learner.

    Three buckets:

    - `pending_reviews`: concepts whose last check was > 7 days ago,
      computed inline from the event stream (no scheduler
      dependency).
    - `pending_artifact`: True if an unconsumed NextSessionArtifact
      is waiting.
    - `flagged_gaps`: empty for Phase 7 — gap detection is a later-
      phase concern. The field is present so the client wire
      format is stable.
    """
    artifact = state.persistence.artifacts.get(learner_id)
    pending_artifact = (
        artifact is not None and artifact.get("consumed_at") is None
    )
    return LearnerQueueResponse(
        learner_id=learner_id,
        pending_reviews=_count_pending_reviews(state, learner_id),
        pending_artifact=pending_artifact,
        flagged_gaps=[],
    )


@router.post(
    "/{learner_id}/capture",
    response_model=CaptureResponse,
    status_code=201,
)
def capture_source_route(
    learner_id: str,
    request: CaptureRequest,
    _auth: None = Depends(require_learner_auth),
    state: AppState = Depends(get_state),
) -> CaptureResponse:
    """Accept a student-shared primary source and persist it.

    Flow:

    1. Require a brain store — sources are written to the brain, not
       the SQLite side.
    2. Run the inbound safety gate on the text. Crisis or boundary
       violations produce an HTTP 400 with a caller-readable detail
       string. The route does NOT flip any session into CRISIS_PAUSE
       — capture is a per-learner, session-agnostic endpoint.
    3. Resolve the learner's age bracket from the persisted profile
       so `capture_source` can stamp it on the SourcePage. Missing
       profile → 404; the caller must onboard first.
    4. Mint a stable source slug from title + body hash.
    5. Hand off to the memory layer's `capture_source` and return
       the new source id.
    """
    if state.brain_store is None:
        raise HTTPException(
            status_code=503, detail="brain store not configured"
        )
    decision = _GATE.scan(request.text)
    if decision.action == "crisis":
        raise HTTPException(status_code=400, detail="crisis_detected")
    if decision.action == "boundary":
        raise HTTPException(status_code=400, detail="boundary_violation")

    profile = state.persistence.learners.get(learner_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown learner: {learner_id}",
        )

    source_id = _source_id_for(learner_id, request.title, request.text)
    page = capture_source(
        request.text,
        source_id=source_id,
        title=request.title,
        age_bracket=profile.age_bracket.value,
        brain_store=state.brain_store,
        learner_id=learner_id,
    )
    return CaptureResponse(source_id=page.source_id)


__all__ = [
    "CaptureRequest",
    "CaptureResponse",
    "LearnerQueueResponse",
    "ResumeResponse",
    "router",
]
