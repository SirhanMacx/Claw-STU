"""Shared-secret bearer-token auth for learner-facing routes.

Spec reference: §4.9.2 (non-goal N8). The Phase 7 API surfaces four
learner-facing endpoints (`wiki`, `resume`, `queue`, `capture`) that
must not be callable from the open internet during local deployments,
but the MVP explicitly rejects per-learner identity management — it is
a single household / single classroom / single teacher use case.

The N8 design: a single process-wide token, read from
``STU_LEARNER_AUTH_TOKEN`` at request time. If the env var is unset,
the dependency is a no-op (dev mode, local loopback). If the env var
is set, every request must include an ``Authorization: Bearer <token>``
header whose value matches via ``secrets.compare_digest`` — constant-
time comparison so a network-adjacent attacker cannot derive the
secret byte-by-byte from response latency.

Learner-id binding is intentionally NOT checked. A valid token grants
access to any learner's data. This is acceptable for the deployment
model; post-MVP will upgrade to per-learner JWTs (non-goal N8).
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException

_AUTH_ENV_VAR = "STU_LEARNER_AUTH_TOKEN"
_BEARER_PREFIX = "Bearer "


def require_learner_auth(
    learner_id: str,
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency that gates learner-facing routes on a bearer token.

    - If ``STU_LEARNER_AUTH_TOKEN`` is unset, succeeds without checking
      anything. Dev mode.
    - If the env var is set and the ``Authorization`` header is missing
      or does not start with ``Bearer ``, raises HTTP 401.
    - If the header is present but the token does not match the env
      value (constant-time compare), raises HTTP 401.

    The ``learner_id`` path parameter is accepted so the dependency can
    be attached to routes shaped ``/learners/{learner_id}/...``, but it
    is not inspected. Any valid token grants access to any learner —
    this is the post-MVP upgrade path called out in N8.
    """
    expected = os.environ.get(_AUTH_ENV_VAR)
    if expected is None or expected == "":
        # Dev mode — no auth configured.
        return

    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise HTTPException(status_code=401, detail="unauthorized")
    presented = authorization[len(_BEARER_PREFIX) :]
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
