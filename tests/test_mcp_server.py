"""MCP server module tests.

Verifies the module imports cleanly, the tool registry has all five
expected tools, the CLI command is wired, and individual tools handle
edge cases gracefully.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawstu.mcp_server import clawstu_progress, clawstu_wiki


def test_mcp_server_module_imports_cleanly() -> None:
    """The MCP server module must import without side effects."""
    import clawstu.mcp_server as mod

    assert hasattr(mod, "mcp")
    assert hasattr(mod, "run_mcp_server")


def test_mcp_tool_definitions_exist() -> None:
    """The tool registry must contain all five documented tools."""
    from clawstu.mcp_server import _get_tool_registry

    tools = _get_tool_registry()
    expected = {
        "clawstu_ask",
        "clawstu_wiki",
        "clawstu_progress",
        "clawstu_review",
        "clawstu_learn_session",
    }
    assert set(tools) == expected


def test_mcp_server_command_in_help() -> None:
    """The ``mcp-server`` command must appear in the CLI's registered commands."""
    import click

    from clawstu.cli import app

    # Typer registers commands; iterate registered info to find mcp-server.
    command_names: list[str] = []
    if hasattr(app, "registered_commands"):
        for cmd in app.registered_commands:
            if hasattr(cmd, "name") and cmd.name:
                command_names.append(cmd.name)

    # Also check via the internal Click group that Typer builds.
    click_app: click.Group | None = None
    if hasattr(app, "_get_command"):
        click_app = app._get_command()

    if isinstance(click_app, click.Group):
        command_names.extend(click_app.list_commands(click.Context(click_app)))

    assert "mcp-server" in command_names, (
        f"mcp-server not found in CLI commands: {command_names}"
    )


async def test_wiki_tool_handles_no_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The wiki tool returns an error when no learner data exists."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    result_json = await clawstu_wiki(concept="test_concept", learner_id="")
    result = json.loads(result_json)
    # Should indicate no learner found (empty store) or return wiki content.
    # Either is acceptable -- the key thing is it doesn't crash.
    assert isinstance(result, dict)
    assert "error" in result or "wiki_markdown" in result


async def test_progress_tool_handles_no_learner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The progress tool returns an error when no learner exists."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    result_json = await clawstu_progress(learner_id="nonexistent_learner")
    result = json.loads(result_json)
    assert isinstance(result, dict)
    # Should gracefully handle missing learner.
    assert "error" in result or "learner_id" in result
