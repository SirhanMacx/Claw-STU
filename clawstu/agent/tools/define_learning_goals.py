"""Define verifiable learning objectives before teaching a topic."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.orchestrator.providers import LLMMessage
from clawstu.orchestrator.task_kinds import TaskKind


class DefineLearningGoalsTool(BaseTool):
    name = "define_learning_goals"
    description = (
        "Define 2-3 verifiable learning objectives for a topic. "
        "Call this BEFORE teaching."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "What the student wants to learn",
            },
            "current_zpd": {
                "type": "string",
                "description": "Student's current ZPD tier",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"

        zpd = args.get("current_zpd", "meeting")
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(TaskKind.PATHWAY_PLANNING)
        prompt = (
            f"Generate exactly 2-3 specific, verifiable learning objectives "
            f"for teaching '{topic}' to a {age} student at the {zpd} tier.\n"
            f"Format each objective as: 'The student should be able to: ...'\n"
            f"Each objective must be testable with a single question."
        )
        resp = await provider.complete(
            system="You are a learning-objective generator.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
        )
        return f"Learning objectives for '{topic}':\n{resp.text}"
