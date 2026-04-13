"""Smoke tests for v5 CLI parity commands.

Every test verifies the command is registered, ``--help`` works, and
the basic invocation path runs without crashing. None of these tests
require the agent package to be wired -- they exercise the graceful
fallback path.
"""
from __future__ import annotations

import re

from typer.testing import CliRunner

from clawstu.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _plain(s: str) -> str:
    return _ANSI_RE.sub("", s)


# ---------------------------------------------------------------------------
# clawstu generate
# ---------------------------------------------------------------------------


def test_generate_help() -> None:
    result = runner.invoke(app, ["generate", "--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "generate" in stdout.lower()
    assert "topic" in stdout.lower()


def test_generate_worksheet_fallback() -> None:
    result = runner.invoke(app, ["generate", "worksheet", "photosynthesis"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "worksheet" in stdout.lower()
    assert "v5" in stdout.lower()


def test_generate_rejects_unknown_type() -> None:
    result = runner.invoke(app, ["generate", "not-a-type", "topic"])
    assert result.exit_code == 2
    stdout = _plain(result.stdout)
    assert "unknown" in stdout.lower() or "not-a-type" in stdout


def test_generate_accepts_all_artifact_types() -> None:
    for artifact_type in (
        "worksheet", "game", "visual", "simulation", "animation",
        "slides", "study-guide", "practice-test", "flashcards",
    ):
        result = runner.invoke(app, ["generate", artifact_type, "test"])
        assert result.exit_code == 0, f"Failed for {artifact_type}"


# ---------------------------------------------------------------------------
# clawstu export
# ---------------------------------------------------------------------------


def test_export_help() -> None:
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "export" in stdout.lower()
    assert "format" in stdout.lower() or "pdf" in stdout.lower()


def test_export_pdf_fallback() -> None:
    result = runner.invoke(app, ["export", "pdf"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "pdf" in stdout.lower()
    assert "v5" in stdout.lower()


def test_export_rejects_unknown_format() -> None:
    result = runner.invoke(app, ["export", "pptx"])
    assert result.exit_code == 2
    stdout = _plain(result.stdout)
    assert "unknown" in stdout.lower() or "pptx" in stdout


# ---------------------------------------------------------------------------
# clawstu search
# ---------------------------------------------------------------------------


def test_search_help() -> None:
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "search" in stdout.lower()


def test_search_fallback() -> None:
    result = runner.invoke(app, ["search", "mitosis"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "mitosis" in stdout.lower()
    assert "v5" in stdout.lower()


# ---------------------------------------------------------------------------
# clawstu practice (shortcut)
# ---------------------------------------------------------------------------


def test_practice_help() -> None:
    result = runner.invoke(app, ["practice", "--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "practice" in stdout.lower()


def test_practice_fallback() -> None:
    result = runner.invoke(app, ["practice", "quadratic equations"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "practice-test" in stdout.lower()
    assert "v5" in stdout.lower()


# ---------------------------------------------------------------------------
# clawstu flashcards (shortcut)
# ---------------------------------------------------------------------------


def test_flashcards_help() -> None:
    result = runner.invoke(app, ["flashcards", "--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "flashcard" in stdout.lower()


def test_flashcards_fallback() -> None:
    result = runner.invoke(app, ["flashcards", "cell biology"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "flashcards" in stdout.lower()
    assert "v5" in stdout.lower()


# ---------------------------------------------------------------------------
# clawstu game (shortcut)
# ---------------------------------------------------------------------------


def test_game_help() -> None:
    result = runner.invoke(app, ["game", "--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "game" in stdout.lower()


def test_game_fallback() -> None:
    result = runner.invoke(app, ["game", "periodic table"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "game" in stdout.lower()
    assert "v5" in stdout.lower()


# ---------------------------------------------------------------------------
# clawstu ingest
# ---------------------------------------------------------------------------


def test_ingest_help() -> None:
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "ingest" in stdout.lower()


def test_ingest_missing_path() -> None:
    result = runner.invoke(app, ["ingest", "/nonexistent/path/materials.txt"])
    assert result.exit_code == 1
    stdout = _plain(result.stdout)
    assert "does not exist" in stdout.lower()


def test_ingest_valid_path_fallback(tmp_path: object) -> None:
    from pathlib import Path

    p = Path(str(tmp_path)) / "materials.txt"
    p.write_text("Some curriculum content.")
    result = runner.invoke(app, ["ingest", str(p)])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    assert "v5" in stdout.lower()


# ---------------------------------------------------------------------------
# Top-level help includes all new commands
# ---------------------------------------------------------------------------


def test_help_mentions_v5_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    stdout = _plain(result.stdout)
    for cmd in ("generate", "export", "search", "practice", "flashcards", "game", "ingest"):
        assert cmd in stdout, f"--help missing v5 command '{cmd}'"
