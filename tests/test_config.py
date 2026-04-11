"""Tests for AppConfig, TaskRoute, and load_config."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from clawstu.orchestrator.config import (
    AppConfig,
    TaskRoute,
)
from clawstu.orchestrator.task_kinds import TaskKind


def test_task_route_is_frozen() -> None:
    route = TaskRoute(provider="ollama", model="llama3.2")
    with pytest.raises(ValidationError):
        route.provider = "anthropic"  # type: ignore[misc]


def test_task_route_defaults() -> None:
    route = TaskRoute(provider="ollama", model="llama3.2")
    assert route.max_tokens == 1024
    assert 0.0 <= route.temperature <= 1.0


def test_app_config_has_defaults_for_every_task_kind() -> None:
    cfg = AppConfig()
    for kind in TaskKind:
        assert kind in cfg.task_routing, f"missing default routing for {kind}"
        route = cfg.task_routing[kind]
        assert isinstance(route, TaskRoute)
        assert route.provider in (*cfg.fallback_chain, "echo"), (
            f"default routing for {kind} uses provider {route.provider!r} "
            f"which is not in fallback_chain {cfg.fallback_chain}"
        )


def test_app_config_default_data_dir_is_under_home() -> None:
    cfg = AppConfig()
    assert cfg.data_dir == Path.home() / ".claw-stu"


def test_app_config_default_primary_provider_is_ollama() -> None:
    cfg = AppConfig()
    assert cfg.primary_provider == "ollama"


def test_app_config_default_fallback_chain_ends_at_openrouter() -> None:
    cfg = AppConfig()
    assert cfg.fallback_chain == ("ollama", "openai", "anthropic", "openrouter")


def test_default_task_routing_matches_spec_table() -> None:
    """The §4.2.4 default routing table is the contract."""
    cfg = AppConfig()
    assert cfg.task_routing[TaskKind.SOCRATIC_DIALOGUE].provider == "ollama"
    assert cfg.task_routing[TaskKind.BLOCK_GENERATION].provider == "openrouter"
    assert cfg.task_routing[TaskKind.CHECK_GENERATION].provider == "openrouter"
    assert cfg.task_routing[TaskKind.RUBRIC_EVALUATION].provider == "anthropic"
    assert cfg.task_routing[TaskKind.PATHWAY_PLANNING].provider == "openrouter"
    assert cfg.task_routing[TaskKind.CONTENT_CLASSIFY].provider == "ollama"
    assert cfg.task_routing[TaskKind.DREAM_CONSOLIDATION].provider == "openrouter"
    # Model names per §4.2.4:
    assert cfg.task_routing[TaskKind.RUBRIC_EVALUATION].model == "claude-haiku-4-5"
    assert cfg.task_routing[TaskKind.BLOCK_GENERATION].model == "z-ai/glm-4.5-air"
