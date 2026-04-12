"""LLM orchestration layer.

Thin seam between the deterministic session runner and the (optional)
LLM provider. Everything in this module must remain optional — the
MVP session loop runs end-to-end without a single LLM call, and
orchestrator is only invoked when the session runner asks for
LLM-generated enrichment (e.g., Socratic dialogue continuation,
bespoke feedback).
"""

from clawstu.orchestrator.chain import ReasoningChain
from clawstu.orchestrator.config import (
    AppConfig,
    TaskRoute,
    ensure_data_dir,
    load_config,
)
from clawstu.orchestrator.live_content import (
    LiveContentGenerator,
    LiveGenerationError,
)
from clawstu.orchestrator.prompts import PromptLibrary
from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.provider_google import GoogleProvider
from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.providers import (
    EchoProvider,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
)
from clawstu.orchestrator.router import ModelRouter, RouterConstructionError
from clawstu.orchestrator.task_kinds import TaskKind

__all__ = [
    "AnthropicProvider",
    "AppConfig",
    "EchoProvider",
    "GoogleProvider",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LiveContentGenerator",
    "LiveGenerationError",
    "ModelRouter",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "PromptLibrary",
    "ProviderError",
    "ReasoningChain",
    "RouterConstructionError",
    "TaskKind",
    "TaskRoute",
    "ensure_data_dir",
    "load_config",
]
