"""Retrieve this student's recorded misconceptions."""

from __future__ import annotations

import json
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.memory.pages import MisconceptionPage, PageKind


class ReadMisconceptionsTool(BaseTool):
    name = "read_misconceptions"
    description = (
        "Retrieve the student's recorded misconceptions from "
        "the brain store and learner profile."
    )
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        # From profile
        profile_misc = context.profile.misconceptions

        # From brain store
        pages = context.brain.list_for_learner(
            context.learner_id, PageKind.MISCONCEPTION,
        )
        brain_misc = []
        for p in pages:
            if isinstance(p, MisconceptionPage):
                brain_misc.append({
                    "concept": p.misconception_id,
                    "content": p.render()[:200],
                })

        result = {
            "profile_misconceptions": profile_misc,
            "brain_misconceptions": brain_misc,
        }
        if not profile_misc and not brain_misc:
            return "No misconceptions recorded for this student."
        return json.dumps(result, indent=2)
