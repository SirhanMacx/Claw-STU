"""OpenAIProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import inspect
import json

import httpx
import pytest

from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def test_openai_complete_is_async() -> None:
    assert inspect.iscoroutinefunction(OpenAIProvider.complete), (
        "OpenAIProvider.complete must be declared `async def` per Phase 2"
    )


def _make_provider(
    transport: httpx.MockTransport,
    api_key: str = "sk-test",
) -> OpenAIProvider:
    client = httpx.AsyncClient(transport=transport)
    return OpenAIProvider(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        client=client,
    )


async def test_openai_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-abc",
                "object": "chat.completion",
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello back.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 4,
                    "total_tokens": 16,
                },
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = await provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hi?")],
        max_tokens=256,
        temperature=0.2,
        model="gpt-4o-mini",
    )
    assert isinstance(response, LLMResponse)
    assert response.text == "Hello back."
    assert response.provider == "openai"
    assert response.model == "gpt-4o-mini"
    assert response.finish_reason == "stop"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-test"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o-mini"
    assert body["max_tokens"] == 256
    # OpenAI puts the system prompt as the first message, not a
    # separate field. Verify the wire shape.
    assert body["messages"][0] == {
        "role": "system",
        "content": "You are Stuart.",
    }
    assert body["messages"][1] == {"role": "user", "content": "Hi?"}


def test_openai_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        OpenAIProvider(api_key=None)
    with pytest.raises(ValueError, match="api_key"):
        OpenAIProvider(api_key="")


async def test_openai_401_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            text='{"error":{"message":"invalid api key"}}',
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 401"):
        await provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


async def test_openai_empty_choices_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl",
                "object": "chat.completion",
                "model": "gpt-4o-mini",
                "choices": [],
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no choices"):
        await provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
