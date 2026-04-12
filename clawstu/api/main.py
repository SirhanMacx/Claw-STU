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
from typing import Literal

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


def create_app() -> FastAPI:
    app = FastAPI(
        title="Claw-STU",
        description="Stuart — a personal learning agent that grows with the student.",
        version=__version__,
        lifespan=lifespan,
    )

    # ── CORS ────────────────────────────────────────────────────────
    # Supports localhost + Chrome extension origins.  Mirrors Claw-ED's
    # pattern (clawed/api/server.py) for cross-repo consistency.
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

    app.include_router(session.router)
    app.include_router(profile.router)
    app.include_router(admin.router)
    app.include_router(learners.router)
    app.include_router(quick.router)

    # ── Web UI ──────────────────────────────────────────────────────
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

    # ── Root-level /health alias ─────────────────────────────────────
    # README promises ``GET /health``; the canonical endpoint lives at
    # ``/admin/health``. This alias keeps both paths valid.
    @app.get("/health", response_model=admin.HealthResponse)
    def health_alias(
        request: Request,
        state: AppState = Depends(get_state),
    ) -> admin.HealthResponse:
        return admin.health(request=request, state=state)

    # ── WebSocket live sessions ───────────────────────────────────────
    @app.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket) -> None:
        """Full session lifecycle over a single WebSocket connection.

        Protocol (JSON):
        Client -> Server:
          {"type": "onboard", "name": "...", "age": N, "topic": "..."}
          {"type": "answer", "text": "..."}
          {"type": "ready"}
          {"type": "close"}
        Server -> Client:
          {"type": "setup", "topic": "...", "age_bracket": "...", "provider": "..."}
          {"type": "block", "title": "...", "body": "...", "modality": "...", "minutes": N}
          {"type": "check", "prompt": "...", "item_id": "..."}
          {"type": "feedback", "correct": bool, "text": "..."}
          {"type": "summary", "duration_minutes": N, "blocks": N}
          {"type": "error", "message": "..."}
          {"type": "degraded", "reason": "..."}
          {"type": "crisis", "resources": "..."}

        Auth: bearer token via ``?token=xxx`` query parameter. In dev
        mode with no token configured, connections are allowed without
        auth. Messages are rate-limited to 30/minute per connection and
        max 4KB per message.
        """
        import contextlib
        from datetime import UTC, datetime

        import httpx

        from clawstu.api.auth import validate_token
        from clawstu.assessment.evaluator import Evaluator
        from clawstu.engagement.session import SessionPhase, SessionRunner
        from clawstu.orchestrator.live_content import LiveContentGenerator, LiveGenerationError
        from clawstu.orchestrator.providers import ProviderError
        from clawstu.orchestrator.task_kinds import TaskKind
        from clawstu.profile.model import Domain
        from clawstu.safety.boundaries import BoundaryEnforcer
        from clawstu.safety.escalation import EscalationHandler
        from clawstu.safety.gate import InboundSafetyGate

        # ── Auth check (STU-1) ─────────────────────────────────────
        token = websocket.query_params.get("token")
        if not validate_token(token):
            # Must accept before sending a close frame with payload.
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "message": "unauthorized",
            })
            await websocket.close(code=1008)
            return

        await websocket.accept()

        rate_limiter = _WsRateLimiter()
        gate = InboundSafetyGate(EscalationHandler(), BoundaryEnforcer())
        evaluator = Evaluator()

        async def _receive_validated_json() -> dict[str, object] | None:
            """Receive a JSON message with size + rate limit checks.

            Returns None if rate-limited or oversized (error already
            sent to the client).
            """
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
            import json
            result: dict[str, object] = json.loads(raw)
            return result

        try:
            # 1. Wait for onboard message
            raw_data = await _receive_validated_json()
            if raw_data is None:
                await websocket.close()
                return

            if raw_data.get("type") != "onboard":
                await websocket.send_json({
                    "type": "error",
                    "message": "Expected onboard message first.",
                })
                await websocket.close()
                return

            # Validate through pydantic model (STU-7)
            try:
                onboard_msg = WsOnboardMessage.model_validate(raw_data)
            except ValidationError:
                await websocket.send_json({
                    "type": "error",
                    "message": "invalid message format",
                })
                await websocket.close()
                return

            name = onboard_msg.name
            age = onboard_msg.age
            topic = onboard_msg.topic
            domain_raw = onboard_msg.domain
            domain = Domain(str(domain_raw)) if domain_raw is not None else Domain.OTHER

            # Build session
            cfg = load_config()
            providers = build_providers(cfg)
            router = ModelRouter(config=cfg, providers=providers)
            live = LiveContentGenerator(router=router)
            runner = SessionRunner(live_content=live)

            degraded = False
            degraded_reason: str | None = None
            original_domain = domain

            if topic is not None:
                # Topic-aware path: live-content onboarding.  If the
                # provider is unreachable (e.g. no Ollama daemon in
                # tests), fall back to the sync path so the session
                # still starts.  The fallback uses US_HISTORY because
                # it is the only domain with seed pathways in the
                # deterministic content library.
                try:
                    profile, ws_session = await runner.onboard_with_topic(
                        learner_id=name,
                        age=age,
                        domain=domain,
                        topic=topic,
                    )
                except (ConnectionError, TimeoutError, httpx.HTTPError, ValueError, OSError, ProviderError, LiveGenerationError):
                    # Provider unreachable — fall back to the sync
                    # seed-library path.  Flag as degraded (STU-5).
                    degraded = True
                    degraded_reason = "provider unreachable, using seed library"
                    try:
                        profile, ws_session = runner.onboard(
                            learner_id=name,
                            age=age,
                            domain=domain,
                            topic=topic,
                        )
                    except ValueError:
                        profile, ws_session = runner.onboard(
                            learner_id=name,
                            age=age,
                            domain=Domain.US_HISTORY,
                            topic=topic,
                        )
                        if domain != Domain.US_HISTORY:
                            degraded_reason = (
                                f"provider unreachable, using seed library; "
                                f"domain changed from {original_domain.value} "
                                f"to us_history (only seed domain available)"
                            )
                    if ws_session.phase == SessionPhase.CALIBRATING:
                        runner.finish_calibration(profile, ws_session)
            else:
                # No topic: deterministic seed-library path.
                profile, ws_session = runner.onboard(
                    learner_id=name,
                    age=age,
                    domain=domain,
                )
                # Skip calibration for the WebSocket path — go
                # straight to teaching so the client gets blocks.
                if ws_session.phase == SessionPhase.CALIBRATING:
                    runner.finish_calibration(profile, ws_session)

            provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
            provider_name = type(provider).__name__.replace("Provider", "").lower()

            # Send degraded notice before setup if applicable (STU-5)
            if degraded:
                await websocket.send_json({
                    "type": "degraded",
                    "reason": degraded_reason,
                })

            await websocket.send_json({
                "type": "setup",
                "topic": topic or domain.value,
                "age_bracket": profile.age_bracket.value,
                "provider": f"{provider_name}/{model}",
            })

            # 2. Teach loop
            started_at = datetime.now(UTC)
            while True:
                directive = runner.next_directive(profile, ws_session)

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

                    # Wait for "ready" or "answer"
                    raw_msg = await _receive_validated_json()
                    if raw_msg is None:
                        break
                    if raw_msg.get("type") == "close":
                        break

                if ws_session.phase is SessionPhase.CHECKING:
                    check_item = runner.select_check(ws_session)
                    await websocket.send_json({
                        "type": "check",
                        "prompt": check_item.prompt,
                        "item_id": check_item.id,
                    })

                    raw_answer = await _receive_validated_json()
                    if raw_answer is None:
                        break
                    if raw_answer.get("type") == "close":
                        break

                    # Validate answer message (STU-7)
                    try:
                        answer_validated = WsAnswerMessage.model_validate(raw_answer)
                        answer_text = answer_validated.text
                    except ValidationError:
                        await websocket.send_json({
                            "type": "error",
                            "message": "invalid message format",
                        })
                        break

                    decision = gate.scan(answer_text)
                    if decision.action == "crisis":
                        ws_session.phase = SessionPhase.CRISIS_PAUSE
                        assert decision.crisis_detection is not None
                        resources = gate.escalation.resources(
                            decision.crisis_detection
                        )
                        await websocket.send_json({
                            "type": "crisis",
                            "resources": resources,
                        })
                        break

                    result = evaluator.evaluate(check_item, answer_text)
                    runner.record_check(
                        profile, ws_session, check_item, result,
                    )
                    await websocket.send_json({
                        "type": "feedback",
                        "correct": result.correct,
                        "text": result.notes or (
                            "Correct!" if result.correct else "Not quite."
                        ),
                    })

            # 3. Send summary
            runner.close(profile, ws_session)
            elapsed = max(
                1,
                int(
                    (datetime.now(UTC) - started_at).total_seconds() // 60
                ),
            )
            await websocket.send_json({
                "type": "summary",
                "duration_minutes": elapsed,
                "blocks": ws_session.blocks_presented,
            })
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            with contextlib.suppress(Exception):
                await websocket.send_json({
                    "type": "error",
                    "message": str(exc),
                })

    return app


app = create_app()
