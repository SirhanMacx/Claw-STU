"""Engagement: session lifecycle and modality rotation."""

from src.engagement.modality import ModalityRotator
from src.engagement.session import (
    Session,
    SessionDirective,
    SessionPhase,
    SessionRunner,
    TeachBlockResult,
)
from src.engagement.signals import EngagementSignals

__all__ = [
    "EngagementSignals",
    "ModalityRotator",
    "Session",
    "SessionDirective",
    "SessionPhase",
    "SessionRunner",
    "TeachBlockResult",
]
