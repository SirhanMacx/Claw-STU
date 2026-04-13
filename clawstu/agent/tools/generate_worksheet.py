"""Generate scaffolded practice problems at the learner's ZPD."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GenerateWorksheetTool(BaseTool):
    name = "generate_worksheet"
    description = (
        "Generate a scaffolded worksheet with practice problems "
        "calibrated to the student's current ZPD tier."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic for the worksheet"},
            "difficulty": {
                "type": "string",
                "enum": ["approaching", "meeting", "exceeding"],
                "description": "Difficulty tier (from ZPD)",
            },
            "question_count": {
                "type": "integer",
                "description": "Number of questions (default: 5)",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        difficulty = args.get("difficulty", "meeting")
        count = int(args.get("question_count", 5))
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create a {count}-question worksheet on '{topic}' for a "
            f"{age} student at the {difficulty} tier. "
            f"Include clear instructions and space for answers. "
            f"Format as clean markdown."
        )
        resp = await provider.complete(
            system="You are a worksheet generator for students.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
        )
        content = resp.text

        out_path = context.output_dir / f"worksheet_{topic.replace(' ', '_')[:30]}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        return f"Created worksheet: {out_path}\n\n{content[:500]}"
