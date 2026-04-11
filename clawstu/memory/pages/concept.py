"""ConceptPage — what Stuart knows about a specific concept.

Keyed by `concept_id`. The compiled-truth section holds the HAPP framing
(historical context, key actors, outcomes, modern relevance), tied
sources, known misconceptions, and — crucially — the student-specific
state (current tier, samples, last-seen). Concept pages are scoped per
learner, so "civil_war" is a different page for each student.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawstu.memory.pages.base import BrainPage, PageKind, parse_frontmatter


class ConceptPage(BrainPage):
    """A per-(learner, concept) brain page."""

    kind: PageKind = PageKind.CONCEPT
    learner_id: str
    concept_id: str

    def _frontmatter_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "learner_id": self.learner_id,
            "concept_id": self.concept_id,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def parse(cls, text: str) -> ConceptPage:
        fields, body = parse_frontmatter(text)
        if fields.get("kind") != PageKind.CONCEPT.value:
            raise ValueError(
                f"expected kind=concept, got {fields.get('kind')!r}"
            )
        compiled_truth, timeline = BrainPage.split_body(body)
        return cls(
            learner_id=fields["learner_id"],
            concept_id=fields["concept_id"],
            updated_at=datetime.fromisoformat(fields["updated_at"]),
            schema_version=int(fields.get("schema_version", "1")),
            compiled_truth=compiled_truth,
            timeline=timeline,
        )
