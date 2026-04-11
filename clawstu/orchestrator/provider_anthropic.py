"""Anthropic Claude provider via the Messages API.

Endpoint: POST https://api.anthropic.com/v1/messages
Docs: https://docs.anthropic.com/en/api/messages

HEARTBEAT §3 compliance: same helper-extraction pattern as
OllamaProvider. `complete()` stays under 50 lines.
"""

from __future__ import annotations

from typing import Any

import httpx

from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)

_ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider:
    """LLMProvider for Anthropic's Claude Messages API."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://api.anthropic.com",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("AnthropicProvider requires an api_key")
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
        """POST to /v1/messages and return the parsed response."""
        effective_model = model or "claude-haiku-4-5"
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
        return {
            "model": model,
            "system": system,
            "messages": [
                {"role": msg.role, "content": msg.content} for msg in messages
            ],
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
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
        }
        try:
            http_response = await self._client.post(
                f"{self._base_url}/v1/messages",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"anthropic request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"anthropic returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            parsed = http_response.json()
        except ValueError as exc:
            raise ProviderError(
                f"anthropic returned non-JSON body: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"anthropic response body is not a JSON object: "
                f"{type(parsed).__name__}"
            )
        return parsed

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        content_blocks = body.get("content")
        if not isinstance(content_blocks, list):
            raise ProviderError(
                f"anthropic response content is not a list: "
                f"{type(content_blocks).__name__}"
            )
        text_blocks: list[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                block_text = block.get("text")
                if isinstance(block_text, str):
                    text_blocks.append(block_text)
        if not text_blocks:
            raise ProviderError(
                "anthropic response has no text blocks in content"
            )
        usage_raw = body.get("usage")
        usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
        return LLMResponse(
            text="\n".join(text_blocks),
            provider=self.name,
            model=str(body.get("model", model)),
            finish_reason=str(body.get("stop_reason", "stop")),
            metadata={
                "input_tokens": str(usage.get("input_tokens", "")),
                "output_tokens": str(usage.get("output_tokens", "")),
            },
        )
