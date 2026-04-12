"""Tests for the clawstu CLI entry point."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from clawstu.cli import app

runner = CliRunner()

# Typer uses rich to render --help with box-drawing characters and
# ANSI color codes. On CI (no TTY) those codes end up in the captured
# stdout and can fragment literal substrings like "--ping" across
# escape sequences, so every test that asserts on --help output
# strips ANSI first.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _plain(s: str) -> str:
    return _ANSI_RE.sub("", s)


def test_help_mentions_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Every top-level command we register should appear in --help.
    stdout = _plain(result.stdout)
    for command in (
        "learn",
        "resume",
        "wiki",
        "progress",
        "history",
        "review",
        "serve",
        "doctor",
        "scheduler",
        "profile",
    ):
        assert command in stdout, f"--help missing '{command}'"


def test_help_shows_project_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "clawstu" in stdout.lower() or "Stuart" in stdout


def test_invoking_with_no_args_dispatches_to_learn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`clawstu` with no args drops into the `learn` chat loop.

    Phase 8 Part 2A wires a default callback that invokes the
    ``learn`` command when no subcommand is given, mirroring how
    ``clawed`` drops you straight into a chat. The callback then
    hands off to ``clawstu.cli_chat.run_chat_session``. Under
    CliRunner there's no real stdin, so the real chat loop would
    eventually crash on a prompt read. We stub ``run_chat_session``
    to a marker function and assert it was invoked with empty
    ChatInputs -- that exercises the callback wiring without
    depending on Rich's TTY behavior.
    """
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    calls: list[Any] = []

    def _fake_run_chat_session(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "clawstu.cli_chat.run_chat_session", _fake_run_chat_session,
    )

    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.stdout
    assert len(calls) == 1, (
        f"expected run_chat_session to be invoked once; got {len(calls)}"
    )
    inputs = calls[0]["inputs"]
    assert inputs.learner_id is None
    assert inputs.age is None
    assert inputs.topic is None
    assert inputs.domain is None


def test_doctor_prints_config_summary() -> None:
    result = runner.invoke(app, ["doctor"])
    # doctor should succeed on a clean environment (no secrets.json,
    # no env overrides -> falls back to AppConfig defaults).
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "config load" in stdout
    assert "primary_provider" in stdout


def test_scheduler_run_once_placeholder() -> None:
    result = runner.invoke(app, ["scheduler", "run-once", "--task", "dream_cycle"])
    assert result.exit_code == 0
    assert "dream_cycle" in _plain(result.stdout)


def test_doctor_without_ping_does_not_make_network_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """doctor is a static config dump by default; --ping is opt-in.

    We monkeypatch both httpx.Client.post and .get to raise on any
    invocation, then run `doctor` without --ping. If any code path
    tries a network call, the test fails with a clear message.
    """
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    def forbidden_request(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "doctor without --ping must not make network calls; "
            f"attempted: args={args}, kwargs={kwargs}"
        )

    monkeypatch.setattr(httpx.Client, "post", forbidden_request)
    monkeypatch.setattr(httpx.Client, "get", forbidden_request)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout
    # With --ping off, the reachability line says "skipped".
    assert "skipped" in _plain(result.stdout)


def test_doctor_accepts_ping_flag() -> None:
    """The --ping flag is actually a registered option.

    Behavioral test (not help-text introspection): if --ping were not
    a real flag, Typer would reject the invocation with exit code 2
    ("no such option"). Exit code 0 + stdout content is the contract.
    This is more robust than scraping --help for "--ping" because
    rich-rendered help output in CI contains ANSI escapes and
    word-wrapping that can fragment the literal substring.
    """
    result = runner.invoke(app, ["doctor", "--ping"])
    assert result.exit_code == 0, (
        f"--ping rejected by the CLI: exit={result.exit_code}\n"
        f"stdout:\n{result.stdout}"
    )


def test_doctor_with_ping_prints_deferred_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """With --ping, Phase 1 still prints a DEFERRED note (real
    reachability check lands in Phase 2). This test pins the
    behavior so anyone who implements real pings has to update it.
    """
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["doctor", "--ping"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "provider reachability" in stdout
    assert "DEFERRED" in stdout


def test_setup_command_exists_in_help() -> None:
    """`clawstu setup --help` returns 0 and mentions the wizard."""
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    # The help body should at least describe the wizard's purpose.
    assert "setup" in stdout.lower()
    assert "provider" in stdout.lower()


def test_setup_command_runs_in_echo_only_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`clawstu setup --no-interactive --provider echo` writes secrets.json."""
    # Isolate the data dir + clear ambient credentials so the wizard's
    # load_config sees the bare default it expects from a clean install.
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
        "OLLAMA_BASE_URL",
        "STU_PRIMARY_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    result = runner.invoke(
        app,
        ["setup", "--no-interactive", "--provider", "echo"],
    )
    assert result.exit_code == 0, result.stdout
    secrets = tmp_path / "secrets.json"
    assert secrets.exists(), "wizard did not write secrets.json"
    payload = json.loads(secrets.read_text())
    assert payload == {"primary_provider": "echo"}


def test_learn_command_exists_in_help() -> None:
    """`clawstu learn --help` returns 0 and describes the learning session."""
    result = runner.invoke(app, ["learn", "--help"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "learn" in stdout.lower()
    # The help body should mention the topic argument.
    assert "topic" in stdout.lower()


def test_resume_command_exists_in_help() -> None:
    """`clawstu resume --help` returns 0 and describes warm-start."""
    result = runner.invoke(app, ["resume", "--help"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "resume" in stdout.lower()


def test_learn_command_forwards_topic_and_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`clawstu learn <topic>` passes its args through to ChatInputs."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    calls: list[Any] = []

    def _fake_run_chat_session(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "clawstu.cli_chat.run_chat_session", _fake_run_chat_session,
    )

    result = runner.invoke(
        app,
        [
            "learn",
            "The Haitian Revolution",
            "--learner", "ada",
            "--age", "15",
            "--domain", "global_history",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert len(calls) == 1
    inputs = calls[0]["inputs"]
    assert inputs.topic == "The Haitian Revolution"
    assert inputs.learner_id == "ada"
    assert inputs.age == 15
    # Domain is a Domain enum, not a raw string.
    from clawstu.profile.model import Domain
    assert inputs.domain is Domain.GLOBAL_HISTORY


def test_learn_command_rejects_unknown_domain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`--domain nonsense` exits non-zero with a helpful message."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    result = runner.invoke(
        app,
        ["learn", "photosynthesis", "--domain", "not_a_real_domain"],
    )
    assert result.exit_code == 2
    stdout = _plain(result.stdout)
    assert "not_a_real_domain" in stdout or "unknown" in stdout.lower()


def test_resume_command_forwards_learner_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`clawstu resume ada` calls ``run_resume_session(learner_id='ada')``."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    calls: list[Any] = []

    def _fake_run_resume_session(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "clawstu.cli_chat.run_resume_session", _fake_run_resume_session,
    )

    result = runner.invoke(app, ["resume", "ada"])
    assert result.exit_code == 0, result.stdout
    assert calls == [{"learner_id": "ada"}]


def test_resume_command_without_artifact_reports_nothing_to_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """NoArtifactError is surfaced as a yellow message + exit code 1."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    from clawstu.engagement.session import NoArtifactError

    def _raises(**_kwargs: Any) -> None:
        raise NoArtifactError("no artifact for learner 'ada'")

    monkeypatch.setattr(
        "clawstu.cli_chat.run_resume_session", _raises,
    )
    result = runner.invoke(app, ["resume", "ada"])
    assert result.exit_code == 1
    stdout = _plain(result.stdout)
    assert "nothing to resume" in stdout
    assert "clawstu learn" in stdout


# ---------------------------------------------------------------------------
# Phase 8 Part 2B: companion command smoke tests
# ---------------------------------------------------------------------------


def test_wiki_command_exists_in_help() -> None:
    """`clawstu wiki --help` returns 0 and describes the concept wiki."""
    result = runner.invoke(app, ["wiki", "--help"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "wiki" in stdout.lower()
    assert "concept" in stdout.lower()


def test_progress_command_exists_in_help() -> None:
    """`clawstu progress --help` returns 0 and describes the dashboard."""
    result = runner.invoke(app, ["progress", "--help"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "progress" in stdout.lower()


def test_history_command_exists_in_help() -> None:
    """`clawstu history --help` returns 0 and describes the listing."""
    result = runner.invoke(app, ["history", "--help"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "history" in stdout.lower()


def test_review_command_exists_in_help() -> None:
    """`clawstu review --help` returns 0 and describes spaced review."""
    result = runner.invoke(app, ["review", "--help"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "review" in stdout.lower()
