"""Generate a mini slide deck (3-5 slides) for visual learners."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GenerateSlidesTool(BaseTool):
    name = "generate_slides"
    description = (
        "Create a 3-5 slide HTML mini deck for visual learners."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic for the slides"},
            "slide_count": {
                "type": "integer",
                "description": "Number of slides (default: 5)",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        count = int(args.get("slide_count", 5))
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create a {count}-slide HTML presentation about '{topic}' "
            f"for a {age} student. Use arrow key navigation, clean "
            f"design, and all CSS/JS inline."
        )
        resp = await provider.complete(
            system="You generate HTML slide presentations.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model, max_tokens=4096,
        )

        slug = topic.replace(" ", "_")[:20]
        out_path = context.output_dir / f"slides_{slug}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        return f"Created {count}-slide deck: {out_path}"
