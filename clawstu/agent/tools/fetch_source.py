"""Retrieve and summarize a specific source document.

Handles both local file paths and HTTP(S) URLs. Long content is truncated
to stay within a reasonable context-window budget.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from clawstu.agent.base_tool import BaseTool, ToolContext

_MAX_BYTES = 1_048_576
_SUMMARY_CHARS = 4000


def _summarize(text: str) -> str:
    if len(text) <= _SUMMARY_CHARS:
        return text
    return text[:_SUMMARY_CHARS] + "\n\n[...truncated...]"


class FetchSourceTool(BaseTool):
    name = "fetch_source"
    description = "Retrieve a local file or URL and return its content."
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "path_or_url": {
                "type": "string",
                "description": "Local file path or HTTP(S) URL",
            },
        },
        "required": ["path_or_url"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        target = args.get("path_or_url", "")
        if not target:
            return "ERROR: path_or_url is required"

        if target.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(target)
                resp.raise_for_status()
                return _summarize(resp.text)

        path = Path(target)
        if not path.is_file():
            return f"File not found: {target}"
        return _summarize(path.read_text(encoding="utf-8", errors="replace"))
