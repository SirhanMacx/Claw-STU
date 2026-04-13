"""Check whether learning objectives were met after teaching."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.orchestrator.providers import LLMMessage
from clawstu.orchestrator.task_kinds import TaskKind


class CheckLearningGoalsTool(BaseTool):
    name = "check_learning_goals"
    description = (
        "Check if the student met the learning objectives. "
        "Call this before closing a topic."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "goals": {
                "type": "string",
                "description": "The learning objectives that were set",
            },
            "evidence": {
                "type": "string",
                "description": "What the student demonstrated",
            },
        },
        "required": ["goals", "evidence"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        goals = args.get("goals", "")
        evidence = args.get("evidence", "")
        if not goals or not evidence:
            return "ERROR: both goals and evidence are required"

        provider, model = context.router.for_task(TaskKind.RUBRIC_EVALUATION)
        prompt = (
            f"Learning objectives:\n{goals}\n\n"
            f"Student evidence:\n{evidence}\n\n"
            f"For each objective, state MET or NOT_MET with a one-line reason."
        )
        resp = await provider.complete(
            system="You are a learning-objective evaluator.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
        )
        return f"Goal assessment:\n{resp.text}"
