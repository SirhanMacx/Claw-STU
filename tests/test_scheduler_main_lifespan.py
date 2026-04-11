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
