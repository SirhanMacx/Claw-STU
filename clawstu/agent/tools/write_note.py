"""Record a session observation note to the brain store."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.memory.pages import SessionPage


class WriteNoteTool(BaseTool):
    name = "write_note"
    description = (
        "Record an observation about the student's learning "
        "during this session (comprehension, engagement, etc.)."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "Observation to record",
            },
            "category": {
                "type": "string",
                "enum": ["comprehension", "engagement", "misconception", "progress"],
                "description": "Note category",
            },
        },
        "required": ["note"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        note = args.get("note", "")
        if not note:
            return "ERROR: note is required"
        category = args.get("category", "comprehension")

        page = SessionPage(
            session_id=context.session_id,
            learner_id=context.learner_id,
            compiled_truth=f"[{category}] {note}",
        )
        context.brain.put(page, learner_id=context.learner_id)
        return f"Recorded {category} note for session {context.session_id}."
