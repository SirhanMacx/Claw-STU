"""Search Stuart's brain pages for relevant knowledge."""

from __future__ import annotations

import json
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


def _diversify_query(query: str) -> list[str]:
    """Return [original, rephrased, synonym-expanded] query variants.

    Pure keyword-based expansion -- no LLM call needed. Keeps the
    diversification deterministic and fast.
    """
    queries = [query]
    words = query.lower().split()
    if len(words) < 2:
        return queries

    # Rephrased: reverse the non-trivial word order
    rephrased = " ".join(reversed(words))
    if rephrased != query.lower():
        queries.append(rephrased)

    # Synonym-expanded: add individual keywords as separate queries
    # so partial matches on any single term still surface results.
    longest = max(words, key=len)
    if longest != query.lower():
        queries.append(longest)

    return queries


class SearchBrainTool(BaseTool):
    name = "search_brain"
    description = (
        "Search Stuart's brain (memory store) for relevant "
        "concept pages, session notes, and topic knowledge."
    )
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

        pages = context.brain.list_for_learner(context.learner_id)
        if not pages:
            return "No brain pages found for this learner."

        queries = _diversify_query(query)

        # Search all query variants; deduplicate by page key, keep first hit.
        seen_keys: set[str] = set()
        matches: list[str] = []
        for q in queries:
            q_lower = q.lower()
            for page in pages:
                key = getattr(page, "page_key", None) or id(page)
                if key in seen_keys:
                    continue
                rendered = page.render()
                if q_lower in rendered.lower():
                    seen_keys.add(key)
                    matches.append(rendered[:200])

        if not matches:
            return f"No brain pages matched '{query}'."
        return json.dumps(matches[:5])
