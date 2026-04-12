"""Quick-ask endpoint for the Chrome extension and other lightweight clients.

``POST /api/ask`` accepts a free-text question and returns a real
Socratic response via ``ReasoningChain.ask()`` without requiring a
full session lifecycle. This is the backend for the "Ask Stuart"
Chrome extension and any other stateless Q&A surface.

The endpoint runs the question through the inbound safety gate first,
then routes through the ModelRouter to the provider configured for
SOCRATIC_DIALOGUE (default: local Ollama llama3.2). Falls back to
EchoProvider if no real providers are configured.
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
async def quick_ask(request: AskRequest) -> AskResponse:
    """One-shot Socratic Q&A — no session required.

    Runs the inbound safety gate on the question text. If a crisis is
    detected, returns the escalation resources. Otherwise routes
    through ReasoningChain.ask() with TaskKind.SOCRATIC_DIALOGUE for
    a real LLM-backed response.
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
    # Real Socratic response via the orchestrator.
    try:
        from clawstu.api.main import build_providers
        from clawstu.orchestrator.chain import ReasoningChain
        from clawstu.orchestrator.config import load_config
        from clawstu.orchestrator.providers import ProviderError
        from clawstu.orchestrator.router import ModelRouter

        cfg = load_config()
        providers = build_providers(cfg)
        router_inst = ModelRouter(config=cfg, providers=providers)
        chain = ReasoningChain(router=router_inst)
        answer = await chain.ask(request.question)
        return AskResponse(response=answer)
    except (ProviderError, Exception):
        # Graceful fallback — never crash the endpoint.
        return AskResponse(
            response=(
                f"I wasn't able to generate a full answer right now. "
                f"Try again, or run `clawstu setup` to configure a provider.\n\n"
                f"Your question: {request.question}"
            ),
        )
