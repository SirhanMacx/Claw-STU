"""Tests for `clawstu.scheduler.registry`.

Covers `TaskRegistry` directly and `default_registry()` — the five
task SPECs the spec mandates under §4.7.5. Each SPEC's cron string is
parsed with `CronTrigger.from_crontab` so an invalid expression fails
loudly here rather than silently at scheduler-startup time.

Task-body behavior is covered in `test_scheduler_tasks.py`; this file
stops at the metadata layer.
"""

from __future__ import annotations

from typing import ClassVar

from apscheduler.triggers.cron import CronTrigger

from clawstu.scheduler.context import ProactiveContext
from clawstu.scheduler.registry import (
    TaskRegistry,
    TaskReport,
    TaskSpec,
    TokenCost,
    default_registry,
)


async def _dummy_run(ctx: ProactiveContext, learner_id: str) -> TaskReport:
    """Trivial task body used by the registry unit tests.

    Never actually called — we only need a callable that matches the
    `TaskRunFn` type to construct a `TaskSpec`.
    """
    return TaskReport(
        task_name="dummy",
        learner_id_hash=None,
        outcome="success",
        duration_ms=0,
    )


def _dummy_spec(name: str = "dummy", *, enabled: bool = True) -> TaskSpec:
    return TaskSpec(
        name=name,
        cron="0 0 * * *",
        enabled=enabled,
        description=f"dummy task {name}",
        run_fn=_dummy_run,
    )


class TestTaskRegistry:
    def test_registers_and_retrieves_by_name(self) -> None:
        registry = TaskRegistry()
        spec = _dummy_spec("alpha")
        registry.register(spec)
        assert registry.get("alpha") is spec
        assert registry.get("missing") is None

    def test_list_all_returns_every_registered_spec(self) -> None:
        registry = TaskRegistry()
        registry.register(_dummy_spec("alpha"))
        registry.register(_dummy_spec("beta"))
        names = [spec.name for spec in registry.list_all()]
        assert names == ["alpha", "beta"]

    def test_list_enabled_excludes_disabled_specs(self) -> None:
        registry = TaskRegistry()
        registry.register(_dummy_spec("alpha"))
        registry.register(_dummy_spec("beta", enabled=False))
        names = [spec.name for spec in registry.list_enabled()]
        assert names == ["alpha"]

    def test_register_overwrites_existing_spec_with_same_name(self) -> None:
        registry = TaskRegistry()
        registry.register(_dummy_spec("alpha"))
        replacement = _dummy_spec("alpha")
        registry.register(replacement)
        assert registry.get("alpha") is replacement
        assert len(registry.list_all()) == 1


class TestTaskReport:
    def test_defaults_produce_zero_token_cost(self) -> None:
        report = TaskReport(
            task_name="t",
            learner_id_hash=None,
            outcome="success",
            duration_ms=0,
        )
        assert report.token_cost == TokenCost()
        assert report.token_cost.input_tokens == 0
        assert report.token_cost.output_tokens == 0
        assert report.details == {}
        assert report.error_message is None

    def test_report_is_frozen(self) -> None:
        report = TaskReport(
            task_name="t",
            learner_id_hash="h",
            outcome="success",
            duration_ms=1,
        )
        # pydantic frozen models raise ValidationError on mutation
        import pydantic
        try:
            report.task_name = "other"  # type: ignore[misc]
        except pydantic.ValidationError:
            return
        raise AssertionError("expected ValidationError on frozen mutation")


class TestDefaultRegistry:
    _EXPECTED_NAMES: ClassVar[list[str]] = [
        "dream_cycle",
        "prepare_next_session",
        "spaced_review",
        "refresh_zpd",
        "prune_stale",
    ]

    def test_default_registry_has_five_tasks(self) -> None:
        registry = default_registry()
        names = [spec.name for spec in registry.list_all()]
        assert names == self._EXPECTED_NAMES

    def test_default_registry_specs_are_all_enabled(self) -> None:
        registry = default_registry()
        enabled = [spec.name for spec in registry.list_enabled()]
        assert enabled == self._EXPECTED_NAMES

    def test_default_registry_cron_strings_parse(self) -> None:
        registry = default_registry()
        for spec in registry.list_all():
            trigger = CronTrigger.from_crontab(spec.cron)
            assert isinstance(trigger, CronTrigger)

    def test_default_registry_crons_match_spec_table(self) -> None:
        registry = default_registry()
        expected = {
            "dream_cycle": "30 2 * * *",
            "prepare_next_session": "15 3 * * *",
            "spaced_review": "45 3 * * *",
            "refresh_zpd": "0 4 * * *",
            "prune_stale": "0 5 * * 0",
        }
        actual = {spec.name: spec.cron for spec in registry.list_all()}
        assert actual == expected
