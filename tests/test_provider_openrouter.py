"""OpenRouterProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import json

import httpx
import pytest

from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def _make_provider(
    transport: httpx.MockTransport,
    api_key: str = "sk-or-test",
) -> OpenRouterProvider:
    client = httpx.Client(transport=transport)
    return OpenRouterProvider(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        client=client,
    )


def test_openrouter_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["authorization"] = request.headers.get("authorization")
        captured["http_referer"] = request.headers.get("http-referer")
        captured["x_title"] = request.headers.get("x-title")
        return httpx.Response(
            200,
            json={
                "id": "gen-abc",
                "object": "chat.completion",
                "model": "z-ai/glm-4.5-air",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from GLM.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hi?")],
        max_tokens=256,
        temperature=0.2,
    )
    assert isinstance(response, LLMResponse)
    assert response.text == "Hello from GLM."
    assert response.provider == "openrouter"
    assert response.model == "z-ai/glm-4.5-air"
    assert response.finish_reason == "stop"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-or-test"
    assert captured["http_referer"] == "https://github.com/SirhanMacx/Claw-STU"
    assert captured["x_title"] == "Claw-STU"
    body = captured["body"]
    assert isinstance(body, dict)
    # Default model used when caller omits `model` kwarg.
    assert body["model"] == "z-ai/glm-4.5-air"
    assert body["max_tokens"] == 256
    assert body["messages"][0] == {
        "role": "system",
        "content": "You are Stuart.",
    }
    assert body["messages"][1] == {"role": "user", "content": "Hi?"}


def test_openrouter_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        OpenRouterProvider(api_key=None)
    with pytest.raises(ValueError, match="api_key"):
        OpenRouterProvider(api_key="")


def test_openrouter_402_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            text='{"error":{"message":"insufficient credits"}}',
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 402"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_openrouter_empty_choices_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen",
                "object": "chat.completion",
                "model": "z-ai/glm-4.5-air",
                "choices": [],
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no choices"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
