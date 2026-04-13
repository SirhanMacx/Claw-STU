"""Generate animated explanations as HTML animations."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GenerateAnimationTool(BaseTool):
    name = "generate_animation"
    description = (
        "Create an animated HTML explanation of a concept. "
        "Uses CSS/JS animations for step-by-step visualization."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic to animate"},
            "concept_to_animate": {
                "type": "string",
                "description": "Specific concept or process to visualize",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        concept = args.get("concept_to_animate", topic)
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create a self-contained HTML page with CSS/JS "
            f"animations explaining '{concept}' for a {age} student. "
            f"Use step-by-step animated transitions. Play/pause "
            f"controls. All CSS/JS inline."
        )
        resp = await provider.complete(
            system="You generate animated HTML educational content.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model, max_tokens=4096,
        )

        slug = topic.replace(" ", "_")[:20]
        out_path = context.output_dir / f"animation_{slug}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        return f"Created animation: {out_path}"
