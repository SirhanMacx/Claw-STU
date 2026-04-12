"""Interactive setup wizard for clawstu.

Walks a student or guardian through provider selection, API key
collection, verification, and writing the result to
``~/.claw-stu/secrets.json`` with 0600 perms.

The wizard is a thin layer over :mod:`clawstu.orchestrator.config` and
the four network providers. Nothing in this module has any pedagogical
content -- it is purely configuration plumbing with friendly prompts.

Design notes
------------

* The wizard is driven through a :class:`WizardIO` protocol so tests
  can script the flow without touching real stdin/stdout. The default
  implementation (:class:`_TyperIO`) wraps :mod:`typer`'s prompt/echo
  helpers; the suite-side fake (:class:`_FakeIO` in
  ``tests/test_setup_wizard.py``) reads from a pre-loaded list.
* Real providers are constructed via a *provider factory*, also
  injectable. The default builds the production provider with a fresh
  :class:`httpx.AsyncClient`; tests pass a factory whose clients are
  backed by :class:`httpx.MockTransport` so verification ping checks
  exercise the real ``.complete()`` code path against a canned
  response.
* Verification is best-effort: a 401 from the provider becomes a
  user-facing prompt asking whether to retry or save anyway. This
  matches the way a teacher onboarding a fleet of laptops would
  expect the tool to behave -- friendly, never silently destructive.

Layering
--------

``clawstu/setup_wizard.py`` is a top-level module (sibling of
``clawstu/cli.py``). It imports from
:mod:`clawstu.orchestrator.config`, :mod:`clawstu.orchestrator.providers`,
and the four ``provider_*`` modules. It deliberately imports nothing
from ``api``, ``engagement``, ``memory``, ``persistence``, or
``scheduler`` so the CLI command stays import-cheap and side-effect-free.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx
import typer

from clawstu.orchestrator.config import AppConfig, ensure_data_dir, load_config
from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.providers import LLMMessage, LLMProvider, ProviderError

logger = logging.getLogger(__name__)


# Provider menu keys -> human label. Mirrors the typed prompt below.
_PROVIDER_MENU: tuple[tuple[str, str], ...] = (
    ("anthropic", "Anthropic (Claude -- best for rubric evaluation)"),
    ("openai", "OpenAI (GPT -- widely available)"),
    ("openrouter", "OpenRouter (access to GLM, Llama, Mistral, etc.)"),
    ("ollama", "Ollama (run locally, free, private)"),
    ("echo", "Echo (offline demo mode -- stub content only, for testing)"),
)


class SetupError(RuntimeError):
    """Raised when the wizard cannot complete.

    Today this only fires when the wizard runs in non-interactive mode
    with an unsupported flag combination (e.g. ``--provider anthropic``
    without ``--api-key``). Interactive failures bubble through the
    prompt loop instead -- the user can always abort with Ctrl+C.
    """


class WizardIO(Protocol):
    """Tests inject this so they can script the wizard flow.

    The real wizard uses :mod:`typer` under the hood; the test fake
    returns canned responses in order. The protocol is intentionally
    minimal (prompt + echo + confirm) so adding a new prompt style
    later does not silently break test fakes.
    """

    def prompt(
        self,
        text: str,
        *,
        hide_input: bool = False,
        default: str | None = None,
    ) -> str:
        """Ask the operator for a string. Echoed in plaintext unless ``hide_input``."""
        ...

    def echo(self, text: str, *, color: str | None = None) -> None:
        """Print a line to the operator. ``color`` is a typer color name."""
        ...

    def confirm(self, text: str, *, default: bool = False) -> bool:
        """Ask the operator a yes/no question."""
        ...


# A provider factory takes (name, api_key, base_url) and returns an
# LLMProvider. Tests pass a factory that returns providers backed by an
# httpx.MockTransport so the verification step is reproducible offline.
ProviderFactory = Callable[[str, str | None, str], LLMProvider]


class _TyperIO:
    """Default :class:`WizardIO` implementation backed by :mod:`typer`."""

    def prompt(
        self,
        text: str,
        *,
        hide_input: bool = False,
        default: str | None = None,
    ) -> str:
        result = typer.prompt(text, hide_input=hide_input, default=default)
        # typer.prompt returns whatever default's type is when no input is
        # given. The wizard only ever passes strings, so the runtime type
        # is always str -- but mypy needs the explicit narrow.
        return str(result)

    def echo(self, text: str, *, color: str | None = None) -> None:
        if color is None:
            typer.echo(text)
        else:
            typer.secho(text, fg=color)

    def confirm(self, text: str, *, default: bool = False) -> bool:
        return bool(typer.confirm(text, default=default))


def _default_provider_factory(
    name: str, api_key: str | None, base_url: str,
) -> LLMProvider:
    """Build the production provider for ``name``.

    Raises :class:`ValueError` if ``name`` is not one of the four real
    providers. The wizard never calls this for ``echo`` -- echo writes
    directly without verification.
    """
    if name == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=base_url)
    if name == "openai":
        return OpenAIProvider(api_key=api_key, base_url=base_url)
    if name == "openrouter":
        return OpenRouterProvider(api_key=api_key, base_url=base_url)
    if name == "ollama":
        return OllamaProvider(base_url=base_url, api_key=api_key)
    raise ValueError(f"unknown provider for factory: {name!r}")


def run_setup(
    *,
    interactive: bool = True,
    io: WizardIO | None = None,
    provider_override: str | None = None,
    api_key_override: str | None = None,
    base_url_override: str | None = None,
    provider_factory: ProviderFactory | None = None,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    """Run the wizard. Returns the dict that was written to ``secrets.json``.

    Parameters
    ----------
    interactive:
        When ``True`` (default) the wizard prompts the operator for
        every choice. When ``False``, ``provider_override`` must be
        supplied (and, for non-echo providers, ``api_key_override``)
        and the wizard runs straight through with no network
        verification.
    io:
        :class:`WizardIO` implementation. Defaults to
        :class:`_TyperIO`. Required only when tests want a deterministic
        scripted flow.
    provider_override, api_key_override, base_url_override:
        Bypass prompts when supplied. Used by ``--no-interactive`` mode
        and by tests.
    provider_factory:
        Builds providers for verification. Defaults to a factory that
        constructs real providers with fresh
        :class:`httpx.AsyncClient` instances. Tests inject a factory
        whose clients use :class:`httpx.MockTransport`.
    config:
        Pre-resolved :class:`AppConfig`. Defaults to the result of
        :func:`load_config`. Tests pin this to a tmp directory by
        setting ``CLAW_STU_DATA_DIR``; production code lets it default.
    """
    factory = provider_factory or _default_provider_factory
    wizard_io: WizardIO = io or _TyperIO()
    cfg = config or load_config()

    if not interactive:
        return _run_non_interactive(
            io=wizard_io,
            cfg=cfg,
            provider_override=provider_override,
            api_key_override=api_key_override,
            base_url_override=base_url_override,
        )

    _emit_greeting(wizard_io)
    choice = _prompt_provider(wizard_io)
    if choice == "echo":
        overrides = _collect_echo(wizard_io)
    elif choice == "ollama":
        overrides = _collect_ollama(wizard_io)
    else:
        overrides = _collect_api_key_provider(
            wizard_io, name=choice, factory=factory, cfg=cfg,
        )
    return _finish(wizard_io, cfg=cfg, overrides=overrides)


# ---------------------------------------------------------------------------
# Greeting + provider menu
# ---------------------------------------------------------------------------


def _emit_greeting(io: WizardIO) -> None:
    """Print the short "what this is" message."""
    io.echo("")
    io.echo("Claw-STU setup")
    io.echo("")
    io.echo(
        "Stuart is a personal learning agent. It uses an LLM to generate "
        "content for whatever subject you want to learn. You bring your "
        "own API key -- we don't run a central server."
    )
    io.echo("")
    io.echo(
        "Your API key and all learning data stay on this machine under "
        "~/.claw-stu (permissions 0700). Nothing is sent anywhere except "
        "to the LLM provider you choose."
    )
    io.echo("")


def _prompt_provider(io: WizardIO) -> str:
    """Show the numbered menu and return the chosen provider name."""
    io.echo("Pick a provider:")
    for idx, (_name, label) in enumerate(_PROVIDER_MENU, start=1):
        io.echo(f"  {idx}. {label}")
    while True:
        raw = io.prompt("Choice", default="1")
        choice = (raw or "").strip()
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(_PROVIDER_MENU):
                return _PROVIDER_MENU[n - 1][0]
        # Allow typing the name directly too -- friendlier for ops.
        for name, _label in _PROVIDER_MENU:
            if choice.lower() == name:
                return name
        io.echo(f"  '{choice}' is not a valid choice; pick 1-{len(_PROVIDER_MENU)}.")


# ---------------------------------------------------------------------------
# Per-provider collection
# ---------------------------------------------------------------------------


def _collect_echo(io: WizardIO) -> dict[str, Any]:
    io.echo("")
    io.echo(
        "Running in offline demo mode. Content will be deterministic "
        "stubs. Run `clawstu setup` again to pick a real provider."
    )
    return {"primary_provider": "echo"}


def _collect_ollama(io: WizardIO) -> dict[str, Any]:
    """Pick base_url and ping ``/api/tags`` to verify the daemon is up."""
    io.echo("")
    base_url = io.prompt(
        "Ollama base URL",
        default="http://localhost:11434",
    ).strip() or "http://localhost:11434"
    if _ping_ollama(base_url):
        io.echo("Ollama daemon reachable.", color=typer.colors.GREEN)
    else:
        io.echo(
            f"Could not reach Ollama at {base_url}. Stuart will still "
            "save the URL, but you'll need to start the daemon before "
            "running a session.",
            color=typer.colors.YELLOW,
        )
    overrides: dict[str, Any] = {
        "primary_provider": "ollama",
        "ollama_base_url": base_url,
    }
    return overrides


def _collect_api_key_provider(
    io: WizardIO,
    *,
    name: str,
    factory: ProviderFactory,
    cfg: AppConfig,
) -> dict[str, Any]:
    """Prompt for an API key, verify it, and return overrides.

    The verification call is the same one
    :func:`run_setup` documents: ``system="ping"``, one user message
    saying ``"hi"``, ``max_tokens=8``. On 401/403 the wizard offers a
    retry; on a third failure (or operator decline) the wizard offers
    to save anyway -- it never silently discards the operator's input.
    """
    base_url = _default_base_url(name, cfg)
    field_key, label = _api_key_field(name)
    while True:
        api_key = io.prompt(f"{label} API key", hide_input=True).strip()
        if not api_key:
            io.echo("API key is required for this provider.")
            continue
        try:
            provider = factory(name, api_key, base_url)
        except (ValueError, TypeError) as exc:
            io.echo(f"Could not construct provider: {exc}", color=typer.colors.RED)
            if not io.confirm("Try a different key?", default=True):
                raise
            continue
        ok, error = _ping_provider(provider)
        if ok:
            io.echo("Key verified.", color=typer.colors.GREEN)
            break
        io.echo(f"Verification failed: {error}", color=typer.colors.RED)
        if io.confirm("Retry with a different key?", default=True):
            continue
        if io.confirm(
            "Save this key anyway (you can rerun `clawstu setup` later)?",
            default=False,
        ):
            break
        raise SetupError(
            f"Setup aborted: could not verify {name} key and operator "
            "declined to save."
        )
    return {
        "primary_provider": name,
        field_key: api_key,
    }


def _api_key_field(name: str) -> tuple[str, str]:
    """Map a provider name to its (secrets.json key, prompt label) pair."""
    if name == "anthropic":
        return "anthropic_api_key", "Anthropic"
    if name == "openai":
        return "openai_api_key", "OpenAI"
    if name == "openrouter":
        return "openrouter_api_key", "OpenRouter"
    raise ValueError(f"no api-key field for provider {name!r}")


def _default_base_url(name: str, cfg: AppConfig) -> str:
    if name == "anthropic":
        return cfg.anthropic_base_url
    if name == "openai":
        return cfg.openai_base_url
    if name == "openrouter":
        return cfg.openrouter_base_url
    if name == "ollama":
        return cfg.ollama_base_url
    raise ValueError(f"no default base URL for provider {name!r}")


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------


def _ping_provider(provider: LLMProvider) -> tuple[bool, str]:
    """Run a tiny ``.complete()`` call. Returns (ok, error_message).

    Always closes the provider's underlying :class:`httpx.AsyncClient`
    once the ping has run -- otherwise pytest's ``filterwarnings=error``
    promotes a ``ResourceWarning`` from the leaked client into a test
    failure on the next gc cycle. Each call to ``_ping_provider``
    constructs a fresh provider via the factory, so closing the
    client here is the right scope.

    Uses an explicit ``new_event_loop`` + ``run_until_complete`` rather
    than :func:`asyncio.run` so the wizard's loop lifetime never
    collides with pytest-asyncio's auto-mode loop. ``asyncio.run``
    swaps the policy under the hood, which can confuse pytest-asyncio
    when wizard tests sit alongside async tests in the same suite.
    The loop is closed unconditionally in a ``finally`` block so the
    ResourceWarning never fires even when the ping itself raises.
    """
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run_ping_and_close(provider))
    except ProviderError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"unexpected error: {exc}"
    finally:
        loop.close()
    return True, ""


async def _run_ping_and_close(provider: LLMProvider) -> None:
    """Send the verification ping then close the provider's client.

    Factored out so the synchronous loop adapter has only one entry
    point. The provider's ``_client`` attribute is read via
    :func:`getattr` because every concrete provider in this codebase
    holds an :class:`httpx.AsyncClient` under that name and we'd
    rather close it once here than thread an async-context-manager
    factory through the wizard.
    """
    try:
        await provider.complete(
            system="ping",
            messages=[LLMMessage(role="user", content="hi")],
            max_tokens=8,
            temperature=0.0,
        )
    finally:
        client = getattr(provider, "_client", None)
        if isinstance(client, httpx.AsyncClient):
            await client.aclose()


def _ping_ollama(base_url: str) -> bool:
    """``GET {base_url}/api/tags`` and return True iff the daemon answers.

    Uses a sync :class:`httpx.Client` (the ping is not on the hot
    path) and unconditionally closes it via ``with`` so the call
    stays clean under pytest's ``filterwarnings=error``.
    """
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{base_url.rstrip('/')}/api/tags")
        return response.status_code < 500
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------------------
# Non-interactive path + finalization
# ---------------------------------------------------------------------------


def _run_non_interactive(
    *,
    io: WizardIO,
    cfg: AppConfig,
    provider_override: str | None,
    api_key_override: str | None,
    base_url_override: str | None,
) -> dict[str, Any]:
    """Run the wizard with no prompts. Used by ``--no-interactive``."""
    if provider_override is None:
        raise SetupError(
            "non-interactive mode requires --provider; pick echo, "
            "ollama, anthropic, openai, or openrouter."
        )
    name = provider_override.strip().lower()
    valid = {pname for pname, _ in _PROVIDER_MENU}
    if name not in valid:
        raise SetupError(
            f"unknown provider {name!r}; valid choices: {sorted(valid)}"
        )
    if name == "echo":
        overrides: dict[str, Any] = {"primary_provider": "echo"}
    elif name == "ollama":
        base_url = base_url_override or cfg.ollama_base_url
        overrides = {
            "primary_provider": "ollama",
            "ollama_base_url": base_url,
        }
    else:
        if not api_key_override:
            raise SetupError(
                f"non-interactive {name} setup requires --api-key."
            )
        field_key, _label = _api_key_field(name)
        overrides = {
            "primary_provider": name,
            field_key: api_key_override,
        }
    return _finish(io, cfg=cfg, overrides=overrides)


def _finish(
    io: WizardIO, *, cfg: AppConfig, overrides: dict[str, Any],
) -> dict[str, Any]:
    """Create the data dir and write ``secrets.json`` with 0600 perms."""
    ensure_data_dir(cfg)
    secrets_path = cfg.data_dir / "secrets.json"
    _write_secrets(secrets_path, overrides)
    if os.name == "nt":
        io.echo(
            "WARNING: secrets.json was written without POSIX 0600 perms. "
            "Treat ~/.claw-stu/ as sensitive and protect it via NTFS "
            "ACLs or a user-only profile location.",
            color=typer.colors.YELLOW,
        )
    io.echo("")
    io.echo("Setup complete.", color=typer.colors.GREEN)
    io.echo("")
    io.echo("Try:")
    io.echo("  clawstu           # start a learning session (coming in Part 2)")
    io.echo("  clawstu doctor    # verify config")
    io.echo("  clawstu serve     # start the FastAPI server")
    return overrides


def _write_secrets(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` and tighten perms to 0600 on POSIX.

    Existing files are overwritten -- the wizard's job is to land the
    operator on a known-good config, and merging arbitrary prior keys
    into the new dict would silently preserve stale credentials. The
    explicit overwrite is documented behavior.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(serialized + "\n", encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError as exc:
            logger.warning("could not chmod %s to 0600: %s", path, exc)


def secrets_path_for(cfg: AppConfig) -> Path:
    """Return the secrets.json path for ``cfg``. Exposed for tests."""
    return cfg.data_dir / "secrets.json"


def secrets_mode(path: Path) -> int:
    """Return the POSIX mode bits for ``path``, or ``-1`` on Windows.

    Tests assert ``secrets_mode(path) == 0o600``; on Windows the
    assertion is skipped via ``sys.platform`` guards in the suite.
    """
    if os.name == "nt":
        return -1
    return stat.S_IMODE(path.stat().st_mode)


__all__ = [
    "ProviderFactory",
    "SetupError",
    "WizardIO",
    "run_setup",
    "secrets_mode",
    "secrets_path_for",
]
