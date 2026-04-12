"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

from clawstu.api.rate_limit import reset_rate_state
from clawstu.engagement.session import Session, SessionRunner
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import Domain, LearnerProfile

# Default auth mode is now "generate" — tests need "dev" to avoid
# requiring tokens on every HTTP request.
os.environ.setdefault("STU_AUTH_MODE", "dev")


@pytest.fixture(autouse=True)
def _clear_rate_limits() -> None:
    """Reset the in-memory rate limiter before every test."""
    reset_rate_state()


@pytest.fixture
def runner() -> SessionRunner:
    return SessionRunner()


@pytest.fixture
def in_memory_store() -> InMemoryPersistentStore:
    """Fresh dict-backed persistent store for tests that need one."""
    return InMemoryPersistentStore()


@pytest.fixture
def onboarded(runner: SessionRunner) -> tuple[LearnerProfile, Session]:
    profile, session = runner.onboard(
        learner_id="test-learner",
        age=15,
        domain=Domain.US_HISTORY,
    )
    return profile, session


def async_router_for_testing(
    provider: LLMProvider | None = None,
) -> ModelRouter:
    """One-liner router wrapping a single provider.

    Every task in the routing table resolves to the same provider,
    because the fallback chain collapses to echo. This is exactly
    what a test that used to say `provider=EchoProvider()` wants.

    Callers pass an EchoProvider (or any async LLMProvider) and get
    back a ModelRouter they can drop into ReasoningChain or
    LiveContentGenerator.
    """
    echo = provider if isinstance(provider, EchoProvider) else EchoProvider()
    providers: dict[str, LLMProvider] = {"echo": echo}
    if provider is not None and not isinstance(provider, EchoProvider):
        # Register the custom provider under its `name` attribute so
        # callers who want the router to route to a specific stub
        # (e.g., SycophantProvider) can override the fallback chain
        # and get the stub via for_task().
        providers[provider.name] = provider
    return ModelRouter(config=AppConfig(), providers=providers)
