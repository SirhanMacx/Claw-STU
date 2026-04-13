"""Generate diagrams, timelines, concept maps as SVG/HTML."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GenerateVisualTool(BaseTool):
    name = "generate_visual"
    description = (
        "Create a visual aid: timeline, concept map, cause-effect "
        "diagram, or Venn diagram as HTML/SVG."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic for the visual"},
            "visual_type": {
                "type": "string",
                "enum": ["timeline", "concept_map", "cause_effect", "venn_diagram"],
                "description": "Type of visual to create",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        visual_type = args.get("visual_type", "concept_map")
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create a self-contained HTML page with an SVG "
            f"{visual_type} about '{topic}' for a {age} student. "
            f"Use clear labels and colors. All CSS/JS inline."
        )
        resp = await provider.complete(
            system="You generate educational SVG/HTML visuals.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model, max_tokens=4096,
        )

        slug = topic.replace(" ", "_")[:20]
        out_path = context.output_dir / f"visual_{visual_type}_{slug}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        return f"Created {visual_type} visual: {out_path}"
