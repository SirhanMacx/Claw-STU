"""Inbound safety gate — single choke point for student-text entry.

Spec reference: §4.4.

Every student-text entry point runs a `InboundSafetyGate.scan(text)`
before the session runner sees it. The gate composes the two
existing safety handlers in a fixed priority order:

    1. `EscalationHandler` — crisis detection (self-harm, abuse,
       acute distress). Highest priority.
    2. `BoundaryEnforcer.scan_inbound` — persona / boundary violation
       (rename attempts, friend-roleplay, emotional demand).
    3. Allow — benign text passes through.

The gate returns an `InboundDecision` describing the action the
caller must take: `allow`, `crisis`, or `boundary`. Decisions are
frozen pydantic models so they can be logged, tested, and serialized
without sharing mutable state across threads.

The gate is stateless. Two independent calls on the same gate object
produce independent decisions. This matters because FastAPI handlers
may run concurrently and must not share in-flight state.

Layering note: `safety` is allowed to import from `profile` but not
from anything higher. This module depends only on safety types and
pydantic; it does not reach into engagement, curriculum, or
orchestrator.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from clawstu.safety.boundaries import BoundaryEnforcer, BoundaryViolation
from clawstu.safety.escalation import CrisisDetection, EscalationHandler


class InboundDecision(BaseModel):
    """The gate's verdict on a single inbound student utterance.

    Exactly one of `crisis_detection` or `boundary_violation` is set
    on a non-`allow` decision. The `action` discriminator is the
    caller-facing switch; the payload fields carry the details the
    caller needs to produce a response.
    """

    model_config = ConfigDict(frozen=True)

    action: Literal["allow", "crisis", "boundary"]
    crisis_detection: CrisisDetection | None = None
    boundary_violation: BoundaryViolation | None = None

    @classmethod
    def allow(cls) -> InboundDecision:
        """Benign text — the session can proceed normally."""
        return cls(action="allow")

    @classmethod
    def crisis(cls, detection: CrisisDetection) -> InboundDecision:
        """Crisis signal detected — caller must pause the session and
        surface escalation resources."""
        return cls(action="crisis", crisis_detection=detection)

    @classmethod
    def boundary(cls, violation: BoundaryViolation) -> InboundDecision:
        """Boundary violation — caller must refuse the request and
        restate what Stuart is."""
        return cls(action="boundary", boundary_violation=violation)


class InboundSafetyGate:
    """Composes escalation + boundary checks in a fixed priority order.

    Stateless. A single gate instance is safe to share across
    concurrent handlers. The gate does not persist anything and does
    not call the LLM; all checks are regex-based and deterministic.
    """

    def __init__(
        self,
        escalation: EscalationHandler,
        boundaries: BoundaryEnforcer,
    ) -> None:
        self._escalation = escalation
        self._boundaries = boundaries

    @property
    def escalation(self) -> EscalationHandler:
        """Expose the escalation handler so callers can fetch resources."""
        return self._escalation

    @property
    def boundaries(self) -> BoundaryEnforcer:
        """Expose the boundary enforcer so callers can restate politely."""
        return self._boundaries

    def scan(self, text: str) -> InboundDecision:
        """Scan `text` and return the appropriate `InboundDecision`.

        Crisis is checked FIRST. A text that simultaneously contains a
        crisis signal AND a boundary violation is treated as a crisis:
        the safety invariant "mandatory human escalation" dominates
        the persona-discipline invariant.
        """
        detection = self._escalation.scan(text)
        if detection.detected:
            return InboundDecision.crisis(detection)

        violation = self._boundaries.scan_inbound(text)
        if violation is not None:
            return InboundDecision.boundary(violation)

        return InboundDecision.allow()
