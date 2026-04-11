"""Orchestrator tests."""

from __future__ import annotations

import inspect

import pytest

from clawstu.orchestrator.chain import ReasoningChain
from clawstu.orchestrator.config import AppConfig, TaskRoute
from clawstu.orchestrator.prompts import PromptLibrary
from clawstu.orchestrator.providers import (
    EchoProvider,
    LLMMessage,
    LLMResponse,
    ProviderError,
)
from clawstu.orchestrator.router import ModelRouter
from clawstu.orchestrator.task_kinds import TaskKind
from tests.conftest import async_router_for_testing


class TestEchoProvider:
    async def test_returns_echo_of_last_user_message(self) -> None:
        provider = EchoProvider()
        response = await provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hello")],
        )
        assert response.text.startswith("[echo]")
        assert "hello" in response.text
        assert response.provider == "echo"

    async def test_requires_user_message(self) -> None:
        provider = EchoProvider()
        with pytest.raises(ProviderError):
            await provider.complete(system="sys", messages=[])


class TestPromptLibrary:
    def test_soul_system_is_present(self) -> None:
        library = PromptLibrary()
        system = library.soul_system()
        assert "Stuart" in system
        assert "friend" in system.lower() or "not" in system.lower()

    def test_unknown_template_raises(self) -> None:
        library = PromptLibrary()
        with pytest.raises(KeyError):
            library.get("does_not_exist")

    def test_template_rendering(self) -> None:
        library = PromptLibrary()
        rendered = library.get("socratic_continuation").render(
            concept="revolution",
            tier="meeting",
            student_utterance="because they wanted freedom",
        )
        assert "revolution" in rendered


class TestReasoningChain:
    async def test_chain_runs_template_and_returns_text(self) -> None:
        chain = ReasoningChain(router=async_router_for_testing())
        out = await chain.run_template(
            "socratic_continuation",
            user_input="",
            template_vars={
                "concept": "c",
                "tier": "meeting",
                "student_utterance": "because",
            },
        )
        assert isinstance(out, str)
        assert out != ""

    async def test_chain_rewrites_outbound_sycophancy(self) -> None:
        class SycophantProvider:
            name = "sycophant"

            async def complete(
                self,
                *,
                system: str,
                messages: list[LLMMessage],
                max_tokens: int = 1024,
                temperature: float = 0.2,
                model: str | None = None,
            ) -> LLMResponse:
                return LLMResponse(
                    text="Great question! You're so smart.",
                    provider=self.name,
                    model="sycophant-0",
                )

        defaults = AppConfig().task_routing
        cfg = AppConfig(
            task_routing={
                **defaults,
                TaskKind.SOCRATIC_DIALOGUE: TaskRoute(
                    provider="sycophant", model="sycophant-0"
                ),
            },
            fallback_chain=("sycophant", "echo"),
        )
        router = ModelRouter(
            config=cfg,
            providers={"sycophant": SycophantProvider(), "echo": EchoProvider()},
        )

        chain = ReasoningChain(router=router)
        out = await chain.ask("anything")
        assert "great question" not in out.lower()
        assert "smart" not in out.lower()

    async def test_chain_accepts_router_argument(self) -> None:
        """Phase 2: ReasoningChain(router=...) is the new construction form."""
        chain = ReasoningChain(router=async_router_for_testing())
        out = await chain.run_template(
            "socratic_continuation",
            user_input="",
            template_vars={
                "concept": "c",
                "tier": "meeting",
                "student_utterance": "because",
            },
        )
        assert isinstance(out, str) and out


class TestAsyncProtocol:
    """The LLMProvider.complete method must be declared async.

    Phase 2 hard contract (spec §4.2.1.a): every provider call is
    awaited, so both the Protocol and every concrete provider must
    declare `async def complete`. This test pins the contract against
    future regressions.
    """

    def test_echo_provider_complete_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(EchoProvider.complete), (
            "EchoProvider.complete must be declared `async def` "
            "per spec §4.2.1.a"
        )
