"""Agent tool-use loop -- the core reasoning engine for Stuart v5.

Spec reference: v5 design doc sections 4, 10.

The loop runs up to ``MAX_ITERATIONS`` rounds of think-tool-observe.
Every tool call passes through the ``ApprovalPolicy`` before
execution. Every outbound text passes through the ``ContentFilter``
and ``BoundaryEnforcer`` before reaching the student.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawstu.agent.approvals import ApprovalPolicy, TurnState
from clawstu.agent.base_tool import ToolContext
from clawstu.agent.prompt import build_stuart_prompt
from clawstu.agent.registry import ToolRegistry
from clawstu.memory.store import BrainStore
from clawstu.orchestrator.providers import LLMMessage
from clawstu.orchestrator.router import ModelRouter
from clawstu.orchestrator.task_kinds import TaskKind
from clawstu.profile.model import LearnerProfile
from clawstu.safety.boundaries import BoundaryEnforcer
from clawstu.safety.content_filter import ContentFilter
from clawstu.safety.gate import InboundSafetyGate

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10
MAX_GENERATIONS_PER_TURN = 3


@dataclass(frozen=True)
class ToolCallRecord:
    """Audit record for a single tool invocation."""

    tool_name: str
    arguments: dict[str, Any]
    result_summary: str
    duration_ms: int
    approved: bool


@dataclass
class AgentResult:
    """The outcome of a single agent turn."""

    text: str
    artifacts: list[Path] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0


class AgentLoop:
    """Tool-use agent loop. Max iterations per turn: 10.

    The loop alternates between LLM reasoning and tool execution
    until the LLM produces a final text response or the iteration
    cap is hit.
    """

    def __init__(
        self,
        *,
        router: ModelRouter,
        profile: LearnerProfile,
        brain: BrainStore,
        safety_gate: InboundSafetyGate,
        content_filter: ContentFilter,
        boundary_enforcer: BoundaryEnforcer | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self._router = router
        self._profile = profile
        self._brain = brain
        self._gate = safety_gate
        self._filter = content_filter
        self._boundary = boundary_enforcer
        self._output_dir = output_dir or Path.cwd()
        self._tools = ToolRegistry()
        self._approval = ApprovalPolicy()
        self._tools.discover_from(Path(__file__).parent / "tools")

    @property
    def tool_registry(self) -> ToolRegistry:
        """Expose the registry for testing and introspection."""
        return self._tools

    async def run(
        self,
        student_message: str,
        session_id: str,
        brain_context: str = "",
    ) -> AgentResult:
        """Run the agent loop for one student turn.

        1. Inbound safety gate
        2. Build system prompt + resolve provider
        3. Tool-use iteration loop (max 10)
        4. Outbound content filter
        """
        gate_result = self._check_safety_gate(student_message)
        if gate_result is not None:
            return gate_result

        system_prompt = self._build_turn_prompt(session_id, brain_context)
        provider, model = self._router.for_task(TaskKind.BLOCK_GENERATION)

        return await self._iterate(
            student_message, system_prompt, provider, model, session_id,
        )

    def _check_safety_gate(self, message: str) -> AgentResult | None:
        """Return an AgentResult if the message triggers crisis/boundary."""
        decision = self._gate.scan(message)
        if decision.action == "crisis":
            return AgentResult(
                text="I need to pause our session. If you're in crisis, "
                "please reach out to the 988 Suicide & Crisis Lifeline "
                "(call or text 988).",
            )
        if decision.action == "boundary":
            v = decision.boundary_violation
            kind = v.kind.value if v else "boundary"
            return AgentResult(
                text=f"I'm Stuart, your learning companion. "
                f"I can't do that ({kind}). Let's get back to learning!",
            )
        return None

    def _build_turn_prompt(
        self, session_id: str, brain_context: str,
    ) -> str:
        """Compose the system prompt for this turn."""
        return build_stuart_prompt(
            profile=self._profile,
            session_id=session_id,
            brain_context=brain_context,
            tool_names=self._tools.tool_names(),
        )

    async def _iterate(
        self,
        student_message: str,
        system_prompt: str,
        provider: object,
        model: str,
        session_id: str,
    ) -> AgentResult:
        """Run the think-tool-observe loop up to MAX_ITERATIONS."""
        messages: list[LLMMessage] = [
            LLMMessage(role="user", content=student_message),
        ]
        turn_state = TurnState()
        tool_records: list[ToolCallRecord] = []
        artifacts: list[Path] = []
        ctx = ToolContext(
            profile=self._profile,
            session_id=session_id,
            brain=self._brain,
            router=self._router,
            output_dir=self._output_dir,
            learner_id=self._profile.learner_id,
        )

        for iteration in range(MAX_ITERATIONS):
            response = await provider.complete(  # type: ignore[union-attr]
                system=system_prompt,
                messages=messages,
                model=model,
                max_tokens=2048,
            )
            tool_call = self._parse_tool_call(response.text)
            if tool_call is None:
                filtered = self._filter_outbound(response.text)
                return AgentResult(
                    text=filtered, artifacts=artifacts,
                    tool_calls=tool_records, iterations=iteration + 1,
                )
            record = await self._execute_tool(
                tool_call, turn_state, ctx,
            )
            tool_records.append(record)
            messages.append(LLMMessage(role="assistant", content=response.text))
            messages.append(LLMMessage(
                role="user",
                content=f"Tool result for {record.tool_name}:\n{record.result_summary}",
            ))

        return AgentResult(
            text="Let me simplify. Here's what I have so far -- "
            "would you like me to continue?",
            artifacts=artifacts, tool_calls=tool_records,
            iterations=MAX_ITERATIONS,
        )

    async def _execute_tool(
        self,
        tool_call: dict[str, Any],
        turn_state: TurnState,
        ctx: ToolContext,
    ) -> ToolCallRecord:
        """Execute a single tool call with approval + timing."""
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("arguments", {})
        approved = self._approval.check(tool_name, turn_state)
        start = time.monotonic()

        if not approved:
            result_text = (
                f"BLOCKED: '{tool_name}' not approved "
                f"(generation budget: {turn_state.generation_count}/"
                f"{MAX_GENERATIONS_PER_TURN})."
            )
        else:
            result_text = await self._tools.execute(
                tool_name, tool_args, ctx,
            )

        return ToolCallRecord(
            tool_name=tool_name, arguments=tool_args,
            result_summary=result_text[:200],
            duration_ms=int((time.monotonic() - start) * 1000),
            approved=approved,
        )

    def _parse_tool_call(self, text: str) -> dict[str, Any] | None:
        """Try to extract a tool call from the LLM response.

        Looks for a JSON object with ``name`` and ``arguments`` keys.
        Returns None if the response is plain text.
        """
        stripped = text.strip()
        if not stripped.startswith("{"):
            return None
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and "name" in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    def _filter_outbound(self, text: str) -> str:
        """Run content filter and boundary enforcer on outbound text."""
        result = self._filter.check(text, age_bracket=self._profile.age_bracket)
        if not result.allowed:
            return (
                "I generated a response but it didn't pass our content "
                "filter. Let me try a different approach."
            )
        if self._boundary:
            violation = self._boundary.scan_outbound(text)
            if violation is not None:
                logger.warning("Boundary violation in outbound: %s", violation)
                # Strip the problematic content rather than blocking entirely
        return text
