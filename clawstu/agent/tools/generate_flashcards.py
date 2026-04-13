"""Generate spaced repetition flashcards."""

from __future__ import annotations

import json
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class GenerateFlashcardsTool(BaseTool):
    name = "generate_flashcards"
    description = (
        "Create flashcards (front/back pairs) for spaced repetition "
        "study. Returns JSON and saves as CSV."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Flashcard topic"},
            "card_count": {
                "type": "integer",
                "description": "Number of cards (default: 10)",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        topic = args.get("topic", "")
        if not topic:
            return "ERROR: topic is required"
        count = int(args.get("card_count", 10))
        age = context.profile.age_bracket.value

        provider, model = context.router.for_task(
            __import__("clawstu.orchestrator.task_kinds", fromlist=["TaskKind"]).TaskKind.BLOCK_GENERATION,
        )
        from clawstu.orchestrator.providers import LLMMessage

        prompt = (
            f"Create {count} flashcards about '{topic}' for a {age} "
            f"student. Return ONLY a JSON array of objects with "
            f'"front" and "back" keys. No markdown, no explanation.'
        )
        resp = await provider.complete(
            system="You generate flashcard JSON. Output ONLY valid JSON.",
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
        )

        # Try to parse JSON from response
        try:
            cards = json.loads(resp.text.strip())
        except json.JSONDecodeError:
            cards = [{"front": f"Q{i+1} about {topic}", "back": "..."} for i in range(count)]

        # Save as CSV
        slug = topic.replace(" ", "_")[:20]
        csv_path = context.output_dir / f"flashcards_{slug}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["front\tback"]
        for c in cards:
            lines.append(f"{c['front']}\t{c['back']}")
        csv_path.write_text("\n".join(lines), encoding="utf-8")

        return f"Created {len(cards)} flashcards: {csv_path}\n{json.dumps(cards[:3])}"
