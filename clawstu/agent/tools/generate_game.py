"""Generate an educational game as standalone HTML."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GenerateGameTool(BaseTool):
    name = "generate_game"
    description = (
        "Create an interactive HTML learning game. Types: "
        "matching, sorting, timeline, quiz."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic for the game"},
            "game_type": {
                "type": "string",
                "enum": ["matching", "sorting", "timeline", "quiz"],
                "description": "Type of game to create",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        game_type = args.get("game_type", "quiz")
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create a self-contained HTML {game_type} game about "
            f"'{topic}' for a {age} student. Include all CSS and JS "
            f"inline. Make it colorful and engaging."
        )
        resp = await provider.complete(
            system="You generate standalone HTML educational games.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model, max_tokens=4096,
        )

        out_path = context.output_dir / f"game_{game_type}_{topic.replace(' ', '_')[:20]}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        return f"Created {game_type} game: {out_path}"
