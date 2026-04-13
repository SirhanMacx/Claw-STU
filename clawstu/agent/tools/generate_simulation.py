"""Generate an interactive HTML simulation."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GenerateSimulationTool(BaseTool):
    name = "generate_simulation"
    description = (
        "Create an interactive HTML+JS simulation where the "
        "student makes decisions and sees consequences."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic for the simulation"},
            "scenario_description": {
                "type": "string",
                "description": "Description of the scenario to simulate",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        scenario = args.get("scenario_description", topic)
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create a self-contained interactive HTML simulation "
            f"about '{scenario}' for a {age} student. "
            f"Include decision points with consequences. "
            f"All CSS and JS inline."
        )
        resp = await provider.complete(
            system="You generate interactive educational simulations.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model, max_tokens=4096,
        )

        slug = topic.replace(" ", "_")[:20]
        out_path = context.output_dir / f"simulation_{slug}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        return f"Created simulation: {out_path}"
