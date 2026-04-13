"""TemplatePage -- a proven generation template.

Stores artifacts (worksheet, game, visual, etc.) that produced positive
student outcomes.  Keyed by ``template_id``.  The compiled-truth section
holds the original prompt and success context; the timeline logs reuse
events across sessions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawstu.memory.pages.base import BrainPage, PageKind, parse_frontmatter


class TemplatePage(BrainPage):
    """A per-(learner, template) brain page for reusable artifacts."""

    kind: PageKind = PageKind.TEMPLATE
    learner_id: str
    template_id: str
    artifact_type: str = ""
    topic: str = ""
    zpd_tier: str = ""
    prompt_used: str = ""
    success_score: float = 0.0

    def _frontmatter_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "learner_id": self.learner_id,
            "template_id": self.template_id,
            "artifact_type": self.artifact_type,
            "topic": self.topic,
            "zpd_tier": self.zpd_tier,
            "success_score": self.success_score,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def parse(cls, text: str) -> TemplatePage:
        """Parse a rendered template page back into a model."""
        fields, body = parse_frontmatter(text)
        if fields.get("kind") != PageKind.TEMPLATE.value:
            raise ValueError(
                f"expected kind=template, got {fields.get('kind')!r}"
            )
        compiled_truth, timeline = BrainPage.split_body(body)
        return cls(
            learner_id=fields["learner_id"],
            template_id=fields["template_id"],
            artifact_type=fields.get("artifact_type", ""),
            topic=fields.get("topic", ""),
            zpd_tier=fields.get("zpd_tier", ""),
            success_score=float(fields.get("success_score", "0.0")),
            updated_at=datetime.fromisoformat(fields["updated_at"]),
            schema_version=int(fields.get("schema_version", "1")),
            compiled_truth=compiled_truth,
            timeline=timeline,
        )
