"""OpenAI provider via the Chat Completions API.

Endpoint: POST https://api.openai.com/v1/chat/completions
Docs: https://platform.openai.com/docs/api-reference/chat

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


class OpenAIProvider:
    """LLMProvider for OpenAI's Chat Completions API."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIProvider requires an api_key")
        self._api_key: str = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        """POST to /chat/completions and return the parsed response."""
        effective_model = model or "gpt-4o-mini"
        payload = self._build_payload(
            system=system,
            messages=messages,
            model=effective_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = await self._post(payload)
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

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the payload and return the parsed JSON body.

        Raises ProviderError on network failure, non-2xx status, or
        non-JSON/non-object body. The body dict is returned unvalidated
        beyond the top-level shape; _parse_body handles field shape.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        try:
            http_response = await self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"openai returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            parsed = http_response.json()
        except ValueError as exc:
            raise ProviderError(
                f"openai returned non-JSON body: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"openai response body is not a JSON object: "
                f"{type(parsed).__name__}"
            )
        return parsed

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        choices_raw = body.get("choices")
        if not isinstance(choices_raw, list):
            raise ProviderError(
                f"openai response choices is not a list: "
                f"{type(choices_raw).__name__}"
            )
        if not choices_raw:
            raise ProviderError("openai response has no choices")
        first = choices_raw[0]
        if not isinstance(first, dict):
            raise ProviderError(
                f"openai response first choice is not an object: "
                f"{type(first).__name__}"
            )
        message_raw = first.get("message")
        if not isinstance(message_raw, dict):
            raise ProviderError(
                f"openai response first choice message is not an object: "
                f"{type(message_raw).__name__}"
            )
        text = message_raw.get("content", "")
        if not isinstance(text, str):
            raise ProviderError(
                f"openai choice.message.content is not a string: "
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
