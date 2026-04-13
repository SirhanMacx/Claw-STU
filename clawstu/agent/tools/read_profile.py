"""Read the current learner profile (ZPD, modality, history)."""

from __future__ import annotations

import json
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class ReadProfileTool(BaseTool):
    name = "read_profile"
    description = (
        "Read the current student's learning profile including "
        "ZPD estimates, modality outcomes, and misconceptions."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        p = context.profile
        zpd = {
            d.value: {"tier": e.tier.value, "confidence": e.confidence}
            for d, e in p.zpd_by_domain.items()
        }
        modality = {
            m.value: {"success_rate": o.success_rate, "attempts": o.attempts}
            for m, o in p.modality_outcomes.items()
        }
        summary = {
            "learner_id": p.learner_id,
            "age_bracket": p.age_bracket.value,
            "zpd_by_domain": zpd,
            "modality_outcomes": modality,
            "misconceptions": p.misconceptions,
            "event_count": len(p.events),
        }
        return json.dumps(summary, indent=2)
