"""SessionPage — one-page history of a single completed session.

Keyed by `session_id`. The compiled truth summarizes what happened:
which concepts were covered, how many re-teaches, overall accuracy,
modality rotations. The timeline is typically short (it's already a
one-session record), holding bullet points for each teach-check block.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawstu.memory.pages.base import BrainPage, PageKind, parse_frontmatter


class SessionPage(BrainPage):
    """A per-session brain page."""

    kind: PageKind = PageKind.SESSION
    session_id: str
    learner_id: str

    def _frontmatter_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "session_id": self.session_id,
            "learner_id": self.learner_id,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def parse(cls, text: str) -> SessionPage:
        fields, body = parse_frontmatter(text)
        if fields.get("kind") != PageKind.SESSION.value:
            raise ValueError(
                f"expected kind=session, got {fields.get('kind')!r}"
            )
        compiled_truth, timeline = BrainPage.split_body(body)
        return cls(
            session_id=fields["session_id"],
            learner_id=fields["learner_id"],
            updated_at=datetime.fromisoformat(fields["updated_at"]),
            schema_version=int(fields.get("schema_version", "1")),
            compiled_truth=compiled_truth,
            timeline=timeline,
        )
