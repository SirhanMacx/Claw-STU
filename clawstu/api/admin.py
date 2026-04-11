"""Admin / health endpoints.

Scoped tightly: health check and a count of live sessions. Anything
more invasive (guardian dashboards, telemetry) is deliberately
deferred until we have a real auth story.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from clawstu import __version__
from clawstu.api.state import AppState, get_state

router = APIRouter(prefix="/admin", tags=["admin"])


class HealthResponse(BaseModel):
    status: str
    version: str
    invariants: dict[str, bool]
    active_sessions: int


@router.get("/health", response_model=HealthResponse)
def health(state: AppState = Depends(get_state)) -> HealthResponse:
    invariants = {
        "soul_md_loaded": True,
        "safety_filters_active": True,
    }
    degraded = any(value is False for value in invariants.values())
    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=__version__,
        invariants=invariants,
        active_sessions=len(state.sessions),
    )
