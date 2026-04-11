"""Tests for the clawstu CLI entry point."""
from __future__ import annotations

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
    for command in ("serve", "doctor", "scheduler", "profile"):
        assert command in stdout, f"--help missing '{command}'"


def test_help_shows_project_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "clawstu" in stdout.lower() or "Stuart" in stdout


def test_invoking_with_no_args_shows_help() -> None:
    # Typer default: no args + no default command -> shows help (exit 0).
    result = runner.invoke(app, [])
    assert result.exit_code in (0, 2)  # Typer may return 2 for missing command


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
