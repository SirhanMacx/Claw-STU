"""LLM orchestration layer.

Thin seam between the deterministic session runner and the (optional)
LLM provider. Everything in this module must remain optional — the
MVP session loop runs end-to-end without a single LLM call, and
orchestrator is only invoked when the session runner asks for
LLM-generated enrichment (e.g., Socratic dialogue continuation,
bespoke feedback).
"""

from src.orchestrator.chain import ReasoningChain
from src.orchestrator.prompts import PromptLibrary
from src.orchestrator.providers import (
    EchoProvider,
    LLMProvider,
    LLMResponse,
    ProviderError,
)

__all__ = [
    "EchoProvider",
    "LLMProvider",
    "LLMResponse",
    "PromptLibrary",
    "ProviderError",
    "ReasoningChain",
]
