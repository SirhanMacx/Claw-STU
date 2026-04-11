"""Free-text learning topics.

Claw-STU is a subject-agnostic tutor. A student shows up with something
they want to learn — "photosynthesis", "the French Revolution", "why
does ice float", "recursion in Python" — and Stuart builds a session
around that topic.

The `Domain` enum in `clawstu.profile.model` is kept as a **coarse
classification tag** so the learner profile can note "this was a
science topic" vs. "this was a history topic" for future adaptation.
It is NOT a gate on what a student is allowed to ask about. The canonical
source of truth for a session is the `Topic` — a validated, free-text
string plus a slug for stable IDs and log lines.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clawstu.profile.model import Domain

_MAX_RAW_LEN = 200
_MIN_RAW_LEN = 2
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class Topic(BaseModel):
    """A student-provided learning topic.

    - `raw`: the student's own phrasing, preserved verbatim for prompts
      and session summaries.
    - `slug`: a normalized, URL-safe identifier used for logs, event
      IDs, and fallback lookups.
    - `domain`: a coarse classification the orchestrator may attach.
      Defaults to `Domain.OTHER` and is intentionally *not* required —
      forcing every topic into a taxonomy is the anti-pattern we are
      trying to escape.
    """

    model_config = ConfigDict(frozen=True)

    raw: str = Field(min_length=_MIN_RAW_LEN, max_length=_MAX_RAW_LEN)
    slug: str = Field(min_length=1, max_length=80)
    domain: Domain = Domain.OTHER

    @field_validator("raw")
    @classmethod
    def _strip_raw(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < _MIN_RAW_LEN:
            raise ValueError("topic is too short")
        return stripped

    @classmethod
    def from_student_input(
        cls,
        text: str,
        *,
        domain: Domain = Domain.OTHER,
    ) -> Topic:
        """Build a `Topic` from raw student input. Raises on empty/huge."""
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("topic cannot be empty")
        if len(cleaned) > _MAX_RAW_LEN:
            raise ValueError(
                f"topic too long ({len(cleaned)} > {_MAX_RAW_LEN} chars)"
            )
        slug = _slugify(cleaned)
        if not slug:
            raise ValueError(f"topic has no sluggable content: {cleaned!r}")
        return cls(raw=cleaned, slug=slug, domain=domain)


def _slugify(text: str) -> str:
    lowered = text.lower()
    collapsed = _SLUG_RE.sub("-", lowered).strip("-")
    return collapsed[:80]
