"""OllamaProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import json

import httpx

from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.providers import LLMMessage, LLMResponse


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
