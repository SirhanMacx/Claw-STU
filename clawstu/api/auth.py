"""Shared-secret bearer-token auth for learner-facing routes.

Spec reference: §4.9.2 (non-goal N8). The Phase 7 API surfaces four
learner-facing endpoints (``wiki``, ``resume``, ``queue``, ``capture``)
that must not be callable from the open internet during local
deployments, but the MVP explicitly rejects per-learner identity
management — it is a single household / single classroom / single
teacher use case.

Auth modes (controlled by ``STU_AUTH_MODE`` env var):

* **enforce** — a token *must* be set via ``STU_LEARNER_AUTH_TOKEN``.
  Requests without a valid ``Authorization: Bearer <token>`` header
  get HTTP 401.  This is the default when the server binds to a
  non-loopback address.
* **generate** — auto-create a cryptographically random token on first
  startup, save it to ``~/.claw-stu/api_token`` (0600), and print it
  once to stderr so the operator can configure clients.
* **dev** — original behaviour.  If ``STU_LEARNER_AUTH_TOKEN`` is
  unset, the dependency is a no-op.  Suitable for local loopback
  development only.

When ``STU_AUTH_MODE`` is *not* set the default is ``dev`` for
localhost-bound processes and ``enforce`` otherwise, matching the
principle-of-least-surprise for production deployments.

The ``learner_id`` path parameter is accepted so the dependency can be
attached to routes shaped ``/learners/{learner_id}/...``, but it is
not inspected.  Any valid token grants access to any learner — this
is the post-MVP upgrade path called out in N8.
"""

from __future__ import annotations

import logging
import os
import secrets
import stat
import sys
from pathlib import Path

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

_AUTH_ENV_VAR = "STU_LEARNER_AUTH_TOKEN"
_MODE_ENV_VAR = "STU_AUTH_MODE"
_BEARER_PREFIX = "Bearer "
_DATA_DIR = Path(
    os.environ.get("CLAW_STU_DATA_DIR", str(Path.home() / ".claw-stu"))
)
_TOKEN_FILE = _DATA_DIR / "api_token"

# ── Mode resolution ──────────────────────────────────────────────────

_VALID_MODES = frozenset({"enforce", "generate", "dev"})


def _resolve_mode() -> str:
    """Determine the auth mode from env vars and bind address."""
    explicit = os.environ.get(_MODE_ENV_VAR, "").strip().lower()
    if explicit in _VALID_MODES:
        return explicit
    # No explicit mode: default to dev when the server is localhost.
    host = os.environ.get("UVICORN_HOST", "127.0.0.1")
    if host in ("127.0.0.1", "::1", "localhost"):
        return "dev"
    return "enforce"


def _get_or_generate_token() -> str:
    """Return the token from the env var, or generate and persist one."""
    existing = os.environ.get(_AUTH_ENV_VAR, "").strip()
    if existing:
        return existing
    # Check the persisted token file first.
    if _TOKEN_FILE.exists():
        token = _TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    # Generate a new token.
    token = secrets.token_urlsafe(32)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        _TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        logger.warning(
            "Could not set 0600 on %s — verify permissions manually",
            _TOKEN_FILE,
        )
    # Print once so the operator can copy it.
    print(
        f"\n  Stuart API token (saved to {_TOKEN_FILE}):\n"
        f"  {token}\n",
        file=sys.stderr,
    )
    return token


# ── FastAPI dependency ───────────────────────────────────────────────

def require_learner_auth(
    learner_id: str,
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency that gates learner-facing routes on a bearer token.

    Behaviour depends on the resolved auth mode:

    * **dev** — if ``STU_LEARNER_AUTH_TOKEN`` is unset, succeed without
      checking.  If the env var *is* set, enforce it.
    * **generate** — auto-create a token on first call, then enforce it.
    * **enforce** — the env var *must* be set; raise 401 otherwise.

    Constant-time comparison via ``secrets.compare_digest`` prevents
    timing-based side-channel attacks.
    """
    mode = _resolve_mode()

    if mode == "dev":
        expected = os.environ.get(_AUTH_ENV_VAR, "").strip()
        if not expected:
            return  # Dev mode — no auth configured.
    elif mode == "generate":
        expected = _get_or_generate_token()
    else:
        # enforce
        expected = os.environ.get(_AUTH_ENV_VAR, "").strip()
        if not expected:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Server misconfigured: STU_AUTH_MODE=enforce but "
                    "STU_LEARNER_AUTH_TOKEN is not set."
                ),
            )

    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise HTTPException(status_code=401, detail="unauthorized")
    presented = authorization[len(_BEARER_PREFIX):]
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
