"""GoogleProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import inspect
import json

import httpx
import pytest

from clawstu.orchestrator.provider_google import GoogleProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def test_google_complete_is_async() -> None:
    assert inspect.iscoroutinefunction(GoogleProvider.complete), (
        "GoogleProvider.complete must be declared `async def`"
    )


def _make_provider(
    transport: httpx.MockTransport,
    api_key: str = "AIza-test-key",
) -> GoogleProvider:
    client = httpx.AsyncClient(transport=transport)
    return GoogleProvider(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        client=client,
    )


async def test_google_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["x-goog-api-key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Hi there."}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 3,
                },
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = await provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.2,
        model="gemini-2.0-flash",
    )
    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.provider == "google"
    assert response.model == "gemini-2.0-flash"
    assert response.finish_reason == "stop"
    assert (
        captured["url"]
        == "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-2.0-flash:generateContent"
    )
    assert captured["x-goog-api-key"] == "AIza-test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["generationConfig"]["maxOutputTokens"] == 256
    assert body["systemInstruction"] == {"parts": [{"text": "You are Stuart."}]}
    assert body["contents"][0] == {
        "role": "user",
        "parts": [{"text": "Hello?"}],
    }


def test_google_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        GoogleProvider(api_key=None)
    with pytest.raises(ValueError, match="api_key"):
        GoogleProvider(api_key="")


async def test_google_401_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            text='{"error":{"code":401,"message":"API key not valid."}}',
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 401"):
        await provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


async def test_google_empty_candidates_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": []},
        )

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no candidates"):
        await provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


async def test_google_extracts_first_text_part() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "first"},
                                {"text": "second"},
                            ],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                    }
                ],
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = await provider.complete(
        system="sys",
        messages=[LLMMessage(role="user", content="hi")],
    )
    assert response.text == "first\nsecond"


async def test_google_with_system_instruction() -> None:
    """Verify systemInstruction is sent as a separate top-level field."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "ok"}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                    }
                ],
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    await provider.complete(
        system="Be helpful.",
        messages=[LLMMessage(role="user", content="hi")],
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["systemInstruction"] == {"parts": [{"text": "Be helpful."}]}
    # System prompt should NOT appear in contents
    for entry in body["contents"]:
        assert isinstance(entry, dict)
        for part in entry["parts"]:
            assert isinstance(part, dict)
            assert part.get("text") != "Be helpful."


async def test_google_non_dict_body_raises() -> None:
    """A response body that is not a JSON object raises ProviderError."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'"just a string"')

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="not a JSON object"):
        await provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
