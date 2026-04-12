"""Profile endpoints.

These exist to honor the SOUL.md commitment: *the learner owns their
profile*. Export and delete are first-class, not afterthoughts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from clawstu.api.auth import require_auth
from clawstu.api.state import AppState, get_state
from clawstu.profile.export import export_to_json
from clawstu.profile.model import LearnerProfile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/{session_id}", response_model=LearnerProfile)
def get_profile(
    session_id: str,
    _auth: None = Depends(require_auth),
    state: AppState = Depends(get_state),
) -> LearnerProfile:
    try:
        return state.get(session_id).profile
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{session_id}/export")
def export_profile(
    session_id: str,
    _auth: None = Depends(require_auth),
    state: AppState = Depends(get_state),
) -> Response:
    try:
        profile = state.get(session_id).profile
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    body = export_to_json(profile)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="profile-{profile.learner_id}.json"'
            ),
        },
    )


@router.delete("/{session_id}", status_code=204)
def delete_profile(
    session_id: str,
    _auth: None = Depends(require_auth),
    state: AppState = Depends(get_state),
) -> Response:
    """Delete everything the server knows about this session.

    This is a hard delete. The learner profile is gone from memory
    after this call returns. For a real deployment this would also
    scrub any persistent copies.
    """
    state.drop(session_id)
    return Response(status_code=204)
