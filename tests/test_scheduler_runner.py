"""Tests for `clawstu.scheduler.runner.SchedulerRunner`.

The runner is a thin wrapper around APScheduler's `AsyncIOScheduler`,
so these tests do NOT call `start()` (that would spawn a background
event loop the test does not own). Instead they construct a runner
with a fabricated registry, read `get_job_ids()`, and assert the
registry-to-jobs translation matches expectations.

The dispatch path (`_run_spec` -> persist) is exercised by calling
`_run_spec` directly, which lets us verify that:
  - a known task name yields a recorded SchedulerRunStore row;
  - an unknown task name short-circuits without recording.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import (
    TaskRegistry,
    TaskReport,
    TaskSpec,
    default_registry,
)
from clawstu.scheduler.runner import SchedulerRunner


def _router() -> ModelRouter:
    providers: dict[str, LLMProvider] = {"echo": EchoProvider()}
    return ModelRouter(config=AppConfig(), providers=providers)


@pytest.fixture
def context(tmp_path: Path) -> ProactiveContext:
    return ProactiveContext(
        router=_router(),
        brain_store=BrainStore(tmp_path / "brain"),
        persistence=InMemoryPersistentStore(),
    )


def _trivial_spec(name: str = "trivial", *, enabled: bool = True) -> TaskSpec:
    """Build a TaskSpec whose run_fn echoes the spec's own name.

    Defining the run_fn inside the factory closes over `name` so the
    recorded `TaskReport.task_name` matches the SPEC name. This lets
    `test_run_spec_records_report_in_persistence` assert against an
    explicit value.
    """
    async def _run(ctx: ProactiveContext, learner_id: str) -> TaskReport:
        return TaskReport(
            task_name=name,
            learner_id_hash=None,
            outcome="success",
            duration_ms=1,
        )

    return TaskSpec(
        name=name,
        cron="0 0 * * *",
        enabled=enabled,
        description=f"trivial test task {name}",
        run_fn=_run,
    )


class TestSchedulerRunnerJobLoading:
    def test_loads_all_enabled_tasks_from_default_registry(
        self,
        context: ProactiveContext,
    ) -> None:
        runner = SchedulerRunner(registry=default_registry(), context=context)
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

    def test_disabled_tasks_are_not_scheduled(
        self,
        context: ProactiveContext,
    ) -> None:
        registry = TaskRegistry()
        registry.register(_trivial_spec("alpha"))
        registry.register(_trivial_spec("beta", enabled=False))
        runner = SchedulerRunner(registry=registry, context=context)
        ids = runner.get_job_ids()
        assert ids == ["alpha"]

    def test_runner_exposes_registry_and_context(
        self,
        context: ProactiveContext,
    ) -> None:
        registry = TaskRegistry()
        registry.register(_trivial_spec("alpha"))
        runner = SchedulerRunner(registry=registry, context=context)
        assert runner.registry is registry
        assert runner.context is context

    def test_empty_registry_yields_no_jobs(
        self,
        context: ProactiveContext,
    ) -> None:
        runner = SchedulerRunner(registry=TaskRegistry(), context=context)
        assert runner.get_job_ids() == []


class TestSchedulerRunnerDispatch:
    async def test_run_spec_records_report_in_persistence(
        self,
        context: ProactiveContext,
    ) -> None:
        registry = TaskRegistry()
        registry.register(_trivial_spec("alpha"))
        runner = SchedulerRunner(registry=registry, context=context)
        await runner._run_spec("alpha")
        runs = context.persistence.scheduler_runs.list_recent()
        assert len(runs) == 1
        assert runs[0]["task_name"] == "alpha"
        assert runs[0]["outcome"] == "success"
        assert runs[0]["duration_ms"] == 1

    async def test_run_spec_with_unknown_name_records_nothing(
        self,
        context: ProactiveContext,
    ) -> None:
        runner = SchedulerRunner(registry=TaskRegistry(), context=context)
        await runner._run_spec("ghost")
        runs = context.persistence.scheduler_runs.list_recent()
        assert runs == []

    async def test_stop_is_safe_when_scheduler_never_started(
        self,
        context: ProactiveContext,
    ) -> None:
        runner = SchedulerRunner(registry=TaskRegistry(), context=context)
        # Should not raise even though .start() was never called.
        await runner.stop()
