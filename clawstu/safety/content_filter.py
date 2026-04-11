"""Age-appropriate content filter.

Every string shown to the student must pass through this filter. The
MVP implementation is a keyword blocklist with age-bracket awareness.
The post-MVP version adds an LLM-backed classifier — but it is layered
*on top of* this filter, not a replacement. Deterministic filters
cannot be prompt-injected.

This module is intentionally paranoid. A false positive (blocking
acceptable content) is a P1 bug. A false negative (allowing
age-inappropriate content through) is a P0 bug. We tune toward caution.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict

from clawstu.profile.model import AgeBracket


class ContentDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


class FilterResult(BaseModel):
    """Result of a single filter check."""

    model_config = ConfigDict(frozen=True)

    decision: ContentDecision
    matched_terms: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is ContentDecision.ALLOW


# Small, explicit blocklists. Kept as tuples so the module is immutable
# and easy to diff in review.

_GRAPHIC_VIOLENCE = (
    "graphic torture",
    "dismemberment",
    "gore",
    "snuff",
)
_EXPLICIT_SEXUAL = (
    "explicit sexual",
    "pornographic",
    "erotica",
)
_SELF_HARM_ENCOURAGEMENT = (
    "how to harm yourself",
    "how to hurt yourself",
    "ways to self-harm",
)

_UNIVERSAL_BLOCKLIST = _GRAPHIC_VIOLENCE + _EXPLICIT_SEXUAL + _SELF_HARM_ENCOURAGEMENT

# Bracket-specific additions. Applied on top of the universal list.
_BRACKET_BLOCKLIST: dict[AgeBracket, tuple[str, ...]] = {
    AgeBracket.EARLY_ELEMENTARY: (
        "massacre",
        "execution",
        "genocide",
    ),
    AgeBracket.LATE_ELEMENTARY: (
        "massacre in detail",
        "execution method",
    ),
}


class ContentFilter:
    """Deterministic content filter, keyword-based.

    The filter is designed to be *boring*. It does not attempt to
    classify nuance; that is the job of the (post-MVP) LLM-backed
    classifier. This layer exists to catch the obvious cases that no
    model-generated output should ever emit.
    """

    def check(self, text: str, *, age_bracket: AgeBracket) -> FilterResult:
        if not text:
            return FilterResult(decision=ContentDecision.ALLOW)

        lowered = text.lower()
        universal_hits = self._matches(lowered, _UNIVERSAL_BLOCKLIST)
        if universal_hits:
            return FilterResult(
                decision=ContentDecision.BLOCK,
                matched_terms=tuple(universal_hits),
                reason="universal blocklist match",
            )

        bracket_terms = _BRACKET_BLOCKLIST.get(age_bracket, ())
        bracket_hits = self._matches(lowered, bracket_terms)
        if bracket_hits:
            return FilterResult(
                decision=ContentDecision.BLOCK,
                matched_terms=tuple(bracket_hits),
                reason=f"blocklist match for age bracket {age_bracket.value}",
            )
        return FilterResult(decision=ContentDecision.ALLOW)

    @staticmethod
    def _matches(lowered_text: str, terms: tuple[str, ...]) -> list[str]:
        hits: list[str] = []
        for term in terms:
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, lowered_text):
                hits.append(term)
        return hits
