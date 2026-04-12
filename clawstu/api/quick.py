"""Quick-ask endpoint for the Chrome extension and other lightweight clients.

``POST /api/ask`` accepts a free-text question and returns a Socratic
response without requiring a full session lifecycle. This is the backend
for the "Ask Stuart" Chrome extension and any other stateless Q&A
surface.

The endpoint runs the question through the inbound safety gate, then
returns a placeholder Socratic response. The real LLM-backed Socratic
dialogue hooks into the same chain as ``clawstu ask``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from clawstu.safety.boundaries import BoundaryEnforcer
from clawstu.safety.escalation import EscalationHandler
from clawstu.safety.gate import InboundSafetyGate

router = APIRouter(prefix="/api", tags=["quick"])

_GATE = InboundSafetyGate(EscalationHandler(), BoundaryEnforcer())


class AskRequest(BaseModel):
    """Payload for ``POST /api/ask``."""

    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    """Response from ``POST /api/ask``."""

    response: str
    crisis: bool = False


@router.post("/ask", response_model=AskResponse)
def quick_ask(request: AskRequest) -> AskResponse:
    """One-shot Socratic Q&A — no session required.

    Runs the inbound safety gate on the question text. If a crisis is
    detected, returns the escalation resources. Otherwise returns a
    Socratic placeholder (Phase 5). The real LLM-backed response lands
    in Phase 6+.
    """
    decision = _GATE.scan(request.question)
    if decision.action == "crisis":
        assert decision.crisis_detection is not None
        resources = _GATE.escalation.resources(decision.crisis_detection)
        return AskResponse(response=resources, crisis=True)
    if decision.action == "boundary":
        return AskResponse(
            response="I'm Stuart, a learning tool. Let's keep things on-topic.",
        )
    return AskResponse(
        response=(
            "Good question. Let me think about that with you.\n\n"
            "What do you already know about this topic? "
            "That will help me pitch my answer at the right level."
        ),
    )
