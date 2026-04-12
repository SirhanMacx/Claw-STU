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
  get HTTP 401.  Production deployments MUST set ``STU_AUTH_MODE=enforce``
  (or ``generate``) explicitly.
* **generate** — auto-create a cryptographically random token on first
  startup, save it to ``~/.claw-stu/api_token`` (0600), and log it
  once so the operator can configure clients.
* **dev** — original behaviour.  If ``STU_LEARNER_AUTH_TOKEN`` is
  unset, the dependency is a no-op.  Suitable for local loopback
  development only.

When ``STU_AUTH_MODE`` is *not* set the default is ``dev``.
Production deployments MUST set ``STU_AUTH_MODE=enforce`` or
``STU_AUTH_MODE=generate`` explicitly.

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
    """Determine the auth mode from the ``STU_AUTH_MODE`` env var.

    Resolution order:
    1. ``STU_AUTH_MODE`` if explicitly set to a valid mode.
    2. Default to ``dev`` (safe for local development).

    Production deployments MUST set ``STU_AUTH_MODE=enforce`` or
    ``STU_AUTH_MODE=generate`` explicitly. We no longer sniff
    ``UVICORN_HOST`` because that is fragile and unreliable when
    behind reverse proxies or inside containers.
    """
    explicit = os.environ.get(_MODE_ENV_VAR, "").strip().lower()
    if explicit in _VALID_MODES:
        return explicit
    return "dev"


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
    # Log once so the operator can copy it.
    logger.info(
        "Stuart API token (saved to %s): %s", _TOKEN_FILE, token,
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


def require_auth(
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency that gates routes on a bearer token.

    Same logic as ``require_learner_auth`` but without a ``learner_id``
    path parameter, making it suitable for routes that don't have one
    (session, profile, admin/scheduler).
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


def validate_token(token: str | None) -> bool:
    """Check a raw bearer token value against the expected token.

    Used for WebSocket auth where tokens arrive via query params
    instead of HTTP headers. Returns True if the token is valid,
    False otherwise. In dev mode with no token set, returns True.
    """
    mode = _resolve_mode()

    if mode == "dev":
        expected = os.environ.get(_AUTH_ENV_VAR, "").strip()
        if not expected:
            return True  # Dev mode — no auth configured.
    elif mode == "generate":
        expected = _get_or_generate_token()
    else:
        # enforce
        expected = os.environ.get(_AUTH_ENV_VAR, "").strip()
        if not expected:
            return False  # Misconfigured — reject.

    if token is None:
        return False
    return secrets.compare_digest(token, expected)


def validate_auth_on_startup() -> None:
    """Validate that auth is correctly configured at startup.

    Call from the app lifespan. If mode is ``enforce`` and no token is
    set, raises ``SystemExit`` with a clear error BEFORE the server
    starts accepting requests.
    """
    mode = _resolve_mode()
    if mode == "enforce":
        expected = os.environ.get(_AUTH_ENV_VAR, "").strip()
        if not expected:
            raise SystemExit(
                "FATAL: STU_AUTH_MODE=enforce but STU_LEARNER_AUTH_TOKEN "
                "is not set. Set the token or use STU_AUTH_MODE=generate."
            )
