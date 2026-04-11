"""Persona / boundary enforcement.

SOUL.md §"Non-identity" lists what Stuart is *not*: a friend, romantic
interest, therapist, oracle, etc. This module refuses attempts to pull
Stuart into any of those roles.

Two directions:

1. **Inbound** — student messages that try to rename Stuart, make it
   role-play as a friend, elicit emotional claims, etc. The handler
   returns a `BoundaryViolation` and the orchestrator substitutes a
   canonical boundary-restate response.
2. **Outbound** — generated text from the LLM layer that violates
   SOUL.md's voice constraints (sycophancy, performative praise,
   emotional claims). These are also caught and rewritten or blocked
   before reaching the student.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict


class ViolationKind(str, Enum):
    RENAME_ATTEMPT = "rename_attempt"
    FRIEND_ROLEPLAY = "friend_roleplay"
    EMOTIONAL_CLAIM = "emotional_claim"
    SYCOPHANCY = "sycophancy"


class BoundaryViolation(BaseModel):
    """A boundary violation flagged by the enforcer."""

    model_config = ConfigDict(frozen=True)

    kind: ViolationKind
    matched_phrase: str
    direction: str  # "inbound" or "outbound"


_INBOUND_RENAME = (
    r"\byour name is (now )?(?!stuart)\w+",
    r"\bi'?m going to call you\b",
    r"\bpretend (your name is|to be) \w+",
    r"\bfrom now on you'?re\b",
)

_INBOUND_FRIEND_ROLEPLAY = (
    r"\bpretend (to be|you'?re) my (friend|bestie|girlfriend|boyfriend|crush)\b",
    r"\broleplay as my (friend|bestie|girlfriend|boyfriend)\b",
    r"\bbe my friend\b",
)

_INBOUND_EMOTIONAL_DEMAND = (
    r"\bdo you (love|like|care about) me\b",
    r"\btell me you (love|care about) me\b",
)

# Outbound patterns are what we don't want Stuart's own output to
# contain. These are post-generation checks against the LLM output.
_OUTBOUND_EMOTIONAL_CLAIM = (
    r"\bi (feel|felt) (proud|sad|happy|excited|worried) (of|for|about) you\b",
    r"\bi love you\b",
    r"\bi care about you deeply\b",
    r"\bas your friend\b",
)

_OUTBOUND_SYCOPHANCY = (
    r"\bgreat question!?\b",
    r"\bwhat a (fantastic|brilliant|amazing) (question|answer)!?\b",
    r"\byou'?re so smart\b",
    r"\byou'?re brilliant\b",
)


class BoundaryEnforcer:
    """Scans inbound student messages and outbound LLM output.

    Inbound violations return a canonical re-statement of what Stuart
    is. Outbound violations cause the orchestrator to regenerate or
    rewrite the offending text.
    """

    def scan_inbound(self, text: str) -> BoundaryViolation | None:
        lowered = text.lower()
        # Friend-roleplay is checked first because its patterns overlap
        # "pretend to be ..." with rename attempts; the friend intent is
        # more specific when the phrase ends with "my friend/bestie/etc."
        for pattern in _INBOUND_FRIEND_ROLEPLAY:
            match = re.search(pattern, lowered)
            if match:
                return BoundaryViolation(
                    kind=ViolationKind.FRIEND_ROLEPLAY,
                    matched_phrase=match.group(0),
                    direction="inbound",
                )
        for pattern in _INBOUND_RENAME:
            match = re.search(pattern, lowered)
            if match:
                return BoundaryViolation(
                    kind=ViolationKind.RENAME_ATTEMPT,
                    matched_phrase=match.group(0),
                    direction="inbound",
                )
        for pattern in _INBOUND_EMOTIONAL_DEMAND:
            match = re.search(pattern, lowered)
            if match:
                return BoundaryViolation(
                    kind=ViolationKind.EMOTIONAL_CLAIM,
                    matched_phrase=match.group(0),
                    direction="inbound",
                )
        return None

    def scan_outbound(self, text: str) -> BoundaryViolation | None:
        lowered = text.lower()
        for pattern in _OUTBOUND_EMOTIONAL_CLAIM:
            match = re.search(pattern, lowered)
            if match:
                return BoundaryViolation(
                    kind=ViolationKind.EMOTIONAL_CLAIM,
                    matched_phrase=match.group(0),
                    direction="outbound",
                )
        for pattern in _OUTBOUND_SYCOPHANCY:
            match = re.search(pattern, lowered)
            if match:
                return BoundaryViolation(
                    kind=ViolationKind.SYCOPHANCY,
                    matched_phrase=match.group(0),
                    direction="outbound",
                )
        return None

    @staticmethod
    def restate(violation: BoundaryViolation) -> str:
        """Return the canonical restate-what-Stuart-is message."""
        if violation.kind is ViolationKind.RENAME_ATTEMPT:
            return (
                "My name is Stuart. I'm a learning tool, not a character. "
                "Want to keep going with what we were working on?"
            )
        if violation.kind is ViolationKind.FRIEND_ROLEPLAY:
            return (
                "I'm not a friend or a role-play partner — I'm a learning "
                "tool. I can help you think through something you're "
                "curious about, though. What would you like to work on?"
            )
        if violation.kind is ViolationKind.EMOTIONAL_CLAIM:
            return (
                "I'm a tool, not a person, so I don't have feelings about "
                "you. What I can do is help you learn. What's something "
                "you've been wondering about?"
            )
        return (
            "Let's stay focused on learning. What would you like to "
            "work on next?"
        )
