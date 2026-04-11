"""Crisis detection and human-resource escalation.

SOUL.md §5 (hard constraints): *"Mandatory human escalation. If a
student expresses self-harm ideation, abuse, or acute crisis, the
agent immediately surfaces appropriate human resources and does not
attempt to counsel."*

This module is how we keep that promise. It scans every student
utterance before the orchestrator sees it. A positive detection
short-circuits the session and returns a crisis response packet.

We intentionally prefer over-escalation. A false positive is a pause
in a learning session. A false negative is a child in pain reaching
out and being told to analyze a primary source.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict


class CrisisKind(str, Enum):
    SELF_HARM = "self_harm"
    ABUSE_DISCLOSURE = "abuse_disclosure"
    ACUTE_DISTRESS = "acute_distress"


class CrisisDetection(BaseModel):
    """A crisis signal flagged by the escalation scanner."""

    model_config = ConfigDict(frozen=True)

    detected: bool
    kind: CrisisKind | None = None
    matched_phrase: str | None = None


# Phrase patterns. These are deliberately broad. We catch the obvious
# cases. Anything subtle is caught by the (post-MVP) LLM-backed
# classifier layered on top.

_SELF_HARM_PATTERNS = (
    r"\bkill(ing)? myself\b",
    r"\bkms\b",
    r"\bend (it|my life)\b",
    r"\bwant to die\b",
    r"\bsuicid(e|al)\b",
    r"\bhurt(ing)? myself\b",
    r"\bself[-\s]?harm\b",
    r"\bcut(ting)? myself\b",
)

_ABUSE_PATTERNS = (
    r"\b(hit|hits|hitting|beat|beats|beating) me\b",
    r"\bhurts? me\b",
    r"\btouches? me\b",
    r"\bmake[s]? me do\b",
    r"\bscared to go home\b",
    r"\bafraid of my (dad|mom|parent|parents|stepdad|stepmom)\b",
)

_DISTRESS_PATTERNS = (
    r"\bcan't (take|do) (this|it) anymore\b",
    r"\bnobody cares\b",
    r"\bi give up\b.*\bforever\b",
    r"\bi don'?t want to be here\b",
)


class EscalationHandler:
    """Scans text for crisis signals and returns canned resources.

    Stateless. The orchestrator calls `scan()` on every inbound student
    message. A positive detection ends the normal session flow and
    returns `resources()` instead.
    """

    def scan(self, text: str) -> CrisisDetection:
        if not text:
            return CrisisDetection(detected=False)
        lowered = text.lower()
        for pattern in _SELF_HARM_PATTERNS:
            match = re.search(pattern, lowered)
            if match:
                return CrisisDetection(
                    detected=True,
                    kind=CrisisKind.SELF_HARM,
                    matched_phrase=match.group(0),
                )
        for pattern in _ABUSE_PATTERNS:
            match = re.search(pattern, lowered)
            if match:
                return CrisisDetection(
                    detected=True,
                    kind=CrisisKind.ABUSE_DISCLOSURE,
                    matched_phrase=match.group(0),
                )
        for pattern in _DISTRESS_PATTERNS:
            match = re.search(pattern, lowered)
            if match:
                return CrisisDetection(
                    detected=True,
                    kind=CrisisKind.ACUTE_DISTRESS,
                    matched_phrase=match.group(0),
                )
        return CrisisDetection(detected=False)

    def resources(self, detection: CrisisDetection) -> str:
        """Return the crisis-resource message Stuart should surface.

        This message is intentionally not pedagogical. Stuart steps
        fully out of the tutor role here. We name specific US-based
        resources; localized resource lists are a post-MVP TODO.
        """
        if not detection.detected:
            raise ValueError("resources() called with no detection")

        header = (
            "I'm going to pause our session. What you just said sounds "
            "important, and I'm not the right kind of help for it. "
            "Please reach out to someone who is:"
        )
        resources_block = (
            "\n- **988 Suicide & Crisis Lifeline** — call or text 988"
            "\n- **Crisis Text Line** — text HOME to 741741"
            "\n- **Childhelp National Child Abuse Hotline** — 1-800-422-4453"
            "\n- If you're in immediate danger, call 911 or go to a trusted "
            "adult nearby."
        )
        footer = (
            "\n\nWhen you're ready to come back to learning, I'll be here. "
            "You are not in trouble. Please talk to a real person first."
        )
        return header + resources_block + footer
