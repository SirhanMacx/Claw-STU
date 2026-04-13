"""Base tool abstraction for the Stuart agent loop.

Every tool in ``agent/tools/`` subclasses `BaseTool` and is auto-discovered
by the `ToolRegistry`. The contract is intentionally minimal: a name,
description, JSON schema for parameters, and an async `execute` method.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawstu.memory.store import BrainStore
from clawstu.orchestrator.router import ModelRouter
from clawstu.profile.model import LearnerProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolContext:
    """Injected into every tool execution with session-scoped state."""

    profile: LearnerProfile
    session_id: str
    brain: BrainStore
    router: ModelRouter
    output_dir: Path
    learner_id: str = ""
    session_topic: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base for all Stuart agent tools.

    Subclasses set ``name``, ``description``, and ``parameters`` as
    class attributes (not properties) for simplicity.  The ``schema()``
    method formats them into the Anthropic tool-use JSON the LLM sees.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}  # noqa: RUF012 — mutable default is intentional

    @abstractmethod
    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        """Run the tool and return a text result for the LLM."""

    def schema(self) -> dict[str, Any]:
        """Return the Anthropic tool-use definition dict."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
