"""Generate a practice test at the learner's level with answer key."""

from __future__ import annotations

from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GeneratePracticeTestTool(BaseTool):
    name = "generate_practice_test"
    description = (
        "Create a practice test calibrated to the student's ZPD "
        "tier, with an optional answer key."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Test topic"},
            "question_count": {
                "type": "integer",
                "description": "Number of questions (default: 10)",
            },
            "include_answers": {
                "type": "boolean",
                "description": "Include answer key (default: true)",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        count = int(args.get("question_count", 10))
        answers = args.get("include_answers", True)
        age = context.profile.age_bracket.value

        # Determine ZPD tier
        zpd_tiers = [e.tier.value for e in context.profile.zpd_by_domain.values()]
        tier = zpd_tiers[0] if zpd_tiers else "meeting"

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        answer_note = " Include a separate answer key section at the end." if answers else ""
        prompt = (
            f"Create a {count}-question practice test on '{topic}' "
            f"for a {age} student at the {tier} tier.{answer_note} "
            f"Mix question types (MCQ, short answer, true/false). "
            f"Format as markdown."
        )
        resp = await provider.complete(
            system="You create practice assessments for students.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
        )

        slug = topic.replace(" ", "_")[:20]
        out_path = context.output_dir / f"practice_test_{slug}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        return f"Created practice test: {out_path}\n\n{resp.text[:500]}"
