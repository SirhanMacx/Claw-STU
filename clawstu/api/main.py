"""FastAPI app entry point.

Run locally with:

    uvicorn clawstu.api.main:app --reload
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from clawstu import __version__
from clawstu.api import admin, learners, profile, session
from clawstu.api.state import AppState, get_state
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig, load_config
from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import default_registry
from clawstu.scheduler.runner import SchedulerRunner


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
    """
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
    app.include_router(session.router)
    app.include_router(profile.router)
    app.include_router(admin.router)
    app.include_router(learners.router)

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

    return app


app = create_app()
