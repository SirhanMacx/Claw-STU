"""Tests for the clawstu CLI entry point."""
from __future__ import annotations

from typer.testing import CliRunner

from clawstu.cli import app

runner = CliRunner()


def test_help_mentions_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Every top-level command we register should appear in --help.
    for command in ("serve", "doctor", "scheduler", "profile"):
        assert command in result.stdout, f"--help missing '{command}'"


def test_help_shows_project_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "clawstu" in result.stdout.lower() or "Stuart" in result.stdout


def test_invoking_with_no_args_shows_help() -> None:
    # Typer default: no args + no default command -> shows help (exit 0).
    result = runner.invoke(app, [])
    assert result.exit_code in (0, 2)  # Typer may return 2 for missing command


def test_doctor_prints_config_summary() -> None:
    result = runner.invoke(app, ["doctor"])
    # doctor should succeed on a clean environment (no secrets.json,
    # no env overrides -> falls back to AppConfig defaults).
    assert result.exit_code == 0, result.stdout
    assert "config load" in result.stdout
    assert "primary_provider" in result.stdout


def test_scheduler_run_once_placeholder() -> None:
    result = runner.invoke(app, ["scheduler", "run-once", "--task", "dream_cycle"])
    assert result.exit_code == 0
    assert "dream_cycle" in result.stdout
