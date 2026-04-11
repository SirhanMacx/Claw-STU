"""TopicPage — a cluster of related concepts.

Keyed by `topic_id`. The classic example from the spec is
"Reform Movements", which groups abolition, suffrage, labor, and
temperance. The compiled truth tells Stuart how the concepts fit
together and suggests a teaching order; the timeline records when a
learner visited any concept under the topic.

Topic pages are scoped per learner so the ordering / emphasis can
diverge between students.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawstu.memory.pages.base import BrainPage, PageKind, parse_frontmatter


class TopicPage(BrainPage):
    """A per-(learner, topic) brain page."""

    kind: PageKind = PageKind.TOPIC
    learner_id: str
    topic_id: str

    def _frontmatter_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "learner_id": self.learner_id,
            "topic_id": self.topic_id,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def parse(cls, text: str) -> TopicPage:
        fields, body = parse_frontmatter(text)
        if fields.get("kind") != PageKind.TOPIC.value:
            raise ValueError(
                f"expected kind=topic, got {fields.get('kind')!r}"
            )
        compiled_truth, timeline = BrainPage.split_body(body)
        return cls(
            learner_id=fields["learner_id"],
            topic_id=fields["topic_id"],
            updated_at=datetime.fromisoformat(fields["updated_at"]),
            schema_version=int(fields.get("schema_version", "1")),
            compiled_truth=compiled_truth,
            timeline=timeline,
        )
