"""Approval policy for the Stuart agent loop.

Spec reference: v5 design doc section 9.

Every tool call passes through `ApprovalPolicy.check()` before
execution. Read-only tools are always allowed. Generation tools
are budget-capped at 3 per turn. Tools in the NEVER_ALLOWED set
are unconditionally blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class TurnState:
    """Mutable per-turn bookkeeping for the approval policy."""

    generation_count: int = 0
    tool_calls: list[str] = field(default_factory=list)


class ApprovalPolicy:
    """Decides whether a tool call is allowed to execute."""

    MAX_GENERATIONS_PER_TURN: ClassVar[int] = 3

    ALWAYS_ALLOWED: ClassVar[frozenset[str]] = frozenset({
        "read_profile",
        "search_brain",
        "read_misconceptions",
        "write_note",
        "define_learning_goals",
        "check_learning_goals",
    })

    REQUIRES_GENERATION_BUDGET: ClassVar[frozenset[str]] = frozenset({
        "generate_worksheet",
        "generate_game",
        "generate_visual",
        "generate_simulation",
        "generate_animation",
        "generate_slides",
        "generate_study_guide",
        "generate_practice_test",
        "generate_flashcards",
    })

    NEVER_ALLOWED: ClassVar[frozenset[str]] = frozenset()

    def check(self, tool_name: str, turn_state: TurnState) -> bool:
        """Return True if the tool call is allowed, False otherwise."""
        if tool_name in self.NEVER_ALLOWED:
            return False
        if tool_name in self.ALWAYS_ALLOWED:
            return True
        if tool_name in self.REQUIRES_GENERATION_BUDGET:
            if turn_state.generation_count >= self.MAX_GENERATIONS_PER_TURN:
                return False
            turn_state.generation_count += 1
        turn_state.tool_calls.append(tool_name)
        return True
