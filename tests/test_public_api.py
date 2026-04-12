"""Public-import-surface regression tests.

Every symbol that downstream `pip install clawstu` users are
expected to import from `clawstu.orchestrator` or any other
top-level package must be covered here. A missing export is a
release-blocking bug because it turns the public API into a
moving target — v0.1.0 shipped without `ModelRouter` exported
even though it was documented in the landing page, and a user
following that docs path would hit ImportError on their first
try. This test prevents that from happening again.

Rule of thumb: if a symbol is in `__all__`, it must also be in
this test. Any symbol a Phase N task was supposed to "export from
__init__" must also be in this test.
"""
from __future__ import annotations


def test_orchestrator_public_surface_is_stable() -> None:
    """Every Phase 1-2 orchestrator symbol importable from the package root.

    Groups below match the phase that introduced each symbol so a
    future reviewer can quickly see what's load-bearing from where:
    the first group is Phase 1 (config + 5 concrete providers +
    prompts + reasoning chain), the second group is Phase 2 (router
    + live-content relocation).
    """
    from clawstu.orchestrator import (  # noqa: F401
        AnthropicProvider,
        AppConfig,
        EchoProvider,
        GoogleProvider,
        LiveContentGenerator,
        LiveGenerationError,
        LLMMessage,
        LLMProvider,
        LLMResponse,
        ModelRouter,
        OllamaProvider,
        OpenAIProvider,
        OpenRouterProvider,
        PromptLibrary,
        ProviderError,
        ReasoningChain,
        RouterConstructionError,
        TaskKind,
        TaskRoute,
        ensure_data_dir,
        load_config,
    )


def test_orchestrator_dunder_all_matches_actual_exports() -> None:
    """`__all__` must list every symbol this test imports. If someone
    adds a new symbol to the module but forgets `__all__`, this fails."""
    import clawstu.orchestrator as orch

    expected = {
        "AnthropicProvider",
        "AppConfig",
        "EchoProvider",
        "GoogleProvider",
        "LLMMessage",
        "LLMProvider",
        "LLMResponse",
        "LiveContentGenerator",
        "LiveGenerationError",
        "ModelRouter",
        "OllamaProvider",
        "OpenAIProvider",
        "OpenRouterProvider",
        "PromptLibrary",
        "ProviderError",
        "ReasoningChain",
        "RouterConstructionError",
        "TaskKind",
        "TaskRoute",
        "ensure_data_dir",
        "load_config",
    }
    actual = set(orch.__all__)
    missing = expected - actual
    extra = actual - expected
    assert not missing, f"__all__ is missing: {sorted(missing)}"
    assert not extra, (
        f"__all__ has extras not covered by this test: {sorted(extra)}. "
        f"Add them to the expected set above so regressions stay loud."
    )


def test_model_router_is_constructible_from_public_import() -> None:
    """End-to-end: construct a ModelRouter from the public surface.

    This is the exact code path a downstream user would follow after
    `pip install clawstu`. If anything in the import chain is broken,
    this test fails — which is how we know v0.1.0's missing export
    won't silently recur.
    """
    from clawstu.orchestrator import (
        AppConfig,
        EchoProvider,
        LLMProvider,
        ModelRouter,
        TaskKind,
    )

    config = AppConfig()
    providers: dict[str, LLMProvider] = {"echo": EchoProvider()}
    router = ModelRouter(config=config, providers=providers)
    provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    assert provider is not None
    assert isinstance(model, str) and model
