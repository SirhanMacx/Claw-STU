"""Search for proven templates that worked for similar topics/levels."""

from __future__ import annotations

import json
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.memory.pages.base import PageKind
from clawstu.memory.pages.template import TemplatePage


class FindTemplateTool(BaseTool):
    name = "find_template"
    description = (
        "Search for proven templates that worked for similar "
        "topics or difficulty levels."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Topic to search for",
            },
            "artifact_type": {
                "type": "string",
                "description": "Filter by artifact type (optional)",
            },
        },
        "required": ["topic"],
    }

    async def execute(
        self, args: dict[str, Any], context: ToolContext,
    ) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"

        artifact_type = args.get("artifact_type", "")
        pages = context.brain.list_for_learner(
            context.learner_id, kind=PageKind.TEMPLATE,
        )
        matches = _filter_templates(pages, topic, artifact_type)
        if not matches:
            return f"No templates found for topic '{topic}'."
        return json.dumps(matches[:5])


def _filter_templates(
    pages: list[Any],
    topic: str,
    artifact_type: str,
) -> list[dict[str, str]]:
    """Return matching template summaries sorted by relevance."""
    topic_lower = topic.lower()
    results: list[dict[str, str]] = []
    for page in pages:
        if not isinstance(page, TemplatePage):
            continue
        if topic_lower not in page.topic.lower():
            continue
        if artifact_type and artifact_type.lower() != page.artifact_type.lower():
            continue
        results.append({
            "template_id": page.template_id,
            "artifact_type": page.artifact_type,
            "topic": page.topic,
            "zpd_tier": page.zpd_tier,
            "prompt_used": page.prompt_used[:200],
        })
    return results
