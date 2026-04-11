"""Orchestrator tests."""

from __future__ import annotations

import pytest

from src.orchestrator.chain import ReasoningChain
from src.orchestrator.prompts import PromptLibrary
from src.orchestrator.providers import (
    EchoProvider,
    LLMMessage,
    ProviderError,
)


class TestEchoProvider:
    def test_returns_echo_of_last_user_message(self) -> None:
        provider = EchoProvider()
        response = provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hello")],
        )
        assert response.text.startswith("[echo]")
        assert "hello" in response.text
        assert response.provider == "echo"

    def test_requires_user_message(self) -> None:
        provider = EchoProvider()
        with pytest.raises(ProviderError):
            provider.complete(system="sys", messages=[])


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
    def test_chain_runs_template_and_returns_text(self) -> None:
        chain = ReasoningChain(provider=EchoProvider())
        out = chain.run_template(
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

    def test_chain_rewrites_outbound_sycophancy(self) -> None:
        class SycophantProvider:
            name = "sycophant"

            def complete(
                self,
                *,
                system: str,
                messages: list[LLMMessage],
                max_tokens: int = 1024,
                temperature: float = 0.2,
            ) -> object:
                from src.orchestrator.providers import LLMResponse

                return LLMResponse(
                    text="Great question! You're so smart.",
                    provider=self.name,
                    model="sycophant-0",
                )

        chain = ReasoningChain(provider=SycophantProvider())
        out = chain.ask("anything")
        assert "great question" not in out.lower()
        assert "smart" not in out.lower()
