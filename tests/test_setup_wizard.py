"""Tests for the interactive setup wizard.

The wizard is exercised through a small :class:`_FakeIO` shim that
replaces stdin/stdout. Network providers are exercised through
:class:`httpx.MockTransport`-backed clients so the verification ping
is real code, not a stub. Ollama's daemon ping is monkey-patched at
the module level because the wizard's path uses a synchronous
:class:`httpx.Client` for that single GET, which is the cleanest
intercept point.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from clawstu import setup_wizard
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.providers import LLMProvider
from clawstu.setup_wizard import (
    SetupError,
    run_setup,
    secrets_mode,
    secrets_path_for,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeIO:
    """A scripted :class:`WizardIO` that returns canned answers in order.

    ``answers`` is the queue of strings the wizard would have read from
    ``stdin``. ``confirms`` is the queue of yes/no answers. The fake
    records every echoed line into ``echoes`` so tests can assert on
    the user-facing transcript.

    Mismatched script lengths surface as ``IndexError`` rather than a
    silent default, which is exactly what a test wants -- a script that
    is too short means the wizard asked an unanticipated question.
    """

    answers: list[str] = field(default_factory=list)
    confirms: list[bool] = field(default_factory=list)
    echoes: list[str] = field(default_factory=list)
    _answer_idx: int = 0
    _confirm_idx: int = 0

    def prompt(
        self,
        text: str,
        *,
        hide_input: bool = False,
        default: str | None = None,
    ) -> str:
        if self._answer_idx >= len(self.answers):
            raise AssertionError(
                f"FakeIO ran out of scripted answers; "
                f"wizard asked: {text!r}"
            )
        value = self.answers[self._answer_idx]
        self._answer_idx += 1
        return value

    def echo(self, text: str, *, color: str | None = None) -> None:
        self.echoes.append(text)

    def confirm(self, text: str, *, default: bool = False) -> bool:
        if self._confirm_idx >= len(self.confirms):
            raise AssertionError(
                f"FakeIO ran out of scripted confirms; "
                f"wizard asked: {text!r}"
            )
        value = self.confirms[self._confirm_idx]
        self._confirm_idx += 1
        return value


def _make_mock_provider_factory(
    response_status: int = 200,
    response_json: dict[str, Any] | None = None,
) -> setup_wizard.ProviderFactory:
    """Build a provider factory whose providers all use a MockTransport.

    The transport returns ``response_status`` with ``response_json`` for
    every request. This lets the wizard's verification ping exercise
    each real provider's full ``.complete()`` code path against a
    canned answer with no network involvement.
    """
    payload = response_json if response_json is not None else {
        # Anthropic-shaped happy-path body. The other providers parse a
        # different shape, so per-provider tests pass their own JSON.
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
        "model": "claude-haiku-4-5",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(response_status, json=payload)

    transport = httpx.MockTransport(handler)

    def factory(
        name: str, api_key: str | None, base_url: str,
    ) -> LLMProvider:
        client = httpx.AsyncClient(transport=transport)
        if name == "anthropic":
            return AnthropicProvider(
                api_key=api_key, base_url=base_url, client=client,
            )
        if name == "openai":
            return OpenAIProvider(
                api_key=api_key, base_url=base_url, client=client,
            )
        if name == "openrouter":
            return OpenRouterProvider(
                api_key=api_key, base_url=base_url, client=client,
            )
        if name == "ollama":
            return OllamaProvider(
                base_url=base_url, api_key=api_key, client=client,
            )
        raise ValueError(f"unknown provider: {name}")

    return factory


@pytest.fixture
def isolated_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[Path]:
    """Pin ``CLAW_STU_DATA_DIR`` to a fresh tmp dir for each test.

    Also unsets every provider env var so ambient developer credentials
    can never leak into the wizard's loaded config.
    """
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OLLAMA_API_KEY",
        "OLLAMA_BASE_URL",
        "STU_PRIMARY_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------------------
# Tests -- secrets file shape and permissions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_wizard_writes_secrets_file_with_0600_perms_for_anthropic(
    isolated_data_dir: Path,
) -> None:
    """Anthropic flow writes the file at 0600 with the chosen key."""
    fake_io = _FakeIO(answers=["1", "sk-ant-test-key"])
    factory = _make_mock_provider_factory()

    written = run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=factory,
    )

    secrets = isolated_data_dir / "secrets.json"
    assert secrets.exists(), "wizard did not write secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "anthropic",
        "anthropic_api_key": "sk-ant-test-key",
    }
    assert written == payload
    file_mode = stat.S_IMODE(secrets.stat().st_mode)
    assert file_mode == 0o600, f"expected 0600, got {file_mode:o}"
    # The wizard should have echoed a "verified" line.
    assert any("verified" in line.lower() for line in fake_io.echoes)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_wizard_writes_secrets_file_with_0600_perms_for_openai(
    isolated_data_dir: Path,
) -> None:
    """OpenAI flow writes the file at 0600 with the chosen key."""
    fake_io = _FakeIO(answers=["2", "sk-openai-test-key"])
    # OpenAI parses a chat-completions-shaped body.
    factory = _make_mock_provider_factory(
        response_json={
            "id": "chat_test",
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )

    run_setup(interactive=True, io=fake_io, provider_factory=factory)

    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "openai",
        "openai_api_key": "sk-openai-test-key",
    }
    assert secrets_mode(secrets) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_wizard_writes_secrets_file_with_0600_perms_for_openrouter(
    isolated_data_dir: Path,
) -> None:
    """OpenRouter flow writes the file at 0600 with the chosen key."""
    fake_io = _FakeIO(answers=["3", "sk-or-test-key"])
    factory = _make_mock_provider_factory(
        response_json={
            "id": "or_test",
            "model": "z-ai/glm-4.5-air",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )

    run_setup(interactive=True, io=fake_io, provider_factory=factory)

    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "openrouter",
        "openrouter_api_key": "sk-or-test-key",
    }
    assert secrets_mode(secrets) == 0o600


def test_wizard_ollama_picks_base_url_and_does_not_require_api_key(
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama flow accepts a base URL and skips API-key prompting."""
    # Patch _ping_ollama at the module level so the wizard never opens
    # a real socket. The function lives in setup_wizard, so the
    # monkeypatch is local to the wizard and doesn't leak.
    monkeypatch.setattr(setup_wizard, "_ping_ollama", lambda _url: True)
    fake_io = _FakeIO(answers=["4", "http://localhost:22222"])

    written = run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )

    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "ollama",
        "ollama_base_url": "http://localhost:22222",
    }
    assert written == payload
    # The Ollama path must not have asked for an API key, so the script
    # should have only consumed the menu choice and the base URL.
    assert "ollama_api_key" not in payload


def test_wizard_echo_writes_secrets_with_primary_provider_echo(
    isolated_data_dir: Path,
) -> None:
    """Echo flow writes a single-key secrets payload and creates the dir."""
    fake_io = _FakeIO(answers=["5"])
    written = run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )

    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {"primary_provider": "echo"}
    assert written == payload


def test_wizard_verifies_anthropic_key_via_tiny_ping_request(
    isolated_data_dir: Path,
) -> None:
    """The wizard hits the provider's /v1/messages endpoint exactly once.

    The MockTransport handler captures the request URL, headers, and
    body so we can prove the wizard actually performed an HTTP call
    against the AnthropicProvider's full ``.complete()`` code path
    rather than short-circuiting verification with a stub.
    """
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["x-api-key"] = request.headers.get("x-api-key")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "msg_ping",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "pong"}],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 2, "output_tokens": 1},
            },
        )

    transport = httpx.MockTransport(handler)

    def factory(
        name: str, api_key: str | None, base_url: str,
    ) -> LLMProvider:
        client = httpx.AsyncClient(transport=transport)
        return AnthropicProvider(
            api_key=api_key, base_url=base_url, client=client,
        )

    fake_io = _FakeIO(answers=["1", "sk-ant-real"])
    run_setup(interactive=True, io=fake_io, provider_factory=factory)

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["x-api-key"] == "sk-ant-real"
    body = captured["body"]
    assert body["system"] == "ping"
    assert body["max_tokens"] == 8
    # The body should carry the canonical user message we documented.
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_wizard_retries_on_failed_verification(
    isolated_data_dir: Path,
) -> None:
    """A 401 prompts a retry; the second key succeeds and is written."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(
                401,
                text='{"type":"error","error":{"type":"authentication_error"}}',
            )
        return httpx.Response(
            200,
            json={
                "id": "msg",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    transport = httpx.MockTransport(handler)

    def factory(
        name: str, api_key: str | None, base_url: str,
    ) -> LLMProvider:
        client = httpx.AsyncClient(transport=transport)
        return AnthropicProvider(
            api_key=api_key, base_url=base_url, client=client,
        )

    # First answer: pick anthropic. Second: a bad key. Third: a good key.
    # First confirm: yes, retry with a different key.
    fake_io = _FakeIO(
        answers=["1", "sk-ant-bad", "sk-ant-good"],
        confirms=[True],
    )
    run_setup(interactive=True, io=fake_io, provider_factory=factory)

    assert call_count["n"] == 2, "wizard should have re-pinged after retry"
    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "anthropic",
        "anthropic_api_key": "sk-ant-good",
    }


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_wizard_creates_data_dir_with_0700_perms_if_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """When ``~/.claw-stu`` does not exist, the wizard creates it 0700.

    This test points CLAW_STU_DATA_DIR at a path the wizard must
    create, then asserts the resulting directory's permissions match
    the contract documented in ``ensure_data_dir``.
    """
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
        "OLLAMA_BASE_URL",
        "STU_PRIMARY_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    target = tmp_path / "fresh-claw-stu"
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(target))
    assert not target.exists()

    fake_io = _FakeIO(answers=["5"])
    run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )

    assert target.exists() and target.is_dir()
    dir_mode = stat.S_IMODE(target.stat().st_mode)
    assert dir_mode == 0o700, f"expected 0700, got {dir_mode:o}"


# ---------------------------------------------------------------------------
# Extra tests -- non-interactive mode and convenience helpers
# ---------------------------------------------------------------------------


def test_wizard_non_interactive_echo(
    isolated_data_dir: Path,
) -> None:
    """``--no-interactive --provider echo`` writes a minimal payload."""
    fake_io = _FakeIO(answers=[])  # no prompts in non-interactive mode
    written = run_setup(
        interactive=False,
        io=fake_io,
        provider_override="echo",
    )
    assert written == {"primary_provider": "echo"}
    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {"primary_provider": "echo"}


def test_wizard_non_interactive_requires_provider(
    isolated_data_dir: Path,
) -> None:
    fake_io = _FakeIO()
    with pytest.raises(SetupError, match="--provider"):
        run_setup(interactive=False, io=fake_io)


def test_wizard_non_interactive_requires_api_key_for_anthropic(
    isolated_data_dir: Path,
) -> None:
    """Non-interactive Anthropic without --api-key is a SetupError."""
    fake_io = _FakeIO()
    with pytest.raises(SetupError, match="--api-key"):
        run_setup(
            interactive=False,
            io=fake_io,
            provider_override="anthropic",
        )


def test_wizard_non_interactive_writes_anthropic_with_api_key(
    isolated_data_dir: Path,
) -> None:
    """Non-interactive Anthropic with --api-key writes the file (no ping)."""
    fake_io = _FakeIO()
    run_setup(
        interactive=False,
        io=fake_io,
        provider_override="anthropic",
        api_key_override="sk-ant-noninteractive",
    )
    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "anthropic",
        "anthropic_api_key": "sk-ant-noninteractive",
    }


def test_wizard_non_interactive_rejects_unknown_provider(
    isolated_data_dir: Path,
) -> None:
    fake_io = _FakeIO()
    with pytest.raises(SetupError, match="unknown provider"):
        run_setup(
            interactive=False,
            io=fake_io,
            provider_override="banana",
        )


def test_secrets_path_for_returns_data_dir_secrets_json() -> None:
    cfg = AppConfig(data_dir=Path("/tmp/x"))
    assert secrets_path_for(cfg) == Path("/tmp/x/secrets.json")


def test_provider_menu_uses_typing_a_name_directly(
    isolated_data_dir: Path,
) -> None:
    """Operators can type the provider name instead of a number."""
    fake_io = _FakeIO(answers=["echo"])
    run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )
    secrets = isolated_data_dir / "secrets.json"
    assert json.loads(secrets.read_text())["primary_provider"] == "echo"


def test_invalid_menu_choice_re_prompts(
    isolated_data_dir: Path,
) -> None:
    """A nonsense choice surfaces a hint and re-prompts."""
    fake_io = _FakeIO(answers=["banana", "5"])
    run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )
    # The error hint should appear in the captured echoes.
    assert any("not a valid choice" in line for line in fake_io.echoes)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_wizard_overwrites_existing_secrets_file(
    isolated_data_dir: Path,
) -> None:
    """Re-running the wizard replaces the previous secrets, not merges."""
    isolated_data_dir.mkdir(parents=True, exist_ok=True)
    pre_existing = isolated_data_dir / "secrets.json"
    pre_existing.write_text(
        json.dumps({"openai_api_key": "sk-old"}),
        encoding="utf-8",
    )
    os.chmod(pre_existing, 0o600)

    fake_io = _FakeIO(answers=["5"])
    run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )

    payload = json.loads(pre_existing.read_text())
    assert payload == {"primary_provider": "echo"}
    assert "openai_api_key" not in payload
    assert secrets_mode(pre_existing) == 0o600


def test_wizard_re_prompts_on_empty_api_key(
    isolated_data_dir: Path,
) -> None:
    """An empty API key string surfaces a hint and re-prompts.

    Pin the empty-key branch in `_collect_api_key_provider` so a
    silent skip in the future would fail this test loud.
    """
    fake_io = _FakeIO(answers=["1", "", "sk-ant-actual"])
    run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )
    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload["anthropic_api_key"] == "sk-ant-actual"
    assert any("required" in line for line in fake_io.echoes)


def test_wizard_save_anyway_after_repeated_failure(
    isolated_data_dir: Path,
) -> None:
    """Operator declines retry then accepts save-anyway -- key is written.

    This pins the documented escape hatch: a teacher onboarding a
    laptop with a flaky network can save the key and run the wizard
    again later. Without this branch, a transient 5xx would force
    them to abort and re-enter their key from scratch.
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text='{"error":"upstream"}')

    transport = httpx.MockTransport(handler)

    def factory(
        name: str, api_key: str | None, base_url: str,
    ) -> LLMProvider:
        client = httpx.AsyncClient(transport=transport)
        return AnthropicProvider(
            api_key=api_key, base_url=base_url, client=client,
        )

    # answers: pick anthropic, then key. confirms: decline retry, accept save.
    fake_io = _FakeIO(
        answers=["1", "sk-ant-flaky"],
        confirms=[False, True],
    )
    run_setup(interactive=True, io=fake_io, provider_factory=factory)
    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "anthropic",
        "anthropic_api_key": "sk-ant-flaky",
    }


def test_wizard_aborts_when_operator_declines_save_anyway(
    isolated_data_dir: Path,
) -> None:
    """Decline retry AND decline save-anyway -> SetupError, no file written."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error":"auth"}')

    transport = httpx.MockTransport(handler)

    def factory(
        name: str, api_key: str | None, base_url: str,
    ) -> LLMProvider:
        client = httpx.AsyncClient(transport=transport)
        return AnthropicProvider(
            api_key=api_key, base_url=base_url, client=client,
        )

    fake_io = _FakeIO(
        answers=["1", "sk-ant-bad"],
        confirms=[False, False],
    )
    with pytest.raises(SetupError, match="declined to save"):
        run_setup(interactive=True, io=fake_io, provider_factory=factory)
    assert not (isolated_data_dir / "secrets.json").exists()


def test_wizard_non_interactive_ollama_with_base_url_override(
    isolated_data_dir: Path,
) -> None:
    """Non-interactive Ollama with --base-url writes the override."""
    fake_io = _FakeIO()
    run_setup(
        interactive=False,
        io=fake_io,
        provider_override="ollama",
        base_url_override="http://custom.local:9999",
    )
    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "ollama",
        "ollama_base_url": "http://custom.local:9999",
    }


def test_wizard_ollama_unreachable_warning(
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interactive Ollama path warns but still saves when daemon is down."""
    monkeypatch.setattr(setup_wizard, "_ping_ollama", lambda _url: False)
    fake_io = _FakeIO(answers=["4", "http://unreachable:11434"])
    run_setup(
        interactive=True,
        io=fake_io,
        provider_factory=_make_mock_provider_factory(),
    )
    secrets = isolated_data_dir / "secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {
        "primary_provider": "ollama",
        "ollama_base_url": "http://unreachable:11434",
    }
    assert any("Could not reach" in line for line in fake_io.echoes)
