"""Pedagogical task kinds for LLM model routing.

Every call the orchestrator makes to a provider is categorized by its
pedagogical purpose, not by its LLM characteristics. This is the key
that `ModelRouter` (Phase 2) uses to pick a concrete provider + model.

TaskKind values are the wire format for `AppConfig.task_routing`, so
renaming one is a breaking change. Test snapshot in
`tests/test_task_kinds.py::test_task_kind_members_stable_across_versions`
is the guard.
"""
from __future__ import annotations

from enum import Enum


class TaskKind(str, Enum):
    """The pedagogical jobs Stuart performs."""

    # Short, cheap, latency-sensitive. Default: local Ollama.
    SOCRATIC_DIALOGUE = "socratic_dialogue"

    # Quality-sensitive prose. Default: OpenRouter GLM 4.5 Air.
    BLOCK_GENERATION = "block_generation"

    # Structured JSON, tier-aware. Default: OpenRouter GLM 4.5 Air.
    CHECK_GENERATION = "check_generation"

    # Accuracy-critical CRQ scoring. Default: Anthropic Haiku 4.5.
    RUBRIC_EVALUATION = "rubric_evaluation"

    # Small strict-JSON concept sequence. Default: OpenRouter GLM 4.5 Air.
    PATHWAY_PLANNING = "pathway_planning"

    # Second-layer safety classification. Default: local Ollama so safety
    # never depends on a network.
    CONTENT_CLASSIFY = "content_classify"

    # Overnight compiled-truth rewrite. Batch, cost-sensitive.
    # Default: OpenRouter GLM 4.5 Air.
    DREAM_CONSOLIDATION = "dream_consolidation"
