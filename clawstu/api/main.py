"""FastAPI app entry point.

Run locally with:

    uvicorn clawstu.api.main:app --reload
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from clawstu.engagement.session import Session, SessionRunner
    from clawstu.profile.model import Domain, LearnerProfile

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.staticfiles import StaticFiles

from clawstu import __version__
from clawstu.api import admin, learners, profile, quick, session
from clawstu.api.state import AppState, get_state
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig, load_config
from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.provider_google import GoogleProvider
from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import default_registry
from clawstu.scheduler.runner import SchedulerRunner

# ── WebSocket message models (STU-7) ───────────────────────────────

class WsOnboardMessage(BaseModel):
    type: Literal["onboard"]
    name: str = Field(min_length=1, max_length=128)
    age: int = Field(ge=5, le=120)
    topic: str | None = Field(default=None, max_length=200)
    domain: str | None = None


class WsAnswerMessage(BaseModel):
    type: Literal["answer"]
    text: str = Field(min_length=1, max_length=2000)


# ── Per-connection WebSocket rate limiter ──────────────────────────

_WS_MAX_MESSAGES_PER_MINUTE = 30
_WS_MAX_MESSAGE_SIZE = 4096  # 4KB


class _WsRateLimiter:
    """Per-connection message rate limiter for WebSocket connections."""

    def __init__(self, max_per_minute: int = _WS_MAX_MESSAGES_PER_MINUTE) -> None:
        self._max = max_per_minute
        self._timestamps: list[float] = []

    def check(self) -> bool:
        """Return True if the message is allowed, False if rate-limited."""
        now = time.time()
        cutoff = now - 60.0
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True


def build_providers(cfg: AppConfig) -> dict[str, LLMProvider]:
    """Build the provider dict the router will draw from.

    Echo + Ollama are always present:
      * Echo is the fallback-chain floor required by ModelRouter; it
        guarantees every TaskKind resolves to *something* even when
        no real keys are configured.
      * Ollama uses a local-by-default base URL and only fails at
        ``.complete()`` time if the daemon isn't running, which the
        router cleanly handles via the fallback chain.

    The three network providers are added only when their API key is
    populated in `cfg`. A missing key means the provider isn't built
    and the router naturally falls through to the next entry in
    `cfg.fallback_chain`.

    Public because :mod:`clawstu.cli_chat` reuses the same factory to
    construct providers for the in-process learn / resume commands.
    The Phase 8 Part 2 chat loop runs without the HTTP app, so it
    builds its own ModelRouter directly, and duplicating this factory
    would mean two places to keep in sync every time a new provider
    lands.
    """
    providers: dict[str, LLMProvider] = {
        "echo": EchoProvider(),
        "ollama": OllamaProvider(
            base_url=cfg.ollama_base_url,
            api_key=cfg.ollama_api_key,
        ),
    }
    if cfg.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(
            api_key=cfg.anthropic_api_key,
            base_url=cfg.anthropic_base_url,
        )
    if cfg.openai_api_key:
        providers["openai"] = OpenAIProvider(
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
        )
    if cfg.openrouter_api_key:
        providers["openrouter"] = OpenRouterProvider(
            api_key=cfg.openrouter_api_key,
            base_url=cfg.openrouter_base_url,
        )
    if cfg.google_api_key:
        providers["google"] = GoogleProvider(
            api_key=cfg.google_api_key,
            base_url=cfg.google_base_url,
        )
    return providers


def _build_proactive_context(state: AppState) -> ProactiveContext:
    """Construct the `ProactiveContext` the scheduler runs against.

    Loads `AppConfig` via `load_config()` (which respects env vars +
    ~/.claw-stu/secrets.json) and builds a router whose providers are
    the real network-backed clients for whichever keys are populated.
    Echo and Ollama are always included; Anthropic, OpenAI, and
    OpenRouter only when their respective api_key is set on `cfg`.

    A `load_config()` failure (malformed secrets.json, typo'd field
    name caught by pydantic ``extra="forbid"``) is allowed to bubble
    up unchanged. Lifespan startup MUST fail loud on a bad config
    rather than silently fall through to Echo and lull the operator
    into thinking the scheduler is talking to real providers.

    The brain store is taken from `AppState` if configured, otherwise
    a tmp directory is created so the dream cycle has a real
    BrainStore to walk in tests and offline development.
    """
    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    brain_store = state.brain_store or BrainStore(
        Path(tempfile.gettempdir()) / "clawstu-brain"
    )
    return ProactiveContext(
        router=router,
        brain_store=brain_store,
        persistence=state.persistence,
    )


def build_scheduler_runner(state: AppState) -> SchedulerRunner:
    """Public factory used by the lifespan and tests.

    Tests construct the runner via this helper to avoid duplicating
    the `ProactiveContext` wiring; production lifespan calls it on
    startup. The lifespan owns calling `await runner.start()`; this
    factory only constructs.
    """
    return SchedulerRunner(
        registry=default_registry(),
        context=_build_proactive_context(state),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the proactive scheduler on app startup, stop on shutdown.

    Spec reference: §4.7.6. The runner is stashed on `app.state` so
    the admin route can read it back via the FastAPI request scope.

    Also validates auth configuration at startup: if STU_AUTH_MODE is
    ``enforce`` and no token is set, the server exits immediately with
    a clear error instead of accepting requests and failing at
    request time.
    """
    from clawstu.api.auth import validate_auth_on_startup

    validate_auth_on_startup()

    state = get_state()
    runner = build_scheduler_runner(state)
    app.state.scheduler = runner
    await runner.start()
    try:
        yield
    finally:
        await runner.stop()


_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _configure_cors(app: FastAPI) -> None:
    """Add CORS middleware with localhost + Chrome extension origins."""
    cors_origins_raw = os.environ.get("CLAW_STU_CORS_ORIGINS", "")
    if cors_origins_raw:
        cors_origins = [
            o.strip() for o in cors_origins_raw.split(",") if o.strip()
        ]
    else:
        cors_origins = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=r"^chrome-extension://[a-z]{32}$",
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


def _register_routes(app: FastAPI) -> None:
    """Attach all API routers to the app."""
    app.include_router(session.router)
    app.include_router(profile.router)
    app.include_router(admin.router)
    app.include_router(learners.router)
    app.include_router(quick.router)


def _mount_static(app: FastAPI) -> None:
    """Serve the static directory and the ``GET /`` web UI endpoint."""
    if _STATIC_DIR.is_dir():
        app.mount(
            "/static",
            StaticFiles(directory=str(_STATIC_DIR)),
            name="static",
        )

    @app.get("/", response_class=HTMLResponse)
    def web_ui() -> str:
        index = _STATIC_DIR / "index.html"
        return index.read_text(encoding="utf-8")


def _register_health_alias(app: FastAPI) -> None:
    """Add the root-level ``GET /health`` alias for ``/admin/health``."""

    @app.get("/health", response_model=admin.HealthResponse)
    def health_alias(
        request: Request,
        state: AppState = Depends(get_state),
    ) -> admin.HealthResponse:
        return admin.health(request=request, state=state)


# ── WebSocket helpers (STU-F2) ───────────────────────────────────────


async def _ws_receive_validated_json(
    websocket: WebSocket,
    rate_limiter: _WsRateLimiter,
) -> dict[str, object] | None:
    """Receive a JSON message with size + rate limit checks.

    Returns None if rate-limited or oversized (error already sent
    to the client).
    """
    import json

    raw = await websocket.receive_text()
    if len(raw.encode("utf-8")) > _WS_MAX_MESSAGE_SIZE:
        await websocket.send_json({
            "type": "error",
            "message": "message too large (max 4KB)",
        })
        return None
    if not rate_limiter.check():
        await websocket.send_json({
            "type": "error",
            "message": "rate limit exceeded (max 30/minute)",
        })
        return None
    result: dict[str, object] = json.loads(raw)
    return result


async def _ws_authenticate(websocket: WebSocket) -> bool:
    """Check the bearer token and accept the connection.

    Returns True if auth succeeded and the socket is accepted.
    Returns False after sending an error frame and closing the socket.
    """
    from clawstu.api.auth import validate_token

    token = websocket.query_params.get("token")
    if not validate_token(token):
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "message": "unauthorized",
        })
        await websocket.close(code=1008)
        return False

    await websocket.accept()
    return True


async def _ws_parse_onboard(
    websocket: WebSocket,
    rate_limiter: _WsRateLimiter,
) -> WsOnboardMessage | None:
    """Receive and validate the onboard message.

    Returns the parsed ``WsOnboardMessage``, or ``None`` if the
    connection should be closed (error already sent to client).
    """
    raw_data = await _ws_receive_validated_json(websocket, rate_limiter)
    if raw_data is None:
        await websocket.close()
        return None

    if raw_data.get("type") != "onboard":
        await websocket.send_json({
            "type": "error",
            "message": "Expected onboard message first.",
        })
        await websocket.close()
        return None

    try:
        return WsOnboardMessage.model_validate(raw_data)
    except ValidationError:
        await websocket.send_json({
            "type": "error",
            "message": "invalid message format",
        })
        await websocket.close()
        return None


def _ws_build_session(
    msg: WsOnboardMessage,
) -> tuple[LearnerProfile, Session, SessionRunner, ModelRouter, bool, str | None]:
    """Build session objects from a validated onboard message.

    Returns ``(profile, session, runner, router, degraded, reason)``.
    Synchronous except for topic-aware paths -- callers must handle
    the async ``onboard_with_topic`` branch separately.
    """
    from clawstu.engagement.session import SessionPhase, SessionRunner
    from clawstu.orchestrator.live_content import LiveContentGenerator
    from clawstu.profile.model import Domain

    domain = Domain(str(msg.domain)) if msg.domain is not None else Domain.OTHER

    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    live = LiveContentGenerator(router=router)
    runner = SessionRunner(live_content=live)

    prof, ws_sess = runner.onboard(
        learner_id=msg.name, age=msg.age, domain=domain, topic=msg.topic,
    )
    if ws_sess.phase == SessionPhase.CALIBRATING:
        runner.finish_calibration(prof, ws_sess)

    return prof, ws_sess, runner, router, False, None


def _ws_fallback_onboard(
    runner: SessionRunner,
    msg: WsOnboardMessage,
    domain: Domain,
) -> tuple[LearnerProfile, Session, str]:
    """Seed-library fallback when live provider is unreachable (STU-5).

    Tries the requested domain first; falls back to US_HISTORY if
    the domain has no seed pathways.  Returns (profile, session, reason).
    """
    from clawstu.profile.model import Domain

    reason = "provider unreachable, using seed library"
    try:
        prof, ws_sess = runner.onboard(
            learner_id=msg.name, age=msg.age,
            domain=domain, topic=msg.topic,
        )
    except ValueError:
        prof, ws_sess = runner.onboard(
            learner_id=msg.name, age=msg.age,
            domain=Domain.US_HISTORY, topic=msg.topic,
        )
        if domain != Domain.US_HISTORY:
            reason = (
                f"provider unreachable, using seed library; "
                f"domain changed from {domain.value} "
                f"to us_history (only seed domain available)"
            )
    return prof, ws_sess, reason


async def _ws_build_session_with_topic(
    msg: WsOnboardMessage,
) -> tuple[LearnerProfile, Session, SessionRunner, ModelRouter, bool, str | None]:
    """Build session with topic-aware live-content onboarding.

    Falls back to the seed-library path when the provider is
    unreachable (STU-5 degraded mode).
    """
    import httpx

    from clawstu.engagement.session import SessionPhase, SessionRunner
    from clawstu.orchestrator.live_content import (
        LiveContentGenerator,
        LiveGenerationError,
    )
    from clawstu.orchestrator.providers import ProviderError
    from clawstu.profile.model import Domain

    domain = Domain(str(msg.domain)) if msg.domain is not None else Domain.OTHER
    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    runner = SessionRunner(live_content=LiveContentGenerator(router=router))

    assert msg.topic is not None  # caller guarantees topic is set
    try:
        prof, ws_sess = await runner.onboard_with_topic(
            learner_id=msg.name, age=msg.age, domain=domain, topic=msg.topic,
        )
        degraded, reason = False, None
    except (
        ConnectionError, TimeoutError, httpx.HTTPError,
        ValueError, OSError, ProviderError, LiveGenerationError,
    ):
        degraded = True
        prof, ws_sess, reason = _ws_fallback_onboard(runner, msg, domain)

    if ws_sess.phase == SessionPhase.CALIBRATING:
        runner.finish_calibration(prof, ws_sess)

    return prof, ws_sess, runner, router, degraded, reason


async def _ws_handle_onboard(
    websocket: WebSocket,
    rate_limiter: _WsRateLimiter,
) -> tuple[LearnerProfile, Session, SessionRunner, ModelRouter] | None:
    """Orchestrate onboard: parse, build session, send setup message.

    Returns ``(profile, ws_session, runner, router)`` on success, or
    ``None`` if the connection should be closed.
    """
    from clawstu.orchestrator.task_kinds import TaskKind
    from clawstu.profile.model import Domain

    msg = await _ws_parse_onboard(websocket, rate_limiter)
    if msg is None:
        return None

    if msg.topic is not None:
        prof, ws_sess, runner, router, degraded, reason = (
            await _ws_build_session_with_topic(msg)
        )
    else:
        prof, ws_sess, runner, router, degraded, reason = (
            _ws_build_session(msg)
        )

    if degraded:
        await websocket.send_json({"type": "degraded", "reason": reason})

    domain = Domain(str(msg.domain)) if msg.domain is not None else Domain.OTHER
    provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    provider_name = type(provider).__name__.replace("Provider", "").lower()
    await websocket.send_json({
        "type": "setup",
        "topic": msg.topic or domain.value,
        "age_bracket": prof.age_bracket.value,
        "provider": f"{provider_name}/{model}",
    })

    return prof, ws_sess, runner, router


async def _ws_handle_crisis(
    websocket: WebSocket,
    ws_session: object,
    decision: object,
    gate: object,
) -> None:
    """Escalate a crisis: update phase and send crisis message."""
    from clawstu.engagement.session import SessionPhase

    ws_session.phase = SessionPhase.CRISIS_PAUSE  # type: ignore[attr-defined]
    assert decision.crisis_detection is not None  # type: ignore[attr-defined]
    resources = gate.escalation.resources(  # type: ignore[attr-defined]
        decision.crisis_detection,  # type: ignore[attr-defined]
    )
    await websocket.send_json({
        "type": "crisis",
        "resources": resources,
    })


async def _ws_send_summary(
    websocket: WebSocket,
    runner: object,
    profile_obj: object,
    ws_session: object,
    started_at: object,
) -> None:
    """Close the session and send a summary message."""
    from datetime import UTC, datetime

    runner.close(profile_obj, ws_session)  # type: ignore[attr-defined]
    elapsed = max(
        1,
        int(
            (datetime.now(UTC) - started_at).total_seconds() // 60  # type: ignore[operator]
        ),
    )
    await websocket.send_json({
        "type": "summary",
        "duration_minutes": elapsed,
        "blocks": ws_session.blocks_presented,  # type: ignore[attr-defined]
    })


async def _ws_run_teach_loop(
    websocket: WebSocket,
    runner: object,
    profile_obj: object,
    ws_session: object,
    gate: object,
    evaluator: object,
    rate_limiter: _WsRateLimiter,
) -> None:
    """Drive the teach/check loop until closing, crisis, or disconnect."""
    from clawstu.engagement.session import SessionPhase

    while True:
        directive = runner.next_directive(profile_obj, ws_session)  # type: ignore[attr-defined]

        if directive.phase in (SessionPhase.CLOSING, SessionPhase.CLOSED):
            break

        if directive.phase is SessionPhase.CRISIS_PAUSE:
            await websocket.send_json({
                "type": "crisis",
                "resources": directive.message or "Session paused.",
            })
            break

        if directive.block is not None:
            block = directive.block
            await websocket.send_json({
                "type": "block",
                "title": block.title,
                "body": block.body,
                "modality": block.modality.value,
                "minutes": block.estimated_minutes,
            })
            raw_msg = await _ws_receive_validated_json(
                websocket, rate_limiter,
            )
            if raw_msg is None or raw_msg.get("type") == "close":
                break

        if ws_session.phase is SessionPhase.CHECKING:  # type: ignore[attr-defined]
            should_break = await _ws_handle_check(
                websocket, runner, profile_obj, ws_session,
                gate, evaluator, rate_limiter,
            )
            if should_break:
                break


async def _ws_handle_check(
    websocket: WebSocket,
    runner: object,
    profile_obj: object,
    ws_session: object,
    gate: object,
    evaluator: object,
    rate_limiter: _WsRateLimiter,
) -> bool:
    """Handle a single check item.  Returns True if the loop should break."""
    check_item = runner.select_check(ws_session)  # type: ignore[attr-defined]
    await websocket.send_json({
        "type": "check",
        "prompt": check_item.prompt,
        "item_id": check_item.id,
    })

    raw_answer = await _ws_receive_validated_json(websocket, rate_limiter)
    if raw_answer is None or raw_answer.get("type") == "close":
        return True

    try:
        answer_validated = WsAnswerMessage.model_validate(raw_answer)
        answer_text = answer_validated.text
    except ValidationError:
        await websocket.send_json({
            "type": "error",
            "message": "invalid message format",
        })
        return True

    decision = gate.scan(answer_text)  # type: ignore[attr-defined]
    if decision.action == "crisis":
        await _ws_handle_crisis(websocket, ws_session, decision, gate)
        return True

    result = evaluator.evaluate(check_item, answer_text)  # type: ignore[attr-defined]
    runner.record_check(  # type: ignore[attr-defined]
        profile_obj, ws_session, check_item, result,
    )
    await websocket.send_json({
        "type": "feedback",
        "correct": result.correct,
        "text": result.notes or (
            "Correct!" if result.correct else "Not quite."
        ),
    })
    return False


# ── WebSocket endpoint ───────────────────────────────────────────────


async def _websocket_chat(websocket: WebSocket) -> None:
    """Full session lifecycle over a single WebSocket connection.

    Orchestrates auth -> onboard -> teach loop -> summary.
    See module docstring for the full JSON protocol.
    Rate-limited to 30 msg/min, max 4KB per message.
    """
    import contextlib
    from datetime import UTC, datetime

    from clawstu.assessment.evaluator import Evaluator
    from clawstu.safety.boundaries import BoundaryEnforcer
    from clawstu.safety.escalation import EscalationHandler
    from clawstu.safety.gate import InboundSafetyGate

    if not await _ws_authenticate(websocket):
        return

    rate_limiter = _WsRateLimiter()
    gate = InboundSafetyGate(EscalationHandler(), BoundaryEnforcer())
    evaluator = Evaluator()

    try:
        result = await _ws_handle_onboard(websocket, rate_limiter)
        if result is None:
            return
        prof, ws_session, runner, _router = result

        started_at = datetime.now(UTC)
        await _ws_run_teach_loop(
            websocket, runner, prof, ws_session,
            gate, evaluator, rate_limiter,
        )
        await _ws_send_summary(
            websocket, runner, prof, ws_session, started_at,
        )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        with contextlib.suppress(Exception):
            await websocket.send_json({
                "type": "error",
                "message": str(exc),
            })


# ── App factory ──────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Claw-STU",
        description="Stuart — a personal learning agent that grows with the student.",
        version=__version__,
        lifespan=lifespan,
    )

    _configure_cors(app)
    _register_routes(app)
    _mount_static(app)
    _register_health_alias(app)
    app.websocket("/ws/chat")(_websocket_chat)

    return app


app = create_app()
