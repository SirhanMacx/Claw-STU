"""ModelRouter — per-TaskKind provider + model resolution.

Stateless. Holds a resolved map from `TaskKind` to `(LLMProvider,
model_name)` at construction time. Falls through `AppConfig.fallback_chain`
if the primary provider for a task is not in the supplied providers dict,
ending at `EchoProvider` as a guaranteed last-resort floor.

Reachability probing (can the server actually be reached?) is NOT done
here — that's `clawstu doctor --ping`'s job. The router only knows
about presence/absence of a provider in the `providers` dict, which
callers build from `load_config()` results (missing api_key => missing
provider).
"""
from __future__ import annotations

from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import LLMProvider
from clawstu.orchestrator.task_kinds import TaskKind


class RouterConstructionError(RuntimeError):
    """Raised when the router cannot be constructed.

    Currently the only way this fires is if `providers` does not contain
    an `"echo"` entry. Echo is the fallback-chain floor; without it, any
    task whose fallback chain exhausts has nowhere to go and the router
    would silently fail at `for_task` time. Loud-fail at construction.
    """


class ModelRouter:
    """Stateless resolver: TaskKind -> (LLMProvider, model_name).

    Construction resolves every TaskKind to the first provider in its
    fallback chain that is actually available. The resolved map is
    cached for the lifetime of the router.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        providers: dict[str, LLMProvider],
    ) -> None:
        if "echo" not in providers:
            raise RouterConstructionError(
                "ModelRouter requires an 'echo' provider as the "
                "fallback-chain floor; got providers: "
                f"{sorted(providers.keys())}"
            )
        self._resolved: dict[TaskKind, tuple[LLMProvider, str]] = {}
        for kind, route in config.task_routing.items():
            provider, model = self._resolve_one(
                primary=(route.provider, route.model),
                fallback_chain=config.fallback_chain,
                providers=providers,
            )
            self._resolved[kind] = (provider, model)

    def for_task(self, kind: TaskKind) -> tuple[LLMProvider, str]:
        """Return the resolved (provider, model) for this task kind.

        Always succeeds — every TaskKind is resolved at construction
        time and cached. An unknown TaskKind raises KeyError, which is
        a programmer error (every enum value must be in the routing
        table by spec §4.2.4).
        """
        return self._resolved[kind]

    def _resolve_one(
        self,
        *,
        primary: tuple[str, str],
        fallback_chain: tuple[str, ...],
        providers: dict[str, LLMProvider],
    ) -> tuple[LLMProvider, str]:
        """Walk primary -> fallback_chain -> echo, returning the first
        provider that exists in `providers`.

        Preserves the primary's model name when the primary is available.
        When we fall through to a chain provider, we still use the task's
        configured model (which may or may not be valid for that
        provider — but the router is not in the business of validating
        model strings against provider capabilities; that's the provider's
        job at `.complete()` time).
        """
        primary_name, primary_model = primary
        if primary_name in providers:
            return providers[primary_name], primary_model
        for name in fallback_chain:
            if name == primary_name:
                continue  # already tried
            if name in providers:
                return providers[name], primary_model
        # Last-resort floor: echo is guaranteed to be present by
        # construction-time check in __init__.
        return providers["echo"], primary_model
