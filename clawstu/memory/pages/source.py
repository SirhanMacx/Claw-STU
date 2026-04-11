"""SourcePage — a primary source with HAPP metadata.

Keyed by `source_id`. Holds title, attribution, age-bracket tag, and the
concepts the source is tied to. The compiled truth is the source text
itself (or a short version, for long documents) plus Stuart's summary of
how the source applies pedagogically.

Sources are global rather than per-learner: one source file, many
learners reference it. Source pages live under a `sources` subdirectory
rather than a learner-hashed directory — `BrainStore` special-cases
this.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawstu.memory.pages.base import BrainPage, PageKind, parse_frontmatter


class SourcePage(BrainPage):
    """A primary-source brain page (global, not per-learner)."""

    kind: PageKind = PageKind.SOURCE
    source_id: str
    title: str
    age_bracket: str  # stored as a string so memory doesn't import profile enums
    attribution: str = ""

    def _frontmatter_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_id": self.source_id,
            "title": self.title,
            "attribution": self.attribution,
            "age_bracket": self.age_bracket,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def parse(cls, text: str) -> SourcePage:
        fields, body = parse_frontmatter(text)
        if fields.get("kind") != PageKind.SOURCE.value:
            raise ValueError(
                f"expected kind=source, got {fields.get('kind')!r}"
            )
        compiled_truth, timeline = BrainPage.split_body(body)
        return cls(
            source_id=fields["source_id"],
            title=fields["title"],
            attribution=fields.get("attribution", ""),
            age_bracket=fields["age_bracket"],
            updated_at=datetime.fromisoformat(fields["updated_at"]),
            schema_version=int(fields.get("schema_version", "1")),
            compiled_truth=compiled_truth,
            timeline=timeline,
        )
