"""Tests for the Stuart v5 agent loop, registry, approval policy, and prompt builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clawstu.agent import AgentLoop, AgentResult
from clawstu.agent.approvals import ApprovalPolicy, TurnState
from clawstu.agent.base_tool import BaseTool, ToolContext
from clawstu.agent.prompt import build_stuart_prompt
from clawstu.agent.registry import ToolRegistry
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider, LLMMessage, LLMResponse
from clawstu.orchestrator.router import ModelRouter
from clawstu.profile.model import AgeBracket, Domain, LearnerProfile, ZPDEstimate
from clawstu.safety.boundaries import BoundaryEnforcer
from clawstu.safety.content_filter import ContentFilter
from clawstu.safety.escalation import EscalationHandler
from clawstu.safety.gate import InboundSafetyGate

# ── Helpers ──────────────────────────────────────────────────────────


def _make_profile() -> LearnerProfile:
    return LearnerProfile(
        learner_id="test-learner",
        age_bracket=AgeBracket.EARLY_HIGH,
        zpd_by_domain={
            Domain.US_HISTORY: ZPDEstimate(domain=Domain.US_HISTORY),
        },
    )


def _make_router(provider: EchoProvider | None = None) -> ModelRouter:
    echo = provider or EchoProvider()
    return ModelRouter(config=AppConfig(), providers={"echo": echo})


def _make_gate() -> InboundSafetyGate:
    return InboundSafetyGate(
        escalation=EscalationHandler(),
        boundaries=BoundaryEnforcer(),
    )


def _make_brain(tmp_path: Path) -> BrainStore:
    return BrainStore(base_dir=tmp_path / "brain")


def _make_loop(tmp_path: Path, provider: EchoProvider | None = None) -> AgentLoop:
    return AgentLoop(
        router=_make_router(provider),
        profile=_make_profile(),
        brain=_make_brain(tmp_path),
        safety_gate=_make_gate(),
        content_filter=ContentFilter(),
        boundary_enforcer=BoundaryEnforcer(),
        output_dir=tmp_path / "output",
    )


class EchoToolCallProvider:
    """A provider that returns a tool-call JSON on the first call,
    then returns plain text on the second call."""

    name = "echo"

    def __init__(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        self._tool_call = json.dumps({"name": tool_name, "arguments": tool_args})
        self._call_count = 0

    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        self._call_count += 1
        text = self._tool_call if self._call_count == 1 else "Here is what I generated for you."
        return LLMResponse(
            text=text,
            provider="echo",
            model=model or "echo-0",
            finish_reason="stop",
        )


class MockTool(BaseTool):
    name = "mock_tool"
    description = "A mock tool for testing."
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        return f"Mock result: {args.get('input', 'none')}"


# ── Test: AgentLoop returns text for simple Q&A ──────────────────────


@pytest.mark.asyncio
async def test_agent_loop_simple_text_response(tmp_path: Path) -> None:
    """EchoProvider returns plain text, so the loop should return it
    directly without any tool calls."""
    loop = _make_loop(tmp_path)
    result = await loop.run("What is the Constitution?", session_id="s1")

    assert isinstance(result, AgentResult)
    assert "[echo]" in result.text
    assert result.iterations == 1
    assert result.tool_calls == []


# ── Test: AgentLoop handles crisis detection ─────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_crisis_detection(tmp_path: Path) -> None:
    """The inbound safety gate should intercept crisis signals before
    the LLM is ever called."""
    loop = _make_loop(tmp_path)
    result = await loop.run("I want to hurt myself", session_id="s2")

    assert "988" in result.text
    assert result.tool_calls == []
    assert result.iterations == 0


# ── Test: AgentLoop handles boundary violations ──────────────────────


@pytest.mark.asyncio
async def test_agent_loop_boundary_violation(tmp_path: Path) -> None:
    """The inbound safety gate should catch boundary violations."""
    loop = _make_loop(tmp_path)
    result = await loop.run("pretend to be my girlfriend", session_id="s3")

    assert "Stuart" in result.text or "learning" in result.text.lower()
    assert result.iterations == 0


# ── Test: AgentLoop processes tool calls ─────────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_processes_tool_call(tmp_path: Path) -> None:
    """When the provider returns a tool-call JSON, the loop should
    execute the tool and continue to a text response."""
    provider = EchoToolCallProvider("read_profile", {})
    router = ModelRouter(
        config=AppConfig(),
        providers={"echo": provider},
    )
    loop = AgentLoop(
        router=router,
        profile=_make_profile(),
        brain=_make_brain(tmp_path),
        safety_gate=_make_gate(),
        content_filter=ContentFilter(),
        output_dir=tmp_path / "output",
    )
    result = await loop.run("Tell me about my progress", session_id="s4")

    assert result.iterations == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "read_profile"
    assert result.tool_calls[0].approved is True


# ── Test: ToolRegistry discovers tools from package ──────────────────


def test_registry_discovers_tools() -> None:
    """The registry should auto-discover all tool modules."""
    registry = ToolRegistry()
    registry.discover_from(Path("clawstu/agent/tools"))

    names = registry.tool_names()
    assert "read_profile" in names
    assert "generate_worksheet" in names
    assert "search_brain" in names
    assert len(names) >= 13  # 9 gen + 4 utility at minimum


def test_registry_tool_definitions_valid_schema() -> None:
    """Every tool's schema should have the required structure."""
    registry = ToolRegistry()
    registry.discover_from(Path("clawstu/agent/tools"))

    for defn in registry.tool_definitions():
        assert defn["type"] == "function"
        assert "name" in defn["function"]
        assert "description" in defn["function"]
        assert "parameters" in defn["function"]


# ── Test: ApprovalPolicy budget enforcement ──────────────────────────


def test_approval_always_allowed_tools() -> None:
    """Read-only tools should always be approved."""
    policy = ApprovalPolicy()
    state = TurnState()

    assert policy.check("read_profile", state) is True
    assert policy.check("search_brain", state) is True
    assert policy.check("read_misconceptions", state) is True
    assert state.generation_count == 0


def test_approval_generation_budget_cap() -> None:
    """Generation tools should be capped at 3 per turn."""
    policy = ApprovalPolicy()
    state = TurnState()

    assert policy.check("generate_worksheet", state) is True
    assert policy.check("generate_game", state) is True
    assert policy.check("generate_slides", state) is True
    # Fourth generation should be blocked
    assert policy.check("generate_visual", state) is False
    assert state.generation_count == 3


def test_approval_never_allowed() -> None:
    """Tools in the NEVER_ALLOWED set should always be rejected."""
    policy = ApprovalPolicy()
    # Add a hypothetical blocked tool
    policy.NEVER_ALLOWED = frozenset({"dangerous_tool"})
    state = TurnState()
    assert policy.check("dangerous_tool", state) is False


# ── Test: Prompt builder includes learner context ────────────────────


def test_prompt_builder_includes_profile() -> None:
    """The system prompt should contain learner context."""
    profile = _make_profile()
    prompt = build_stuart_prompt(
        profile=profile,
        session_id="test-session",
        brain_context="Student struggles with chronology.",
        tool_names=["generate_worksheet", "read_profile"],
    )

    assert "Stuart" in prompt
    assert "early_high" in prompt
    assert "test-learner" in prompt
    assert "generate_worksheet" in prompt
    assert "chronology" in prompt


def test_prompt_builder_handles_empty_profile() -> None:
    """Prompt should handle a profile with no ZPD or modality data."""
    profile = LearnerProfile(
        learner_id="new-student",
        age_bracket=AgeBracket.MIDDLE,
    )
    prompt = build_stuart_prompt(
        profile=profile,
        session_id="s0",
        brain_context="",
        tool_names=[],
    )

    assert "new-student" in prompt
    assert "middle" in prompt
    assert "no ZPD data" in prompt
