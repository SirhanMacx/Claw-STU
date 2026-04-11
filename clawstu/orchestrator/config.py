"""AppConfig and TaskRoute — the provider-layer configuration contract.

AppConfig is loaded from (in priority order):
  1. Environment variables
  2. ~/.claw-stu/secrets.json (0600 on POSIX; WARN on Windows)
  3. Defaults defined in this module

See docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md
§4.2.4 and §4.2.5 for the authoritative default routing table.

Tasks 6-8 add the env/file loader (`load_config`) and the data
directory bootstrap (`ensure_data_dir`). This module currently
ships only the data model and the default-routing helper.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clawstu.orchestrator.task_kinds import TaskKind


class TaskRoute(BaseModel):
    """One (provider, model) assignment for a TaskKind.

    Kept as a named pydantic model so the config file reads cleanly:
    {TaskKind: {provider: ..., model: ..., max_tokens: ..., temperature: ...}}
    rather than opaque tuples.
    """

    model_config = ConfigDict(frozen=True)

    provider: str  # "ollama" | "anthropic" | "openai" | "openrouter" | "echo"
    model: str     # provider-specific model id
    max_tokens: int = 1024
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


def _default_task_routing() -> dict[TaskKind, TaskRoute]:
    """The shipped defaults per design spec §4.2.4.

    The reader-friendly version of this table:

    - SOCRATIC_DIALOGUE   -> ollama / llama3.2         (short, local, free)
    - BLOCK_GENERATION    -> openrouter / glm-4.5-air  (prose quality)
    - CHECK_GENERATION    -> openrouter / glm-4.5-air  (structured JSON)
    - RUBRIC_EVALUATION   -> anthropic / haiku-4-5     (accuracy-critical)
    - PATHWAY_PLANNING    -> openrouter / glm-4.5-air  (small JSON)
    - CONTENT_CLASSIFY    -> ollama / llama3.2         (safety: never network)
    - DREAM_CONSOLIDATION -> openrouter / glm-4.5-air  (batch overnight)
    """
    return {
        TaskKind.SOCRATIC_DIALOGUE: TaskRoute(
            provider="ollama", model="llama3.2",
        ),
        TaskKind.BLOCK_GENERATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.CHECK_GENERATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.RUBRIC_EVALUATION: TaskRoute(
            provider="anthropic", model="claude-haiku-4-5",
        ),
        TaskKind.PATHWAY_PLANNING: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.CONTENT_CLASSIFY: TaskRoute(
            provider="ollama", model="llama3.2",
        ),
        TaskKind.DREAM_CONSOLIDATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
    }


class AppConfig(BaseModel):
    """The Claw-STU runtime configuration.

    Loaded via `load_config()` — see Tasks 6-8. Validation is strict:
    missing provider API keys are fine (falls through the chain),
    but an unknown provider name in `fallback_chain` or `task_routing`
    is a hard error raised by the router at construction time (Phase 2).
    """

    model_config = ConfigDict(validate_assignment=True)

    data_dir: Path = Field(
        default_factory=lambda: Path.home() / ".claw-stu",
        description="Root directory for secrets, brain, SQLite DB, cached models.",
    )
    primary_provider: str = "ollama"
    fallback_chain: tuple[str, ...] = (
        "ollama",
        "openai",
        "anthropic",
        "openrouter",
    )
    task_routing: dict[TaskKind, TaskRoute] = Field(
        default_factory=_default_task_routing,
    )
    # Provider connection settings.
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Session-layer settings.
    session_cache_size: int = 1024
