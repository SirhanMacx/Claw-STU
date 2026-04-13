"""Save a successful generation as a reusable template."""

from __future__ import annotations

import uuid
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.memory.pages.template import TemplatePage


class SaveTemplateTool(BaseTool):
    name = "save_template"
    description = (
        "Save a successful generation as a reusable template "
        "for future students."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "artifact_type": {
                "type": "string",
                "description": (
                    "Kind of artifact: worksheet, game, visual, etc."
                ),
            },
            "topic": {
                "type": "string",
                "description": "Topic the artifact covers",
            },
            "prompt_used": {
                "type": "string",
                "description": "The prompt that generated the artifact",
            },
            "success_notes": {
                "type": "string",
                "description": "Why this worked well for the student",
            },
        },
        "required": ["artifact_type", "topic", "prompt_used"],
    }

    async def execute(
        self, args: dict[str, Any], context: ToolContext,
    ) -> str:
        artifact_type = args.get("artifact_type", "")
        topic = args.get("topic", "")
        prompt_used = args.get("prompt_used", "")
        if not (artifact_type and topic and prompt_used):
            return "ERROR: artifact_type, topic, and prompt_used are required"

        success_notes = args.get("success_notes", "")
        template_id = f"tpl-{uuid.uuid4().hex[:8]}"
        page = TemplatePage(
            learner_id=context.learner_id,
            template_id=template_id,
            artifact_type=artifact_type,
            topic=topic,
            prompt_used=prompt_used,
            compiled_truth=success_notes,
        )
        context.brain.put(page, learner_id=context.learner_id)
        return f"Saved template {template_id} ({artifact_type} on {topic})."
