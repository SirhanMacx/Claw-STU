"""Ollama provider — local + cloud via the chat completions API.

Implements the existing sync LLMProvider protocol from providers.py.
Phase 2 flips this to async as part of the wider async migration.

Endpoint: POST {base_url}/api/chat
Docs: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion

HEARTBEAT §3 compliance: `complete()` stays under ~50 lines by
extracting `_build_payload`, `_post`, and `_parse_body` helpers.
Each helper has one job.
"""

from __future__ import annotations

from typing import Any

import httpx

from clawstu.orchestrator.providers import LLMMessage, LLMResponse, ProviderError


class OllamaProvider:
    """LLMProvider for local or cloud Ollama instances."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
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
        """POST to /api/chat and return the parsed response."""
        effective_model = model or "llama3.2"
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
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the payload and return the parsed JSON body.

        Raises ProviderError on network failure, non-2xx status, or
        non-JSON body. The body dict is returned unvalidated; the
        caller is responsible for shape validation.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            http_response = await self._client.post(
                f"{self._base_url}/api/chat",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"ollama returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            parsed = http_response.json()
        except ValueError as exc:
            raise ProviderError(f"ollama returned non-JSON body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"ollama response body is not a JSON object: {type(parsed).__name__}"
            )
        return parsed

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        message = body.get("message") or {}
        if not isinstance(message, dict):
            raise ProviderError(
                f"ollama response message is not an object: {type(message).__name__}"
            )
        text = message.get("content", "")
        if not isinstance(text, str):
            raise ProviderError(
                f"ollama response message.content is not a string: "
                f"{type(text).__name__}"
            )
        return LLMResponse(
            text=text,
            provider=self.name,
            model=str(body.get("model", model)),
            finish_reason="stop",
            metadata={
                "eval_count": str(body.get("eval_count", "")),
                "prompt_eval_count": str(body.get("prompt_eval_count", "")),
            },
        )
