"""Telegram bot for Claw-STU learning sessions.

Wraps the same session logic as ``clawstu learn`` but over Telegram
messages instead of terminal stdin. Students interact with Stuart
through Telegram commands:

- ``/start`` -- greeting
- ``/learn <topic>`` -- begin a learning session
- ``/ask <question>`` -- one-shot Socratic Q&A
- ``/progress`` -- text-based progress dashboard
- ``/quit`` -- close the active session
- ``/help`` -- list available commands

The bot uses ``python-telegram-bot`` in polling mode. Session state
lives in-memory per ``chat_id``; no persistence across bot restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawstu.api.state import AppState, SessionBundle
from clawstu.assessment.evaluator import Evaluator
from clawstu.engagement.session import Session, SessionPhase, SessionRunner
from clawstu.orchestrator.config import AppConfig, ensure_data_dir, load_config
from clawstu.orchestrator.live_content import LiveContentGenerator
from clawstu.orchestrator.router import ModelRouter
from clawstu.profile.model import Domain, LearnerProfile
from clawstu.safety.boundaries import BoundaryEnforcer
from clawstu.safety.escalation import EscalationHandler
from clawstu.safety.gate import InboundSafetyGate


@dataclass
class _BotSession:
    """Per-chat session state."""

    profile: LearnerProfile
    session: Session
    runner: SessionRunner
    evaluator: Evaluator
    state: AppState


# In-memory map of chat_id -> active bot session
_sessions: dict[int, _BotSession] = {}

_GATE = InboundSafetyGate(EscalationHandler(), BoundaryEnforcer())

_HELP_TEXT = (
    "Available commands:\n"
    "/start -- greeting\n"
    "/learn <topic> -- start a learning session\n"
    "/ask <question> -- one-shot Socratic Q&A\n"
    "/progress -- your progress dashboard\n"
    "/quit -- close the current session\n"
    "/help -- this message"
)

_GREETING = (
    "Hi. I'm Stuart.\n\n"
    "I'm a personal learning agent. Send /learn <topic> to start a session, "
    "or /ask <question> for a quick answer.\n\n"
    "Type /help for all commands."
)


def _build_bot_context() -> tuple[AppConfig, ModelRouter, LiveContentGenerator]:
    """Build provider chain for the bot, reusing the same factory as the CLI."""
    from clawstu.api.main import build_providers

    cfg = load_config()
    ensure_data_dir(cfg)
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    live = LiveContentGenerator(router=router)
    return cfg, router, live


async def _handle_start(update: Any, context: Any) -> None:
    """Handle /start command."""
    await update.message.reply_text(_GREETING)


async def _handle_help(update: Any, context: Any) -> None:
    """Handle /help command."""
    await update.message.reply_text(_HELP_TEXT)


async def _bot_create_session(
    topic: str, name: str,
) -> _BotSession:
    """Onboard a learner and build a ``_BotSession`` for the Telegram bot."""
    _cfg, _router, live = _build_bot_context()
    runner = SessionRunner(live_content=live)
    state = AppState(cache_size=4, runner=runner)
    evaluator = Evaluator()

    profile, session = await runner.onboard_with_topic(
        learner_id=name, age=15, domain=Domain.OTHER, topic=topic,
    )
    bundle = SessionBundle(profile=profile, session=session)
    state.put(bundle)

    return _BotSession(
        profile=profile, session=session,
        runner=runner, evaluator=evaluator, state=state,
    )


async def _handle_learn(update: Any, context: Any) -> None:
    """Handle /learn <topic> -- create a session and send the first block."""
    chat_id: int = update.effective_chat.id
    args: list[str] = context.args or []
    if not args:
        await update.message.reply_text("Usage: /learn <topic>\nExample: /learn photosynthesis")
        return

    topic = " ".join(args)
    if chat_id in _sessions:
        await update.message.reply_text(
            "You already have an active session. Send /quit first."
        )
        return

    name = (
        update.effective_user.first_name
        if update.effective_user else "Learner"
    )
    await update.message.reply_text(f"Setting up a session on: {topic}...")
    bot_session = await _bot_create_session(topic, name)
    _sessions[chat_id] = bot_session

    directive = bot_session.runner.next_directive(
        bot_session.profile, bot_session.session,
    )
    if directive.block is not None:
        block = directive.block
        await update.message.reply_text(
            f"*{block.title}*\n\n{block.body}"[:4096], parse_mode=None,
        )
        await update.message.reply_text(
            "Reply with your answer when you're ready."
        )
    else:
        await update.message.reply_text(
            directive.message or "Session started. Send your answers as messages."
        )


async def _handle_ask(update: Any, context: Any) -> None:
    """Handle /ask <question> -- one-shot Socratic Q&A."""
    args: list[str] = context.args or []
    if not args:
        await update.message.reply_text("Usage: /ask <question>")
        return

    question = " ".join(args)
    decision = _GATE.scan(question)
    if decision.action != "allow":
        await update.message.reply_text(
            "I can't respond to that. Let's keep things on-topic."
        )
        return

    # Use the same echo-based response as the Phase 5 placeholder
    await update.message.reply_text(
        f"You asked: {question}\n\n"
        "I hear you. Tell me more about what you're trying to understand."
    )


async def _handle_progress(update: Any, context: Any) -> None:
    """Handle /progress -- send the progress dashboard as text."""
    chat_id: int = update.effective_chat.id
    bot_session = _sessions.get(chat_id)
    if bot_session is None:
        await update.message.reply_text(
            "No active session. Start one with /learn <topic>."
        )
        return

    profile = bot_session.profile
    session = bot_session.session
    lines: list[str] = [
        f"Topic: {session.topic or session.domain.value}",
        f"Blocks presented: {session.blocks_presented}",
        f"Reteach count: {session.reteach_count}",
    ]
    if profile.zpd_by_domain:
        for domain, zpd in profile.zpd_by_domain.items():
            lines.append(f"ZPD ({domain.value}): {zpd.tier.value} (conf {zpd.confidence:.2f})")
    await update.message.reply_text("\n".join(lines))


async def _handle_quit(update: Any, context: Any) -> None:
    """Handle /quit -- close the session and send summary."""
    chat_id: int = update.effective_chat.id
    bot_session = _sessions.pop(chat_id, None)
    if bot_session is None:
        await update.message.reply_text("No active session to close.")
        return

    summary = bot_session.runner.close(
        bot_session.profile, bot_session.session,
    )
    await update.message.reply_text(f"Session closed.\n\n{summary}")


async def _bot_send_directive(update: Any, directive: Any) -> None:
    """Send the next directive's block or message to the Telegram chat."""
    if directive.block is not None:
        block = directive.block
        text_out = f"*{block.title}*\n\n{block.body}"
        await update.message.reply_text(text_out[:4096], parse_mode=None)
        await update.message.reply_text(
            "Reply with your answer when you're ready."
        )
    elif directive.message:
        await update.message.reply_text(directive.message)


async def _handle_message(update: Any, context: Any) -> None:
    """Handle free-text messages as answers to the current session."""
    chat_id: int = update.effective_chat.id
    bot_session = _sessions.get(chat_id)
    if bot_session is None:
        await update.message.reply_text(
            "No active session. Send /learn <topic> to start one, "
            "or /ask <question> for a quick answer."
        )
        return

    text: str = update.message.text or ""
    decision = _GATE.scan(text)
    if decision.action == "crisis":
        bot_session.session.phase = SessionPhase.CRISIS_PAUSE
        await update.message.reply_text(
            "I'm pausing this session. If you need help, please reach out "
            "to a trusted adult or call 988 (Suicide & Crisis Lifeline)."
        )
        _sessions.pop(chat_id, None)
        return
    if decision.action == "boundary":
        await update.message.reply_text(
            "I'm Stuart, a learning tool. Let's stay on-topic."
        )
        return

    session = bot_session.session
    profile = bot_session.profile
    runner = bot_session.runner

    if session.phase is SessionPhase.CHECKING:
        check_item = runner.select_check(session)
        result = bot_session.evaluator.evaluate(check_item, text)
        runner.record_check(profile, session, check_item, result)
        if result.correct:
            await update.message.reply_text("Correct! Moving on.")
        else:
            notes = result.notes or "Not quite. Let me try a different approach."
            await update.message.reply_text(notes)

    directive = runner.next_directive(profile, session)
    if directive.phase in (SessionPhase.CLOSING, SessionPhase.CLOSED):
        summary = runner.close(profile, session)
        _sessions.pop(chat_id, None)
        await update.message.reply_text(f"Session complete.\n\n{summary}")
        return

    await _bot_send_directive(update, directive)


def run_bot(*, token: str) -> None:
    """Start the Telegram bot in polling mode.

    Lazily imports ``python-telegram-bot`` so the core install stays
    lean. If the optional dep is missing, prints a helpful message.
    """
    try:
        from telegram.ext import (
            ApplicationBuilder,
            CommandHandler,
            MessageHandler,
            filters,
        )
    except ImportError:
        raise RuntimeError(
            "Telegram support requires the telegram extra.\n"
            "Install it with: pip install 'clawstu[telegram]'"
        ) from None

    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", _handle_start))
    application.add_handler(CommandHandler("help", _handle_help))
    application.add_handler(CommandHandler("learn", _handle_learn))
    application.add_handler(CommandHandler("ask", _handle_ask))
    application.add_handler(CommandHandler("progress", _handle_progress))
    application.add_handler(CommandHandler("quit", _handle_quit))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message)
    )

    application.run_polling()
