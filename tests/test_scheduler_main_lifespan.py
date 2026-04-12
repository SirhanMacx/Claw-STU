"""Tests for the FastAPI lifespan + `/admin/scheduler` route.

The lifespan boots a `SchedulerRunner` on app startup and stops it on
shutdown. We do NOT call `await runner.start()` directly in the
test — the FastAPI `TestClient` enters and exits the lifespan as a
side effect of `with TestClient(app) as client:`, which is the only
sanctioned way to drive a real lifespan in tests.

The route tests verify:
1. After lifespan startup, `app.state.scheduler` is a `SchedulerRunner`.
2. `GET /admin/scheduler` returns the five task metadata rows and the
   five job ids loaded by the runner.
3. Recent runs land in the response after we manually invoke a task.
4. The "scheduler not initialized" 503 path fires when the route is
   called against an app that bypassed `create_app()` (and thus the
   lifespan).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clawstu.api.main import build_scheduler_runner, create_app, lifespan
from clawstu.api.state import AppState, get_state
from clawstu.scheduler.runner import SchedulerRunner


@pytest.fixture
def fresh_state() -> AppState:
    """Provide an isolated AppState for each test."""
    return AppState()


@pytest.fixture
def app_and_client(
    fresh_state: AppState,
) -> Iterator[tuple[FastAPI, TestClient]]:
    """Yield (app, client) inside an active lifespan.

    The TestClient is used as a context manager so anyio drives the
    lifespan's startup/shutdown. The FastAPI instance is yielded
    alongside so tests that need `app.state.scheduler` keep the
    static type instead of falling back to the loosely-typed
    `client.app` ASGI handle.
    """
    app = create_app()
    app.dependency_overrides[get_state] = lambda: fresh_state
    with TestClient(app) as test_client:
        yield app, test_client


class TestBuildSchedulerRunner:
    def test_returns_runner_with_five_jobs(
        self,
        fresh_state: AppState,
    ) -> None:
        runner = build_scheduler_runner(fresh_state)
        assert isinstance(runner, SchedulerRunner)
        ids = runner.get_job_ids()
        assert sorted(ids) == sorted(
            [
                "dream_cycle",
                "prepare_next_session",
                "spaced_review",
                "refresh_zpd",
                "prune_stale",
            ]
        )

    def test_runner_context_uses_state_persistence(
        self,
        fresh_state: AppState,
    ) -> None:
        runner = build_scheduler_runner(fresh_state)
        # The runner's context should reuse the AppState's persistence
        # store so scheduler runs land in the same database that the
        # rest of the API reads from.
        assert runner.context.persistence is fresh_state.persistence


class TestLifespanWiring:
    async def test_lifespan_context_manager_constructs_scheduler(self) -> None:
        """Calling the lifespan directly should yield without crashing."""
        app = FastAPI()
        async with lifespan(app):
            assert isinstance(app.state.scheduler, SchedulerRunner)
            assert len(app.state.scheduler.get_job_ids()) == 5

    async def test_lifespan_starts_and_stops_cleanly(self) -> None:
        """Enter and exit the lifespan; the runner should be stoppable."""
        app = FastAPI()
        async with lifespan(app):
            runner = app.state.scheduler
            assert isinstance(runner, SchedulerRunner)
        # After the lifespan exits the runner has been told to stop.
        # The scheduler attribute lingers on app.state — that's OK,
        # nothing reads it after shutdown.


class TestAdminSchedulerRoute:
    def test_returns_full_status_after_startup(
        self,
        app_and_client: tuple[FastAPI, TestClient],
    ) -> None:
        _app, client = app_and_client
        response = client.get("/admin/scheduler")
        assert response.status_code == 200
        body = response.json()
        assert "tasks" in body
        assert "job_ids" in body
        assert "recent_runs" in body
        assert len(body["tasks"]) == 5
        task_names = [t["name"] for t in body["tasks"]]
        assert sorted(task_names) == sorted(
            [
                "dream_cycle",
                "prepare_next_session",
                "spaced_review",
                "refresh_zpd",
                "prune_stale",
            ]
        )
        assert sorted(body["job_ids"]) == sorted(task_names)
        # All tasks ship enabled by default.
        assert all(t["enabled"] for t in body["tasks"])
        # No runs have happened yet.
        assert body["recent_runs"] == []

    def test_route_returns_503_when_scheduler_missing(self) -> None:
        """An app constructed without lifespan should return 503."""
        bare_app = FastAPI()
        # Mount only the admin router; never run the lifespan.
        from clawstu.api import admin

        bare_app.include_router(admin.router)
        with TestClient(bare_app) as bare_client:
            response = bare_client.get("/admin/scheduler")
            assert response.status_code == 503
            assert response.json()["detail"] == "scheduler not initialized"

    def test_recent_runs_serialize_when_persistence_already_has_rows(
        self,
        app_and_client: tuple[FastAPI, TestClient],
    ) -> None:
        # The manual-dispatch path is exercised by
        # tests/test_scheduler_runner.py::TestSchedulerRunnerDispatch.
        # Here we just verify the admin route serializes existing
        # SchedulerRunStore rows correctly. Insert a row directly via
        # the runner's persistence reference and read it back.
        app, client = app_and_client
        runner = app.state.scheduler
        assert isinstance(runner, SchedulerRunner)
        runner.context.persistence.scheduler_runs.append(
            task_name="dream_cycle",
            learner_id_hash="abc123abc123",
            outcome="success",
            duration_ms=42,
            token_cost_input=10,
            token_cost_output=20,
            error_message=None,
        )
        response = client.get("/admin/scheduler")
        assert response.status_code == 200
        body = response.json()
        assert len(body["recent_runs"]) == 1
        run = body["recent_runs"][0]
        assert run["task_name"] == "dream_cycle"
        assert run["learner_id_hash"] == "abc123abc123"
        assert run["outcome"] == "success"
        assert run["duration_ms"] == 42
        assert run["token_cost_input"] == 10
        assert run["token_cost_output"] == 20
        assert run["error_message"] is None


class TestProactiveContextProviderWiring:
    """Phase 8 Part 1: lifespan builds real providers from AppConfig."""

    def test_proactive_context_builds_real_providers_when_config_has_keys(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """When AppConfig has real API keys, the context's router is
        populated with the corresponding concrete providers -- not
        the deterministic Echo we used to ship in Phase 6.

        The router exposes its resolution map privately. Instead of
        reaching into ``_resolved`` we walk every TaskKind via the
        public ``for_task`` API and collect the resolved provider
        types. With Anthropic + OpenAI + OpenRouter + Ollama all
        present, the default routing table should never need to fall
        through to Echo for any kind.
        """
        monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-fake")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")

        from clawstu.api.main import _build_proactive_context
        from clawstu.api.state import AppState
        from clawstu.orchestrator.provider_anthropic import AnthropicProvider
        from clawstu.orchestrator.provider_ollama import OllamaProvider
        from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
        from clawstu.orchestrator.providers import EchoProvider
        from clawstu.orchestrator.task_kinds import TaskKind

        ctx = _build_proactive_context(AppState())
        provider_types: set[type] = set()
        for kind in TaskKind:
            provider, _model = ctx.router.for_task(kind)
            provider_types.add(type(provider))

        assert AnthropicProvider in provider_types, (
            f"missing Anthropic in resolved router: {provider_types}"
        )
        assert OpenRouterProvider in provider_types, (
            f"missing OpenRouter in resolved router: {provider_types}"
        )
        assert OllamaProvider in provider_types, (
            f"missing Ollama in resolved router: {provider_types}"
        )
        # With every key set, no TaskKind should fall through to Echo.
        assert EchoProvider not in provider_types, (
            f"Echo fell through unexpectedly -- a real provider was "
            f"missing for one of the TaskKinds. "
            f"Resolved types: {provider_types}"
        )

    def test_proactive_context_falls_through_to_ollama_with_partial_keys(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """With only OPENAI_API_KEY set, every TaskKind whose primary
        is openrouter or anthropic resolves through the fallback chain
        and lands on Ollama (the first chain entry that's always
        present in the providers dict). Echo never appears.

        This pins the contract that ``_build_providers`` always
        includes Ollama unconditionally and that the router's chain
        walking actually fires when a primary key is missing.
        """
        monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
        for key in (
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "OLLAMA_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-only")

        from clawstu.api.main import _build_proactive_context
        from clawstu.api.state import AppState
        from clawstu.orchestrator.provider_anthropic import AnthropicProvider
        from clawstu.orchestrator.provider_ollama import OllamaProvider
        from clawstu.orchestrator.provider_openai import OpenAIProvider
        from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
        from clawstu.orchestrator.providers import EchoProvider
        from clawstu.orchestrator.task_kinds import TaskKind

        ctx = _build_proactive_context(AppState())
        provider_types: set[type] = set()
        for kind in TaskKind:
            provider, _model = ctx.router.for_task(kind)
            provider_types.add(type(provider))

        # Anthropic and OpenRouter were never built, so they cannot
        # appear in the resolved router.
        assert AnthropicProvider not in provider_types
        assert OpenRouterProvider not in provider_types
        # Ollama is unconditionally present, so the fallback chain
        # lands there for every TaskKind whose primary was missing.
        assert OllamaProvider in provider_types
        # OpenAI was built but no TaskKind names it as primary (the
        # spec routing table picks anthropic/ollama/openrouter only),
        # so it does not appear in the resolved set even though it
        # was constructed.
        assert OpenAIProvider not in provider_types
        # Echo never resolves because Ollama is always present and
        # appears earlier in the fallback chain.
        assert EchoProvider not in provider_types
