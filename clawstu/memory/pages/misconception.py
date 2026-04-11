"""MisconceptionPage — a specific wrong-answer pattern.

Keyed by `misconception_id`. Cross-links to the concepts it affects and
the sessions where it showed up. The compiled truth describes the
pattern (what the student believes and why it's wrong); the timeline
logs each occurrence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawstu.memory.pages.base import BrainPage, PageKind, parse_frontmatter


class MisconceptionPage(BrainPage):
    """A per-(learner, misconception) brain page."""

    kind: PageKind = PageKind.MISCONCEPTION
    learner_id: str
    misconception_id: str
    concept_id: str
    occurrences: int = 0

    def _frontmatter_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "learner_id": self.learner_id,
            "misconception_id": self.misconception_id,
            "concept_id": self.concept_id,
            "occurrences": self.occurrences,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def parse(cls, text: str) -> MisconceptionPage:
        fields, body = parse_frontmatter(text)
        if fields.get("kind") != PageKind.MISCONCEPTION.value:
            raise ValueError(
                f"expected kind=misconception, got {fields.get('kind')!r}"
            )
        compiled_truth, timeline = BrainPage.split_body(body)
        return cls(
            learner_id=fields["learner_id"],
            misconception_id=fields["misconception_id"],
            concept_id=fields["concept_id"],
            occurrences=int(fields.get("occurrences", "0")),
            updated_at=datetime.fromisoformat(fields["updated_at"]),
            schema_version=int(fields.get("schema_version", "1")),
            compiled_truth=compiled_truth,
            timeline=timeline,
        )
