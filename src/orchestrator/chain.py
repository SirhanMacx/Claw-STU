"""Multi-step reasoning chains.

A `ReasoningChain` is a tiny composition helper that runs a prompt
through a provider, applies the outbound boundary filter, and returns
the result — or a safe fallback if the filter rejects the output.

Keeping this layer small is deliberate. The session runner does not
depend on any LLM call to function. Chains are *enrichment*: if a
provider is unavailable, the session loop still completes.
"""

from __future__ import annotations

from src.orchestrator.prompts import PromptLibrary
from src.orchestrator.providers import LLMMessage, LLMProvider, LLMResponse, ProviderError
from src.safety.boundaries import BoundaryEnforcer


class ReasoningChain:
    """One-shot prompt runner with boundary enforcement.

    - `provider` does the LLM call.
    - `prompts` resolves template names into text.
    - `boundaries` scans the outbound text and rejects sycophancy or
      emotional claims before they reach the student.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompts: PromptLibrary | None = None,
        boundaries: BoundaryEnforcer | None = None,
    ) -> None:
        self._provider = provider
        self._prompts = prompts or PromptLibrary()
        self._boundaries = boundaries or BoundaryEnforcer()

    def run_template(
        self,
        template_name: str,
        *,
        user_input: str,
        template_vars: dict[str, object] | None = None,
    ) -> str:
        """Render a template, call the provider, filter the output.

        Returns the sanitized output text. Raises `ProviderError` if
        the provider fails. On outbound boundary violation, returns a
        canonical restatement instead of the generated text.
        """
        template = self._prompts.get(template_name)
        rendered = template.render(**(template_vars or {}))
        messages = [LLMMessage(role="user", content=rendered)]
        try:
            response: LLMResponse = self._provider.complete(
                system=self._prompts.soul_system(),
                messages=messages,
            )
        except ProviderError:
            raise
        text = response.text
        violation = self._boundaries.scan_outbound(text)
        if violation is not None:
            return self._boundaries.restate(violation)
        return text

    def ask(self, user_input: str) -> str:
        """Run an ad-hoc prompt. Used by free-form Socratic dialogue."""
        messages = [LLMMessage(role="user", content=user_input)]
        try:
            response = self._provider.complete(
                system=self._prompts.soul_system(),
                messages=messages,
            )
        except ProviderError:
            raise
        violation = self._boundaries.scan_outbound(response.text)
        if violation is not None:
            return self._boundaries.restate(violation)
        return response.text
