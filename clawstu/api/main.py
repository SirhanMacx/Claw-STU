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

from clawstu import __version__
from clawstu.api import admin, profile, session
from clawstu.api.state import AppState, get_state
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import default_registry
from clawstu.scheduler.runner import SchedulerRunner


def _build_proactive_context(state: AppState) -> ProactiveContext:
    """Construct the `ProactiveContext` the scheduler runs against.

    The router is built from a `ModelRouter` over an `EchoProvider`
    floor — the production `load_config()`-driven router lands later;
    for now we ship a deterministic offline default that the
    scheduler tasks can call without a network. The brain store is
    taken from `AppState` if configured, otherwise a tmp directory
    is created so the dream cycle has a real BrainStore to walk.
    """
    providers: dict[str, LLMProvider] = {"echo": EchoProvider()}
    router = ModelRouter(config=AppConfig(), providers=providers)
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
    return app


app = create_app()
