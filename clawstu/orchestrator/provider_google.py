"""Google Gemini provider via the generateContent REST API.

Endpoint: POST {base_url}/models/{model}:generateContent
Docs: https://ai.google.dev/api/generate-content

Uses raw httpx like the other four providers — no SDK dependency.
Default model: gemini-2.0-flash (fast, cheap, good for education).

HEARTBEAT S3 compliance: same helper-extraction pattern as the
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


class GoogleProvider:
    """LLMProvider for Google's Gemini generateContent API."""

    name = "google"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("GoogleProvider requires an api_key")
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
        """POST to /models/{model}:generateContent and return the parsed response."""
        effective_model = model or "gemini-2.0-flash"
        payload = self._build_payload(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = await self._post(payload, model=effective_model)
        return self._parse_body(body, model=effective_model)

    def _build_payload(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        for msg in messages:
            role = "user" if msg.role == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg.content}],
            })
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

    async def _post(
        self, payload: dict[str, Any], *, model: str,
    ) -> dict[str, Any]:
        """POST the payload and return the parsed JSON body.

        Raises ProviderError on network failure, non-2xx status, or
        non-JSON/non-object body. The body dict is returned unvalidated
        beyond the top-level shape; _parse_body handles field shape.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        url = f"{self._base_url}/models/{model}:generateContent"
        try:
            http_response = await self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"google request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"google returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            parsed = http_response.json()
        except ValueError as exc:
            raise ProviderError(
                f"google returned non-JSON body: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"google response body is not a JSON object: "
                f"{type(parsed).__name__}"
            )
        return parsed

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderError("google response has no candidates")
        first = candidates[0]
        if not isinstance(first, dict):
            raise ProviderError(
                f"google response first candidate is not an object: "
                f"{type(first).__name__}"
            )
        content = first.get("content")
        if not isinstance(content, dict):
            raise ProviderError(
                f"google response candidate content is not an object: "
                f"{type(content).__name__}"
            )
        parts = content.get("parts")
        if not isinstance(parts, list):
            raise ProviderError(
                f"google response candidate parts is not a list: "
                f"{type(parts).__name__}"
            )
        text_parts: list[str] = [
            p["text"]
            for p in parts
            if isinstance(p, dict) and isinstance(p.get("text"), str)
        ]
        if not text_parts:
            raise ProviderError("google response has no text parts")
        usage_raw = body.get("usageMetadata")
        usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
        return LLMResponse(
            text="\n".join(text_parts),
            provider=self.name,
            model=model,
            finish_reason=str(first.get("finishReason", "STOP")).lower(),
            metadata={
                "prompt_tokens": str(usage.get("promptTokenCount", "")),
                "completion_tokens": str(usage.get("candidatesTokenCount", "")),
            },
        )
