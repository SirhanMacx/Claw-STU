"""ModelRouter — per-TaskKind resolution + fallback chain tests."""
from __future__ import annotations

import pytest

from clawstu.orchestrator.config import AppConfig, TaskRoute
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter, RouterConstructionError
from clawstu.orchestrator.task_kinds import TaskKind


def _echo() -> EchoProvider:
    return EchoProvider()


def test_router_resolves_every_task_to_a_provider() -> None:
    """Every TaskKind must resolve to some (provider, model)."""
    cfg = AppConfig()
    providers: dict[str, LLMProvider] = {"echo": _echo()}
    router = ModelRouter(config=cfg, providers=providers)
    for kind in TaskKind:
        provider, model = router.for_task(kind)
        assert provider is not None
        assert isinstance(model, str) and model


def test_router_prefers_primary_provider_when_available() -> None:
    """If ollama is configured and available, SOCRATIC_DIALOGUE goes there."""
    cfg = AppConfig()  # primary_provider="ollama" by default
    ollama = _echo()  # stand-in for an OllamaProvider
    providers: dict[str, LLMProvider] = {
        "ollama": ollama,
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    assert provider is ollama
    assert model == "llama3.2"  # from _default_task_routing()


def test_router_falls_through_when_primary_missing() -> None:
    """If ollama is not in providers, SOCRATIC falls through to the next
    provider in the fallback_chain that IS in providers."""
    cfg = AppConfig()  # fallback chain: ollama -> openai -> anthropic -> openrouter
    openai_provider = _echo()
    providers: dict[str, LLMProvider] = {
        "openai": openai_provider,
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    provider, _model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    assert provider is openai_provider


def test_router_falls_through_to_echo_as_last_resort() -> None:
    """If none of the fallback_chain providers are available, echo is
    the guaranteed last-resort floor."""
    cfg = AppConfig()
    echo = _echo()
    providers: dict[str, LLMProvider] = {"echo": echo}
    router = ModelRouter(config=cfg, providers=providers)
    provider, _model = router.for_task(TaskKind.BLOCK_GENERATION)
    assert provider is echo


def test_router_raises_when_no_provider_at_all() -> None:
    """If neither any fallback provider nor echo is provided, the
    router refuses to construct — an empty router is always a bug."""
    cfg = AppConfig()
    with pytest.raises(RouterConstructionError, match="echo"):
        ModelRouter(config=cfg, providers={})


def test_router_uses_task_model_not_provider_default() -> None:
    """The model returned by for_task comes from AppConfig.task_routing,
    NOT from the provider's own default."""
    cfg = AppConfig()
    providers: dict[str, LLMProvider] = {
        "openrouter": _echo(),
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    _provider, model = router.for_task(TaskKind.BLOCK_GENERATION)
    assert model == "z-ai/glm-4.5-air"  # from spec §4.2.4


def test_router_honors_custom_task_routing_override() -> None:
    """If AppConfig.task_routing is overridden, the router respects it."""
    cfg = AppConfig(
        task_routing={
            **AppConfig().task_routing,
            TaskKind.SOCRATIC_DIALOGUE: TaskRoute(
                provider="openai",
                model="gpt-4o-mini",
            ),
        },
    )
    providers: dict[str, LLMProvider] = {
        "openai": _echo(),
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    _provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    assert model == "gpt-4o-mini"
