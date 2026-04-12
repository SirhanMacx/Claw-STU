"""Tests for the Telegram bot module.

All tests use unittest.mock — no actual Telegram connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawstu import bot as bot_module


def test_bot_module_imports_cleanly() -> None:
    """The bot module should import without requiring python-telegram-bot."""
    assert hasattr(bot_module, "run_bot")
    assert hasattr(bot_module, "_handle_start")
    assert hasattr(bot_module, "_handle_learn")
    assert hasattr(bot_module, "_GREETING")
    assert hasattr(bot_module, "_HELP_TEXT")


async def test_bot_start_handler_sends_greeting() -> None:
    """The /start handler should send the greeting message."""
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await bot_module._handle_start(update, context)

    update.message.reply_text.assert_called_once_with(bot_module._GREETING)


async def test_bot_learn_handler_creates_session() -> None:
    """The /learn handler rejects a missing topic."""
    update = MagicMock()
    update.effective_chat.id = 99999
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []  # no topic

    await bot_module._handle_learn(update, context)

    # Should have sent the usage message
    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "usage" in call_text.lower() or "/learn" in call_text.lower()


async def test_bot_ask_handler_returns_answer() -> None:
    """The /ask handler should return a response to a question."""
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["what", "is", "photosynthesis"]

    await bot_module._handle_ask(update, context)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "photosynthesis" in call_text.lower()


def test_bot_command_exists_in_cli_help() -> None:
    """The 'bot' command should exist in the CLI app."""
    from typer.testing import CliRunner

    from clawstu.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["bot", "--help"])
    assert result.exit_code == 0
    assert "telegram" in result.output.lower() or "token" in result.output.lower()


async def test_bot_help_handler_sends_commands() -> None:
    """The /help handler should send the help text."""
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await bot_module._handle_help(update, context)

    update.message.reply_text.assert_called_once_with(bot_module._HELP_TEXT)


async def test_bot_quit_handler_no_session() -> None:
    """The /quit handler should say no active session when none exists."""
    update = MagicMock()
    update.effective_chat.id = 88888
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    bot_module._sessions.pop(88888, None)

    await bot_module._handle_quit(update, context)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "no active session" in call_text.lower()


def test_bot_run_bot_raises_without_telegram_dep() -> None:
    """run_bot should raise RuntimeError if python-telegram-bot is not installed."""
    with (
        patch.dict("sys.modules", {"telegram": None, "telegram.ext": None}),
        pytest.raises(RuntimeError, match="telegram extra"),
    ):
        bot_module.run_bot(token="fake-token")
