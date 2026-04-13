"""Age-appropriate web search via DuckDuckGo instant answers.

No API key required. Results are filtered by a blocklist of adult-content
keywords before being returned.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from clawstu.agent.base_tool import BaseTool, ToolContext

_ADULT_KEYWORDS = frozenset({
    "porn", "xxx", "adult", "sex", "nsfw", "onlyfans", "hentai",
    "nude", "naked", "erotic", "fetish", "stripper",
})

_DDG_URL = "https://api.duckduckgo.com/"


def _is_safe(text: str) -> bool:
    lower = text.lower()
    return not any(kw in lower for kw in _ADULT_KEYWORDS)


class SearchWebTool(BaseTool):
    name = "search_web"
    description = "Perform an age-appropriate web search using DuckDuckGo."
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        query = args.get("query", "")
        if not query:
            return "ERROR: query is required"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _DDG_URL,
                params={"q": query, "format": "json", "no_html": "1"},
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, str]] = []
        for topic in data.get("RelatedTopics", []):
            text = topic.get("Text", "")
            url = topic.get("FirstURL", "")
            if text and url and _is_safe(text):
                results.append({"title": text[:80], "url": url})
        if data.get("AbstractText") and _is_safe(data["AbstractText"]):
            results.insert(0, {
                "title": data.get("Heading", query),
                "snippet": data["AbstractText"][:200],
            })
        return json.dumps(results[:5]) if results else "No results found."
