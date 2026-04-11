"""OpenRouter provider — aggregator for GLM, Mistral, Kimi, and many more.

OpenRouter is API-compatible with OpenAI's chat completions format, so
the wire shape is the same as OpenAIProvider. It adds two attribution
headers (HTTP-Referer, X-Title) that OpenRouter uses for its public
leaderboard; these are documented as recommended-not-required.

Endpoint: POST https://openrouter.ai/api/v1/chat/completions
Docs: https://openrouter.ai/docs

HEARTBEAT §3 compliance: same helper-extraction pattern as the
other providers. `complete()` stays under 50 lines.
"""
from __future__ import annotations

from typing import Any

import httpx

from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


class OpenRouterProvider:
    """LLMProvider for OpenRouter's Chat Completions API."""

    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://openrouter.ai/api/v1",
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        referer: str = "https://github.com/SirhanMacx/Claw-STU",
        x_title: str = "Claw-STU",
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouterProvider requires an api_key")
        self._api_key: str = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)
        self._referer = referer
        self._x_title = x_title

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        """POST to /chat/completions and return the parsed response."""
        effective_model = model or "z-ai/glm-4.5-air"
        payload = self._build_payload(
            system=system,
            messages=messages,
            model=effective_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = self._post(payload)
        return self._parse_body(body, model=effective_model)

    def _build_payload(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
        ]
        for msg in messages:
            wire_messages.append({"role": msg.role, "content": msg.content})
        return {
            "model": model,
            "messages": wire_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the payload and return the parsed JSON body.

        Raises ProviderError on network failure, non-2xx status, or
        non-JSON/non-object body. The body dict is returned unvalidated
        beyond the top-level shape; _parse_body handles field shape.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": self._referer,
            "X-Title": self._x_title,
        }
        try:
            http_response = self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"openrouter request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"openrouter returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            parsed = http_response.json()
        except ValueError as exc:
            raise ProviderError(
                f"openrouter returned non-JSON body: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"openrouter response body is not a JSON object: "
                f"{type(parsed).__name__}"
            )
        return parsed

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        choices_raw = body.get("choices")
        if not isinstance(choices_raw, list):
            raise ProviderError(
                f"openrouter response choices is not a list: "
                f"{type(choices_raw).__name__}"
            )
        if not choices_raw:
            raise ProviderError("openrouter response has no choices")
        first = choices_raw[0]
        if not isinstance(first, dict):
            raise ProviderError(
                f"openrouter response first choice is not an object: "
                f"{type(first).__name__}"
            )
        message_raw = first.get("message")
        if not isinstance(message_raw, dict):
            raise ProviderError(
                f"openrouter response first choice message is not an object: "
                f"{type(message_raw).__name__}"
            )
        text = message_raw.get("content", "")
        if not isinstance(text, str):
            raise ProviderError(
                f"openrouter choice.message.content is not a string: "
                f"{type(text).__name__}"
            )
        usage_raw = body.get("usage")
        usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=str(body.get("model", model)),
            finish_reason=str(first.get("finish_reason", "stop")),
            metadata={
                "prompt_tokens": str(usage.get("prompt_tokens", "")),
                "completion_tokens": str(usage.get("completion_tokens", "")),
            },
        )
