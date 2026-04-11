"""Multi-step reasoning chains.

A `ReasoningChain` is a tiny composition helper that runs a prompt
through a provider, applies the outbound boundary filter, and returns
the result — or a safe fallback if the filter rejects the output.

Keeping this layer small is deliberate. The session runner does not
depend on any LLM call to function. Chains are *enrichment*: if a
provider is unavailable, the session loop still completes.
"""

from __future__ import annotations

from clawstu.orchestrator.prompts import PromptLibrary
from clawstu.orchestrator.providers import LLMMessage, LLMResponse, ProviderError
from clawstu.orchestrator.router import ModelRouter
from clawstu.orchestrator.task_kinds import TaskKind
from clawstu.safety.boundaries import BoundaryEnforcer


class ReasoningChain:
    """One-shot prompt runner with boundary enforcement.

    - `router` resolves (provider, model) per TaskKind for each call.
    - `prompts` resolves template names into text.
    - `boundaries` scans the outbound text and rejects sycophancy or
      emotional claims before they reach the student.
    """

    def __init__(
        self,
        *,
        router: ModelRouter,
        prompts: PromptLibrary | None = None,
        boundaries: BoundaryEnforcer | None = None,
    ) -> None:
        self._router = router
        self._prompts = prompts or PromptLibrary()
        self._boundaries = boundaries or BoundaryEnforcer()

    async def run_template(
        self,
        template_name: str,
        *,
        user_input: str,
        template_vars: dict[str, object] | None = None,
        task_kind: TaskKind = TaskKind.SOCRATIC_DIALOGUE,
    ) -> str:
        """Render a template, call the provider resolved for `task_kind`,
        filter the output. See spec §4.2.3 for routing semantics.
        """
        template = self._prompts.get(template_name)
        rendered = template.render(**(template_vars or {}))
        messages = [LLMMessage(role="user", content=rendered)]
        provider, model = self._router.for_task(task_kind)
        try:
            response: LLMResponse = await provider.complete(
                system=self._prompts.soul_system(),
                messages=messages,
                model=model,
            )
        except ProviderError:
            raise
        text = response.text
        violation = self._boundaries.scan_outbound(text)
        if violation is not None:
            return self._boundaries.restate(violation)
        return text

    async def ask(
        self,
        user_input: str,
        *,
        task_kind: TaskKind = TaskKind.SOCRATIC_DIALOGUE,
    ) -> str:
        """Run an ad-hoc prompt. Used by free-form Socratic dialogue."""
        messages = [LLMMessage(role="user", content=user_input)]
        provider, model = self._router.for_task(task_kind)
        try:
            response = await provider.complete(
                system=self._prompts.soul_system(),
                messages=messages,
                model=model,
            )
        except ProviderError:
            raise
        violation = self._boundaries.scan_outbound(response.text)
        if violation is not None:
            return self._boundaries.restate(violation)
        return response.text
