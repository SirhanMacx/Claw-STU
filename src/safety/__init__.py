"""Safety guardrails.

Safety is not a feature in Claw-STU. It is the foundation. Every piece
of content that touches the student passes through this layer.
"""

from src.safety.boundaries import BoundaryEnforcer, BoundaryViolation
from src.safety.content_filter import ContentDecision, ContentFilter
from src.safety.escalation import CrisisDetection, EscalationHandler

__all__ = [
    "BoundaryEnforcer",
    "BoundaryViolation",
    "ContentDecision",
    "ContentFilter",
    "CrisisDetection",
    "EscalationHandler",
]
