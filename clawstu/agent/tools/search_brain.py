"""Search Stuart's brain pages for relevant knowledge."""

from __future__ import annotations

import json
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class SearchBrainTool(BaseTool):
    name = "search_brain"
    description = (
        "Search Stuart's brain (memory store) for relevant "
        "concept pages, session notes, and topic knowledge."
    )
    parameters: dict[str, Any] = {
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

        query_lower = query.lower()
        matches = []
        for page in pages:
            rendered = page.render()
            if query_lower in rendered.lower():
                matches.append(rendered[:200])

        if not matches:
            return f"No brain pages matched '{query}'."
        return json.dumps(matches[:5])
