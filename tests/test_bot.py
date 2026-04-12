"""Tests for the Telegram bot module.

All tests use unittest.mock -- no actual Telegram connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawstu import bot as bot_module
from clawstu.bot import (
    _GREETING,
    _HELP_TEXT,
    _BotSession,
    _handle_ask,
    _handle_help,
    _handle_learn,
    _handle_message,
    _handle_progress,
    _handle_quit,
    _handle_start,
    _sessions,
)
from clawstu.engagement.session import Session, SessionPhase, SessionRunner
from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    LearnerProfile,
    ZPDEstimate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_update(chat_id: int = 12345, first_name: str = "Alice") -> MagicMock:
    """Build a mock ``telegram.Update`` with a realistic shape."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.first_name = first_name
    update.message.reply_text = AsyncMock()
    update.message.text = ""
    return update


def _make_context(args: list[str] | None = None) -> MagicMock:
    """Build a mock ``telegram.ext.ContextTypes.DEFAULT_TYPE``."""
    ctx = MagicMock()
    ctx.args = args if args is not None else []
    return ctx


def _make_bot_session(
    *,
    chat_id: int = 12345,
    phase: SessionPhase = SessionPhase.TEACHING,
    topic: str = "photosynthesis",
    blocks_presented: int = 2,
    reteach_count: int = 1,
    register: bool = True,
) -> _BotSession:
    """Build a ``_BotSession`` with controllable state.

    If *register* is True the session is stored in the module-level
    ``_sessions`` dict so handler functions can find it by chat_id.
    """
    profile = LearnerProfile(
        learner_id="test-learner", age_bracket=AgeBracket.EARLY_HIGH,
    )
    runner = SessionRunner()
    session = Session(
        learner_id="test-learner",
        domain=Domain.OTHER,
        topic=topic,
    )
    session.phase = phase
    session.blocks_presented = blocks_presented
    session.reteach_count = reteach_count

    from clawstu.api.state import AppState
    from clawstu.assessment.evaluator import Evaluator

    evaluator = Evaluator()
    state = AppState(cache_size=4, runner=runner)

    bot_session = _BotSession(
        profile=profile,
        session=session,
        runner=runner,
        evaluator=evaluator,
        state=state,
    )
    if register:
        _sessions[chat_id] = bot_session
    return bot_session


# ---------------------------------------------------------------------------
# Module-level import and attribute tests
# ---------------------------------------------------------------------------


def test_bot_module_imports_cleanly() -> None:
    """The bot module should import without requiring python-telegram-bot."""
    assert hasattr(bot_module, "run_bot")
    assert hasattr(bot_module, "_handle_start")
    assert hasattr(bot_module, "_handle_learn")
    assert hasattr(bot_module, "_GREETING")
    assert hasattr(bot_module, "_HELP_TEXT")


def test_bot_constants_are_nonempty() -> None:
    """Greeting and help text must contain meaningful content."""
    assert len(_GREETING) > 20
    assert "/learn" in _HELP_TEXT
    assert "/ask" in _HELP_TEXT
    assert "/quit" in _HELP_TEXT
    assert "/help" in _HELP_TEXT
    assert "/progress" in _HELP_TEXT
    assert "/start" in _HELP_TEXT


# ---------------------------------------------------------------------------
# /start handler
# ---------------------------------------------------------------------------


async def test_bot_start_handler_sends_greeting() -> None:
    """The /start handler should send the greeting message."""
    update = _make_update()
    ctx = _make_context()
    await _handle_start(update, ctx)
    update.message.reply_text.assert_called_once_with(_GREETING)


# ---------------------------------------------------------------------------
# /help handler
# ---------------------------------------------------------------------------


async def test_bot_help_handler_sends_commands() -> None:
    """The /help handler should send the help text."""
    update = _make_update()
    ctx = _make_context()
    await _handle_help(update, ctx)
    update.message.reply_text.assert_called_once_with(_HELP_TEXT)


# ---------------------------------------------------------------------------
# /learn handler
# ---------------------------------------------------------------------------


async def test_bot_learn_handler_rejects_missing_topic() -> None:
    """The /learn handler rejects a missing topic."""
    update = _make_update(chat_id=99999)
    ctx = _make_context(args=[])

    await _handle_learn(update, ctx)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "usage" in call_text.lower() or "/learn" in call_text.lower()


async def test_bot_learn_handler_rejects_duplicate_session() -> None:
    """If a session already exists for the chat, /learn rejects."""
    chat_id = 77777
    _make_bot_session(chat_id=chat_id, register=True)
    update = _make_update(chat_id=chat_id)
    ctx = _make_context(args=["mitosis"])

    await _handle_learn(update, ctx)

    call_text: str = update.message.reply_text.call_args[0][0]
    assert "already" in call_text.lower() or "/quit" in call_text.lower()

    # cleanup
    _sessions.pop(chat_id, None)


async def test_bot_learn_handler_creates_session_successfully() -> None:
    """/learn <topic> with a valid topic sets up a session."""
    chat_id = 55555
    _sessions.pop(chat_id, None)  # ensure clean

    update = _make_update(chat_id=chat_id, first_name="Bob")
    ctx = _make_context(args=["photosynthesis"])

    with patch("clawstu.bot._build_bot_context") as mock_build:
        # Provide a minimal live-content mock
        mock_live = MagicMock()
        mock_cfg = MagicMock()
        mock_router = MagicMock()
        mock_build.return_value = (mock_cfg, mock_router, mock_live)

        mock_runner = MagicMock(spec=SessionRunner)
        profile = LearnerProfile(
            learner_id="Bob", age_bracket=AgeBracket.EARLY_HIGH,
        )
        session = Session(
            learner_id="Bob", domain=Domain.OTHER, topic="photosynthesis",
        )
        session.phase = SessionPhase.TEACHING
        mock_runner.onboard_with_topic = AsyncMock(
            return_value=(profile, session),
        )
        # next_directive returns a directive with a block
        mock_block = MagicMock()
        mock_block.title = "What is Photosynthesis?"
        mock_block.body = "Plants convert sunlight into energy."
        mock_directive = MagicMock()
        mock_directive.block = mock_block
        mock_runner.next_directive.return_value = mock_directive

        with patch("clawstu.bot.SessionRunner", return_value=mock_runner):
            await _handle_learn(update, ctx)

        # Should have been called at least twice: "Setting up..." + block text
        assert update.message.reply_text.call_count >= 2
        assert chat_id in _sessions

    # cleanup
    _sessions.pop(chat_id, None)


async def test_bot_learn_handler_no_block_directive() -> None:
    """/learn succeeds even when next_directive returns no block."""
    chat_id = 55556
    _sessions.pop(chat_id, None)

    update = _make_update(chat_id=chat_id, first_name="Eve")
    ctx = _make_context(args=["algebra"])

    with patch("clawstu.bot._build_bot_context") as mock_build:
        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_runner = MagicMock(spec=SessionRunner)
        profile = LearnerProfile(
            learner_id="Eve", age_bracket=AgeBracket.MIDDLE,
        )
        session = Session(
            learner_id="Eve", domain=Domain.OTHER, topic="algebra",
        )
        mock_runner.onboard_with_topic = AsyncMock(
            return_value=(profile, session),
        )
        mock_directive = MagicMock()
        mock_directive.block = None
        mock_directive.message = "Session started."
        mock_runner.next_directive.return_value = mock_directive

        with patch("clawstu.bot.SessionRunner", return_value=mock_runner):
            await _handle_learn(update, ctx)

        # Final message should be the directive's message
        last_call_text: str = update.message.reply_text.call_args[0][0]
        assert "session" in last_call_text.lower() or "started" in last_call_text.lower()

    _sessions.pop(chat_id, None)


async def test_bot_learn_handler_no_user_name() -> None:
    """/learn uses 'Learner' when effective_user is None."""
    chat_id = 55557
    _sessions.pop(chat_id, None)

    update = _make_update(chat_id=chat_id)
    update.effective_user = None
    ctx = _make_context(args=["gravity"])

    with patch("clawstu.bot._build_bot_context") as mock_build:
        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock())
        mock_runner = MagicMock(spec=SessionRunner)
        profile = LearnerProfile(
            learner_id="Learner", age_bracket=AgeBracket.EARLY_HIGH,
        )
        session = Session(
            learner_id="Learner", domain=Domain.OTHER, topic="gravity",
        )
        mock_runner.onboard_with_topic = AsyncMock(
            return_value=(profile, session),
        )
        mock_directive = MagicMock()
        mock_directive.block = None
        mock_directive.message = "Ready."
        mock_runner.next_directive.return_value = mock_directive

        with patch("clawstu.bot.SessionRunner", return_value=mock_runner):
            await _handle_learn(update, ctx)

        # Should have called onboard_with_topic with learner_id="Learner"
        call_kwargs = mock_runner.onboard_with_topic.call_args
        assert call_kwargs[1]["learner_id"] == "Learner"

    _sessions.pop(chat_id, None)


# ---------------------------------------------------------------------------
# /ask handler
# ---------------------------------------------------------------------------


async def test_bot_ask_handler_returns_answer() -> None:
    """The /ask handler should return a response to a question."""
    update = _make_update()
    ctx = _make_context(args=["what", "is", "photosynthesis"])

    await _handle_ask(update, ctx)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "photosynthesis" in call_text.lower()


async def test_bot_ask_handler_rejects_missing_question() -> None:
    """/ask with no arguments sends usage info."""
    update = _make_update()
    ctx = _make_context(args=[])

    await _handle_ask(update, ctx)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "usage" in call_text.lower() or "/ask" in call_text.lower()


async def test_bot_ask_handler_rejects_boundary_violation() -> None:
    """/ask rejects boundary-violating text."""
    update = _make_update()
    ctx = _make_context(args=["pretend", "to", "be", "my", "friend"])

    await _handle_ask(update, ctx)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "can't" in call_text.lower() or "on-topic" in call_text.lower()


# ---------------------------------------------------------------------------
# /progress handler
# ---------------------------------------------------------------------------


async def test_bot_progress_handler_no_session() -> None:
    """/progress with no active session returns guidance."""
    chat_id = 44444
    _sessions.pop(chat_id, None)

    update = _make_update(chat_id=chat_id)
    ctx = _make_context()

    await _handle_progress(update, ctx)

    call_text: str = update.message.reply_text.call_args[0][0]
    assert "no active session" in call_text.lower()


async def test_bot_progress_handler_with_session() -> None:
    """/progress with an active session returns stats."""
    chat_id = 44445
    bot_session = _make_bot_session(
        chat_id=chat_id,
        topic="photosynthesis",
        blocks_presented=3,
        reteach_count=1,
    )
    # Add a ZPD entry so the domain branch is exercised.
    bot_session.profile.zpd_by_domain[Domain.OTHER] = ZPDEstimate(
        domain=Domain.OTHER,
        tier=ComplexityTier.MEETING,
        confidence=0.65,
    )

    update = _make_update(chat_id=chat_id)
    ctx = _make_context()

    await _handle_progress(update, ctx)

    call_text: str = update.message.reply_text.call_args[0][0]
    assert "photosynthesis" in call_text.lower() or "other" in call_text.lower()
    assert "3" in call_text  # blocks_presented
    assert "1" in call_text  # reteach_count
    assert "0.65" in call_text  # confidence

    _sessions.pop(chat_id, None)


# ---------------------------------------------------------------------------
# /quit handler
# ---------------------------------------------------------------------------


async def test_bot_quit_handler_no_session() -> None:
    """The /quit handler should say no active session when none exists."""
    chat_id = 88888
    _sessions.pop(chat_id, None)

    update = _make_update(chat_id=chat_id)
    ctx = _make_context()

    await _handle_quit(update, ctx)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "no active session" in call_text.lower()


async def test_bot_quit_handler_with_session() -> None:
    """/quit with an active session calls runner.close and removes it."""
    chat_id = 88889
    bot_session = _make_bot_session(chat_id=chat_id)
    # Patch runner.close to return a known summary string.
    bot_session.runner.close = MagicMock(return_value="Session abc done.")

    update = _make_update(chat_id=chat_id)
    ctx = _make_context()

    await _handle_quit(update, ctx)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "session closed" in call_text.lower() or "abc" in call_text.lower()
    assert chat_id not in _sessions


# ---------------------------------------------------------------------------
# Free-text message handler
# ---------------------------------------------------------------------------


async def test_message_handler_no_session() -> None:
    """Free text with no session directs user to /learn."""
    chat_id = 33333
    _sessions.pop(chat_id, None)

    update = _make_update(chat_id=chat_id)
    update.message.text = "I think the answer is 42"
    ctx = _make_context()

    await _handle_message(update, ctx)

    call_text: str = update.message.reply_text.call_args[0][0]
    assert "/learn" in call_text.lower() or "/ask" in call_text.lower()


async def test_message_handler_crisis_detection() -> None:
    """Crisis text pauses the session and shows safety resources."""
    chat_id = 33334
    _make_bot_session(chat_id=chat_id)

    update = _make_update(chat_id=chat_id)
    update.message.text = "I want to hurt myself"
    ctx = _make_context()

    await _handle_message(update, ctx)

    call_text: str = update.message.reply_text.call_args[0][0]
    assert "988" in call_text or "crisis" in call_text.lower()
    # Session should be removed.
    assert chat_id not in _sessions


async def test_message_handler_boundary_violation() -> None:
    """Boundary-violating text gets a polite refusal."""
    chat_id = 33335
    _make_bot_session(chat_id=chat_id)

    update = _make_update(chat_id=chat_id)
    update.message.text = "pretend to be my friend"
    ctx = _make_context()

    await _handle_message(update, ctx)

    # Boundary => "on-topic" type message -- session stays active.
    found_boundary_reply = False
    for call in update.message.reply_text.call_args_list:
        text = call[0][0]
        if "on-topic" in text.lower() or "stuart" in text.lower():
            found_boundary_reply = True
            break
    assert found_boundary_reply
    # Session should still exist (boundary doesn't kill session).
    assert chat_id in _sessions

    _sessions.pop(chat_id, None)


async def test_message_handler_checking_phase_correct() -> None:
    """A correct answer during CHECKING phase replies 'Correct'."""
    chat_id = 33336
    bot_session = _make_bot_session(
        chat_id=chat_id, phase=SessionPhase.CHECKING,
    )

    # Mock the runner's check workflow.
    mock_item = MagicMock()
    bot_session.runner.select_check = MagicMock(return_value=mock_item)

    mock_result = MagicMock()
    mock_result.correct = True
    mock_result.notes = None
    bot_session.evaluator.evaluate = MagicMock(return_value=mock_result)

    bot_session.runner.record_check = MagicMock()

    # next_directive returns a teaching directive with a block.
    mock_block = MagicMock()
    mock_block.title = "Next Block"
    mock_block.body = "Content here."
    mock_directive = MagicMock()
    mock_directive.phase = SessionPhase.TEACHING
    mock_directive.block = mock_block
    mock_directive.message = None
    bot_session.runner.next_directive = MagicMock(return_value=mock_directive)

    update = _make_update(chat_id=chat_id)
    update.message.text = "The answer is mitochondria"
    ctx = _make_context()

    await _handle_message(update, ctx)

    # Should include "Correct" in one of the replies.
    replies = [call[0][0] for call in update.message.reply_text.call_args_list]
    assert any("correct" in r.lower() for r in replies)

    _sessions.pop(chat_id, None)


async def test_message_handler_checking_phase_incorrect() -> None:
    """An incorrect answer during CHECKING phase replies with notes."""
    chat_id = 33337
    bot_session = _make_bot_session(
        chat_id=chat_id, phase=SessionPhase.CHECKING,
    )

    mock_item = MagicMock()
    bot_session.runner.select_check = MagicMock(return_value=mock_item)

    mock_result = MagicMock()
    mock_result.correct = False
    mock_result.notes = "Remember the key concept."
    bot_session.evaluator.evaluate = MagicMock(return_value=mock_result)

    bot_session.runner.record_check = MagicMock()

    mock_directive = MagicMock()
    mock_directive.phase = SessionPhase.TEACHING
    mock_directive.block = MagicMock()
    mock_directive.block.title = "Reteach"
    mock_directive.block.body = "Here's another way to think about it."
    mock_directive.message = None
    bot_session.runner.next_directive = MagicMock(return_value=mock_directive)

    update = _make_update(chat_id=chat_id)
    update.message.text = "I don't know"
    ctx = _make_context()

    await _handle_message(update, ctx)

    replies = [call[0][0] for call in update.message.reply_text.call_args_list]
    assert any("remember" in r.lower() for r in replies)

    _sessions.pop(chat_id, None)


async def test_message_handler_session_closing() -> None:
    """When directive says CLOSING, the session closes and summary is sent."""
    chat_id = 33338
    bot_session = _make_bot_session(
        chat_id=chat_id, phase=SessionPhase.TEACHING,
    )

    mock_directive = MagicMock()
    mock_directive.phase = SessionPhase.CLOSING
    mock_directive.block = None
    mock_directive.message = None
    bot_session.runner.next_directive = MagicMock(return_value=mock_directive)
    bot_session.runner.close = MagicMock(return_value="Good work today.")

    update = _make_update(chat_id=chat_id)
    update.message.text = "Looks good"
    ctx = _make_context()

    await _handle_message(update, ctx)

    replies = [call[0][0] for call in update.message.reply_text.call_args_list]
    assert any("complete" in r.lower() or "good work" in r.lower() for r in replies)
    assert chat_id not in _sessions


async def test_message_handler_directive_with_message_only() -> None:
    """When directive has a message but no block, the message is sent."""
    chat_id = 33339
    bot_session = _make_bot_session(
        chat_id=chat_id, phase=SessionPhase.TEACHING,
    )

    mock_directive = MagicMock()
    mock_directive.phase = SessionPhase.TEACHING
    mock_directive.block = None
    mock_directive.message = "Think about this carefully."
    bot_session.runner.next_directive = MagicMock(return_value=mock_directive)

    update = _make_update(chat_id=chat_id)
    update.message.text = "hmm"
    ctx = _make_context()

    await _handle_message(update, ctx)

    replies = [call[0][0] for call in update.message.reply_text.call_args_list]
    assert any("think about" in r.lower() for r in replies)

    _sessions.pop(chat_id, None)


async def test_message_handler_empty_text() -> None:
    """An empty text message is handled gracefully."""
    chat_id = 33340
    bot_session = _make_bot_session(
        chat_id=chat_id, phase=SessionPhase.TEACHING,
    )

    mock_directive = MagicMock()
    mock_directive.phase = SessionPhase.TEACHING
    mock_directive.block = None
    mock_directive.message = "Keep going."
    bot_session.runner.next_directive = MagicMock(return_value=mock_directive)

    update = _make_update(chat_id=chat_id)
    update.message.text = ""
    ctx = _make_context()

    await _handle_message(update, ctx)

    # Should not crash, should still send a reply.
    assert update.message.reply_text.call_count >= 1

    _sessions.pop(chat_id, None)


# ---------------------------------------------------------------------------
# run_bot and CLI wiring
# ---------------------------------------------------------------------------


def test_bot_run_bot_raises_without_telegram_dep() -> None:
    """run_bot should raise RuntimeError if python-telegram-bot is not installed."""
    with (
        patch.dict("sys.modules", {"telegram": None, "telegram.ext": None}),
        pytest.raises(RuntimeError, match="telegram extra"),
    ):
        bot_module.run_bot(token="fake-token")


def test_bot_command_exists_in_cli_help() -> None:
    """The 'bot' command should exist in the CLI app."""
    from typer.testing import CliRunner

    from clawstu.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["bot", "--help"])
    assert result.exit_code == 0
    assert "telegram" in result.output.lower() or "token" in result.output.lower()


# ---------------------------------------------------------------------------
# _build_bot_context smoke test
# ---------------------------------------------------------------------------


def test_build_bot_context_returns_triple() -> None:
    """_build_bot_context returns (config, router, live) triple."""
    from clawstu.bot import _build_bot_context

    cfg, router, live = _build_bot_context()
    assert cfg is not None
    assert router is not None
    assert live is not None
