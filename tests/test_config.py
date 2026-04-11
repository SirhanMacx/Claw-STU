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
    # Pin the actual shipped default rather than a loose range: the
    # validator allows up to 2.0, so a range check here would let a
    # future bump to 1.5 silently slip through.
    assert route.temperature == 0.2


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


def test_load_config_reads_env_var_api_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Env var keys populate AppConfig.

    Isolation note: we point CLAW_STU_DATA_DIR at tmp_path so this
    test does not accidentally read a real ~/.claw-stu/secrets.json
    when Task 7 adds file-based loading. Without this isolation, the
    test's result would depend on whatever is in the executor's home
    directory, which is neither deterministic nor safe.
    """
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-abc")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://anthropic.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-def")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.test/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-ghi")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.test/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-token")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:22222")
    monkeypatch.setenv("STU_PRIMARY_PROVIDER", "openrouter")

    cfg = load_config()
    # Every env var row in load_config's docstring must have a matching
    # assertion here, otherwise a typo in env_map can ship silently.
    assert cfg.anthropic_api_key == "sk-ant-test-abc"
    assert cfg.anthropic_base_url == "https://anthropic.test/v1"
    assert cfg.openai_api_key == "sk-test-def"
    assert cfg.openai_base_url == "https://openai.test/v1"
    assert cfg.openrouter_api_key == "sk-or-test-ghi"
    assert cfg.openrouter_base_url == "https://openrouter.test/v1"
    assert cfg.ollama_api_key == "ollama-token"
    assert cfg.ollama_base_url == "http://localhost:22222"
    assert cfg.primary_provider == "openrouter"


def test_load_config_falls_back_to_defaults_without_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    # Unset every env var load_config reads so ambient environment
    # cannot pollute this test. If load_config grows a new env row,
    # add it here too.
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OLLAMA_API_KEY",
        "OLLAMA_BASE_URL",
        "STU_PRIMARY_PROVIDER",
        "CLAW_STU_DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    cfg = load_config()
    assert cfg.anthropic_api_key is None
    assert cfg.openai_api_key is None
    assert cfg.openrouter_api_key is None
    assert cfg.ollama_api_key is None
    assert cfg.primary_provider == "ollama"  # default from AppConfig
    assert cfg.data_dir == tmp_path


def test_load_config_respects_claw_stu_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path / "custom"))
    cfg = load_config()
    assert cfg.data_dir == tmp_path / "custom"
