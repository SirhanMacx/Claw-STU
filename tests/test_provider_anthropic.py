"""AnthropicProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import json

import httpx
import pytest

from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def _make_provider(
    transport: httpx.MockTransport,
    api_key: str = "sk-ant-test",
) -> AnthropicProvider:
    client = httpx.Client(transport=transport)
    return AnthropicProvider(
        api_key=api_key,
        base_url="https://api.anthropic.com",
        client=client,
    )


def test_anthropic_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["x-api-key"] = request.headers.get("x-api-key")
        captured["anthropic-version"] = request.headers.get("anthropic-version")
        return httpx.Response(
            200,
            json={
                "id": "msg_abc",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there."}],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.2,
        model="claude-haiku-4-5",
    )
    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.provider == "anthropic"
    assert response.model == "claude-haiku-4-5"
    assert response.finish_reason == "end_turn"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["x-api-key"] == "sk-ant-test"
    # Anthropic API version header is required.
    assert captured["anthropic-version"]
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 256
    assert body["system"] == "You are Stuart."
    assert body["messages"][0] == {"role": "user", "content": "Hello?"}


def test_anthropic_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        AnthropicProvider(api_key=None)
    with pytest.raises(ValueError, match="api_key"):
        AnthropicProvider(api_key="")


def test_anthropic_401_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            text='{"type":"error","error":{"type":"authentication_error"}}',
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 401"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_anthropic_extracts_first_text_block() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="sys",
        messages=[LLMMessage(role="user", content="hi")],
    )
    # Claw-STU expects a single concatenated text response. Anthropic may
    # emit multiple text blocks — we join them with a newline.
    assert response.text == "first\nsecond"


def test_anthropic_empty_content_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg",
                "content": [],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no text"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
