"""OllamaProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import json

import httpx
import pytest

from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.providers import LLMMessage, LLMResponse, ProviderError


def _make_provider(transport: httpx.MockTransport) -> OllamaProvider:
    client = httpx.Client(transport=transport)
    return OllamaProvider(
        base_url="http://localhost:11434",
        api_key=None,
        client=client,
    )


def test_ollama_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "message": {"role": "assistant", "content": "Hi there."},
                "done": True,
                "total_duration": 123456,
                "eval_count": 42,
                "prompt_eval_count": 17,
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.3,
        model="llama3.2",
    )

    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.provider == "ollama"
    assert response.model == "llama3.2"
    assert response.finish_reason == "stop"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://localhost:11434/api/chat"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "llama3.2"
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0.3
    assert body["options"]["num_predict"] == 256
    assert body["messages"][0] == {"role": "system", "content": "You are Stuart."}
    assert body["messages"][1] == {"role": "user", "content": "Hello?"}


def test_ollama_500_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_connection_error_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="ollama request failed"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_non_json_body_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="non-JSON"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_missing_content_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": 123}})

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="not a string"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_with_api_key_sets_authorization_header() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"message": {"content": "ok"}, "model": "llama3.2"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OllamaProvider(
        base_url="http://localhost:11434",
        api_key="ollama-cloud-token",
        client=client,
    )
    provider.complete(
        system="sys",
        messages=[LLMMessage(role="user", content="hi")],
    )
    assert captured["authorization"] == "Bearer ollama-cloud-token"


def test_ollama_non_dict_body_raises_provider_error() -> None:
    """The _post guard against non-dict JSON bodies.

    Ollama should never return a top-level list/string, but if the
    endpoint is hijacked or misconfigured, the isinstance(parsed, dict)
    guard in _post raises rather than returning garbage.
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="not a JSON object"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_non_dict_message_raises_provider_error() -> None:
    """The _parse_body guard against non-dict `message` field.

    If Ollama ever returns `{"message": "some string"}` instead of
    `{"message": {"role": ..., "content": ...}}`, the isinstance
    guard in _parse_body raises instead of crashing at .get("content").
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "this should be a dict"})

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="message is not an object"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
