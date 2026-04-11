"""LLM provider abstraction.

Defines a minimal `LLMProvider` protocol that all concrete providers
(Anthropic, OpenAI, Ollama, etc.) implement. The MVP ships with a
deterministic `EchoProvider` that does not call a network. That
provider is enough to run the full session loop end-to-end in tests
and local development, and to let contributors iterate without API
keys.

Concrete network-backed providers live in separate modules (post-MVP)
and are loaded lazily so importing `src.orchestrator` never forces a
network dependency.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ProviderError(RuntimeError):
    """Raised when a provider call fails. Never swallowed."""


class LLMMessage(BaseModel):
    """A single message in an LLM conversation."""

    model_config = ConfigDict(frozen=True)

    role: str  # "system" | "user" | "assistant"
    content: str


class LLMResponse(BaseModel):
    """Response from an LLM provider."""

    model_config = ConfigDict(frozen=True)

    text: str
    provider: str
    model: str
    finish_reason: str = "stop"
    metadata: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every concrete provider must satisfy."""

    name: str

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Synchronous completion. Raises `ProviderError` on failure."""
        ...


class EchoProvider:
    """Deterministic, offline provider used in tests and local dev.

    It does not call a network. Given a system prompt and a message
    stream, it returns a response constructed from the last user
    message, prefixed with a visible `[echo]` marker so anyone who
    sees this output at runtime knows no real LLM was involved.

    This provider is also the reference implementation for the
    `LLMProvider` protocol — it shows exactly which fields of a real
    provider response the session loop depends on.
    """

    name = "echo"

    def __init__(self, *, model: str = "echo-0") -> None:
        self.model = model

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        if not messages:
            raise ProviderError("EchoProvider requires at least one message")
        last_user = next(
            (m for m in reversed(messages) if m.role == "user"),
            None,
        )
        if last_user is None:
            raise ProviderError("EchoProvider requires a 'user' message")
        reply = f"[echo] {last_user.content[:max_tokens]}"
        return LLMResponse(
            text=reply,
            provider=self.name,
            model=self.model,
            finish_reason="stop",
            metadata={
                "system_len": str(len(system)),
                "temperature": f"{temperature:.2f}",
            },
        )
