"""Generate a condensed study guide from session history + brain pages."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.memory.pages import PageKind


class GenerateStudyGuideTool(BaseTool):
    name = "generate_study_guide"
    description = (
        "Create a condensed review/study guide based on the "
        "student's session history and brain pages."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Topic to study (default: current session topic)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", context.session_topic or "general review")
        age = context.profile.age_bracket.value

        # Gather brain pages for context
        pages = context.brain.list_for_learner(context.learner_id, PageKind.CONCEPT)
        brain_summaries = "\n".join(
            f"- {p.render()[:100]}" for p in pages[:5]
        )

        # Gather misconceptions
        misconceptions = ", ".join(
            f"{k} (x{v})" for k, v in context.profile.misconceptions.items()
        ) or "none"

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create a study guide on '{topic}' for a {age} student.\n"
            f"Known misconceptions: {misconceptions}\n"
            f"Brain context:\n{brain_summaries}\n\n"
            f"Include: key concepts, common mistakes to avoid, "
            f"practice questions, and a summary. Format as markdown."
        )
        resp = await provider.complete(
            system="You create concise, effective study guides.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
        )

        out_path = context.output_dir / f"study_guide_{topic.replace(' ', '_')[:20]}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        return f"Created study guide: {out_path}\n\n{resp.text[:500]}"
