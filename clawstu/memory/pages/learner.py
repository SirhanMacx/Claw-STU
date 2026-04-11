"""LearnerPage — what Stuart knows about a specific learner.

One page per learner, keyed by `learner_id`. The compiled-truth section
is the rewritten summary of how this student learns (strengths, pacing,
modality preferences, voice calibration); the timeline records events
like calibrations, check-for-understanding outcomes, and voluntary
questions over time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawstu.memory.pages.base import BrainPage, PageKind, parse_frontmatter


class LearnerPage(BrainPage):
    """A per-learner brain page."""

    kind: PageKind = PageKind.LEARNER
    learner_id: str

    def _frontmatter_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "learner_id": self.learner_id,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def parse(cls, text: str) -> LearnerPage:
        fields, body = parse_frontmatter(text)
        if fields.get("kind") != PageKind.LEARNER.value:
            raise ValueError(
                f"expected kind=learner, got {fields.get('kind')!r}"
            )
        compiled_truth, timeline = BrainPage.split_body(body)
        return cls(
            learner_id=fields["learner_id"],
            updated_at=datetime.fromisoformat(fields["updated_at"]),
            schema_version=int(fields.get("schema_version", "1")),
            compiled_truth=compiled_truth,
            timeline=timeline,
        )
