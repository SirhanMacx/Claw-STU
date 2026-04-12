"""Conversational CLI chat loop for ``clawstu learn``.

The ``clawstu learn`` command drops the student into an interactive
learning session with Stuart. This module owns the chat loop: Rich-
powered terminal output, stdin-based answer collection, in-process
``SessionRunner`` + ``AppState`` + ``ModelRouter`` wiring, graceful
Ctrl-C, and the closing summary.

Nothing in this file has any pedagogical content. It is a thin
presentation layer over the Phase 1-7 session runner. Every decision
about what to teach, how to calibrate, and how to rotate modalities
lives in :mod:`clawstu.engagement.session` -- NOT here.

Design notes
------------

* The chat loop is driven through a :class:`ChatIO` protocol so tests
  can script the flow without touching real stdin/stdout. The default
  implementation (:class:`_RichChatIO`) wraps a :class:`rich.console.Console`
  and ``rich.prompt.Prompt``/``IntPrompt``; the suite-side fake
  (:class:`_FakeChatIO` in ``tests/test_cli_chat.py``) pops answers
  from a scripted queue and collects emitted messages for assertion.

* Session construction reuses :func:`clawstu.api.main.build_providers`
  so there is exactly one provider-factory in the codebase. The chat
  loop runs entirely in-process -- it does NOT go through the HTTP
  API -- and mirrors the same session-runner invocation order as the
  ``api.session`` router.

* Every mutating runner call is followed by an ``AppState.checkpoint``
  so a process kill or Ctrl-C mid-session leaves durable persistence
  on disk. The last act of :func:`run_chat_session` is to ``drop``
  the finished session (which flushes one final time).

Layering
--------

``clawstu/cli_chat.py`` is a top-level module, sibling of
``clawstu/cli.py`` and ``clawstu/setup_wizard.py``. It is treated as
``_cli`` by the hierarchy guard so it can reach into :mod:`clawstu.api`
(for ``build_providers`` and ``AppState``) and all the lower layers.
``setup_wizard`` deliberately does NOT import from cli_chat, and
nothing below the cli layer imports from cli_chat either -- it is a
sink in the import DAG.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt

from clawstu.api.main import build_providers
from clawstu.api.state import AppState, SessionBundle
from clawstu.assessment.evaluator import Evaluator
from clawstu.assessment.generator import AssessmentItem
from clawstu.curriculum.content import LearningBlock
from clawstu.engagement.session import (
    NoArtifactError,
    Session,
    SessionPhase,
    SessionRunner,
    TeachBlockResult,
)
from clawstu.orchestrator.config import AppConfig, ensure_data_dir, load_config
from clawstu.orchestrator.live_content import LiveContentGenerator
from clawstu.orchestrator.providers import LLMProvider
from clawstu.orchestrator.router import ModelRouter
from clawstu.orchestrator.task_kinds import TaskKind
from clawstu.profile.model import Domain, LearnerProfile

OPENING_BANNER = """Hi. I'm Stuart.

I'm a personal learning agent. I'll help you learn about anything
you want — math, history, science, language, whatever. Real
topics, real content, adapted to how you learn.

Three things to know before we start:

  1. I'm not a tutor, a friend, or a therapist. I'm a cognitive
     tool. I won't pretend to care about you the way a person
     would, and I won't replace a teacher or a parent.

  2. I use AI to generate content. I can be wrong. Always check
     important facts with a teacher, a primary source, or someone
     who knows the subject.

  3. If you're in crisis or need to talk to a person, please reach
     out to a trusted adult or crisis resources. I'll pause the
     session and help you find help.
"""

_OFFLINE_WARNING = (
    "⚠ Running in offline demo mode. Content will be deterministic "
    "stubs.\n  Run `clawstu setup` to configure a real provider "
    "(Anthropic, OpenAI,\n  OpenRouter, or local Ollama) for real "
    "learning content."
)


class ChatIO(Protocol):
    """Tests inject this so they can script the chat-loop flow.

    The real chat loop uses :mod:`rich` under the hood; the test fake
    returns canned responses in order. The protocol is intentionally
    minimal (text/int prompts + say + confirm) so adding a new prompt
    style later does not silently break test fakes.
    """

    def ask_text(self, prompt: str, *, default: str | None = None) -> str:
        """Prompt the student for a free-text answer."""
        ...

    def ask_int(self, prompt: str, *, default: int | None = None) -> int:
        """Prompt the student for an integer answer."""
        ...

    def say(
        self,
        message: str,
        *,
        panel_title: str | None = None,
        border_style: str | None = None,
        markdown: bool = False,
    ) -> None:
        """Emit a message to the student.

        When ``panel_title`` or ``border_style`` is set, the real
        implementation wraps the message in a Rich ``Panel``. When
        ``markdown`` is True, the real implementation renders the
        message through the Rich Markdown renderer before panelling.
        """
        ...

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        """Ask the student a yes/no question."""
        ...


@dataclass
class ChatInputs:
    """Seed values for the chat session.

    When any field is ``None`` the chat loop prompts the student for
    it interactively via the ``ChatIO`` implementation. Callers that
    know what they want (unit tests, non-interactive scripts, a CLI
    option override) pass a fully populated instance to skip the
    corresponding prompt.
    """

    learner_id: str | None = None
    age: int | None = None
    topic: str | None = None
    domain: Domain | None = None


class _RichChatIO:
    """Default :class:`ChatIO` implementation backed by :mod:`rich`."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def ask_text(self, prompt: str, *, default: str | None = None) -> str:
        # Rich's Prompt.ask returns Any (because of the Ellipsis-
        # sentinel default handling). We narrow to str and strip.
        if default is None:
            raw = Prompt.ask(prompt, console=self._console)
        else:
            raw = Prompt.ask(prompt, console=self._console, default=default)
        return str(raw).strip()

    def ask_int(self, prompt: str, *, default: int | None = None) -> int:
        if default is None:
            raw = IntPrompt.ask(prompt, console=self._console)
        else:
            raw = IntPrompt.ask(prompt, console=self._console, default=default)
        return int(raw)

    def say(
        self,
        message: str,
        *,
        panel_title: str | None = None,
        border_style: str | None = None,
        markdown: bool = False,
    ) -> None:
        rendered: Any = Markdown(message) if markdown else message
        if panel_title is not None or border_style is not None:
            panel = Panel(
                rendered,
                title=panel_title,
                border_style=border_style or "blue",
            )
            self._console.print(panel)
        else:
            self._console.print(rendered)

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        response = Prompt.ask(
            prompt,
            console=self._console,
            choices=["y", "n"],
            default="y" if default else "n",
        )
        return str(response).strip().lower().startswith("y")


@dataclass
class _ChatContext:
    """Plumbing the chat loop needs on every iteration.

    Keeps ``run_chat_session`` and ``run_resume_session`` from having
    to re-derive the router/live/runner/state quartet every time the
    teach loop cares about one of them.
    """

    cfg: AppConfig
    providers: dict[str, LLMProvider]
    router: ModelRouter
    live: LiveContentGenerator
    runner: SessionRunner
    state: AppState
    evaluator: Evaluator = field(default_factory=Evaluator)


def _build_chat_context(state: AppState | None = None) -> _ChatContext:
    """Build the shared chat context (config, router, live, runner, state).

    Kept as a separate function so :func:`run_chat_session` and
    :func:`run_resume_session` use the same wiring, and so tests can
    inject a pre-built ``AppState`` to pin persistence to an in-memory
    store.
    """
    cfg = load_config()
    ensure_data_dir(cfg)
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    live = LiveContentGenerator(router=router)
    runner = SessionRunner(live_content=live)
    # AppState defaults to an InMemoryPersistentStore. Tests that need
    # a specific store pass one in via the ``state`` argument. The
    # small cache_size keeps the CLI's footprint minimal -- a single
    # interactive session only needs one slot.
    resolved_state = state if state is not None else AppState(
        cache_size=4, runner=runner,
    )
    return _ChatContext(
        cfg=cfg,
        providers=providers,
        router=router,
        live=live,
        runner=runner,
        state=resolved_state,
    )


def _real_providers(providers: dict[str, LLMProvider]) -> set[str]:
    """Return the set of non-echo provider names that were built.

    A real provider is one we expect to actually answer requests on
    the network: ``anthropic``, ``openai``, ``openrouter``, or a
    reachable local ``ollama``. ``echo`` is excluded because it only
    emits deterministic stubs. ``ollama`` is included when present --
    build_providers always constructs an OllamaProvider, so the mere
    presence of the key is only a weak signal, but it's the best one
    we have without pinging the daemon.

    Tests monkeypatch ``ANTHROPIC_API_KEY`` (etc.) to drive the warning
    path on and off without touching this helper.
    """
    return {name for name in providers if name != "echo"}


def _format_provider_label(router: ModelRouter) -> str:
    """Human-readable ``provider/model`` for the setup-summary line.

    Pulls the Socratic-dialogue route because that's the task most
    closely tied to "content the student will see during a session".
    The label is cosmetic -- the actual routing is done per-task.
    """
    provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    provider_name = type(provider).__name__.replace("Provider", "").lower()
    return f"{provider_name}/{model}"


def run_chat_session(
    *,
    inputs: ChatInputs | None = None,
    io: ChatIO | None = None,
    state: AppState | None = None,
) -> None:
    """Run an interactive learning session with Stuart.

    The entry point the Typer ``learn`` command calls. Wraps
    :func:`_run_async_session` in ``asyncio.run`` and translates a
    ``KeyboardInterrupt`` into a graceful "checkpoint + exit" message.

    Parameters
    ----------
    inputs:
        Seed values for learner_id, age, topic, and domain. Any
        ``None`` field is prompted for interactively. Defaults to
        :class:`ChatInputs` with every field ``None``.
    io:
        :class:`ChatIO` override. Defaults to :class:`_RichChatIO`.
        Tests inject a :class:`_FakeChatIO` to drive the loop
        deterministically without touching real stdin/stdout.
    state:
        :class:`AppState` override. Defaults to a fresh instance
        backed by the in-memory persistent store. Tests can pass
        their own to inspect persisted bundles afterwards.
    """
    resolved_io: ChatIO = io or _RichChatIO()
    resolved_inputs = inputs or ChatInputs()
    try:
        asyncio.run(_run_async_session(resolved_inputs, resolved_io, state))
    except KeyboardInterrupt:
        resolved_io.say(
            "\n> Pausing session...\n"
            "  ✓ Checkpoint saved. Run `clawstu resume` to pick this "
            "back up.",
            border_style="yellow",
        )
        # State was checkpointed on every directive cycle so no
        # additional flushing is needed here. Re-raise as SystemExit
        # so Typer reports a clean exit code.
        raise SystemExit(0) from None


async def _run_async_session(
    inputs: ChatInputs,
    io: ChatIO,
    state: AppState | None,
) -> None:
    """Async chat loop driver.

    Split out from :func:`run_chat_session` so the synchronous entry
    point only has to own the ``asyncio.run`` + ``KeyboardInterrupt``
    wrapping.
    """
    io.say(OPENING_BANNER, panel_title="Stuart", border_style="blue")

    learner_id = _resolve_learner_id(inputs, io)
    age = _resolve_age(inputs, io)
    topic_text = _resolve_topic(inputs, io)
    domain = inputs.domain or Domain.OTHER

    ctx = _build_chat_context(state)

    if not _real_providers(ctx.providers):
        io.say(_OFFLINE_WARNING, border_style="yellow")

    io.say("> Setting up your session...")

    profile, session = await ctx.runner.onboard_with_topic(
        learner_id=learner_id,
        age=age,
        domain=domain,
        topic=topic_text,
    )
    bundle = SessionBundle(profile=profile, session=session)
    ctx.state.put(bundle)

    provider_label = _format_provider_label(ctx.router)
    io.say(
        f"  ✓ Topic: {topic_text}\n"
        f"  ✓ Age bracket: {profile.age_bracket.value}\n"
        f"  ✓ Domain: {domain.value}\n"
        f"  ✓ Provider: {provider_label}"
    )

    # Calibration only runs when the runner left us in CALIBRATING.
    # The live-topic path (`onboard_with_topic`) skips calibration and
    # lands directly in TEACHING, so the chat loop mirrors that
    # behavior rather than forcing a calibration cycle the runner
    # never asked for. When a future phase wires LLM-backed
    # calibration for arbitrary topics, flipping the returned phase
    # to CALIBRATING in the runner will automatically re-enable this
    # branch without any change to the chat loop.
    if session.phase is SessionPhase.CALIBRATING:
        _run_calibration_loop(io, ctx, profile, session)

    _run_teach_loop(io, ctx, profile, session)

    # Close + summary. Runner returns a summary string but the
    # presentation layer builds its own human-facing closing screen
    # from the profile / session state.
    ctx.runner.close(profile, session)
    ctx.state.drop(session.id)
    _render_session_summary(io, profile, session)


def run_resume_session(
    *,
    learner_id: str,
    io: ChatIO | None = None,
    state: AppState | None = None,
) -> None:
    """Resume a session from a pre-generated artifact.

    Mirrors :func:`run_chat_session` but loads a primed session via
    :meth:`SessionRunner.warm_start` instead of onboarding a new
    learner. On missing artifact, the underlying runner raises
    :exc:`NoArtifactError`, which the CLI layer turns into a yellow
    "nothing to resume" message and a non-zero exit code.
    """
    resolved_io: ChatIO = io or _RichChatIO()
    try:
        asyncio.run(_run_async_resume(learner_id, resolved_io, state))
    except KeyboardInterrupt:
        resolved_io.say(
            "\n> Pausing session...\n"
            "  ✓ Checkpoint saved. Run `clawstu resume` to pick this "
            "back up.",
            border_style="yellow",
        )
        raise SystemExit(0) from None


async def _run_async_resume(
    learner_id: str,
    io: ChatIO,
    state: AppState | None,
) -> None:
    """Async body of :func:`run_resume_session`.

    ``warm_start`` is synchronous (no LLM call on the warm path) so
    only the shared ``_run_teach_loop`` needs async scaffolding.
    """
    io.say(OPENING_BANNER, panel_title="Stuart", border_style="blue")
    ctx = _build_chat_context(state)

    persistence = ctx.state.persistence
    profile, session = ctx.runner.warm_start(
        learner_id=learner_id,
        learners=persistence.learners,
        artifacts=persistence.artifacts,
        zpd=persistence.zpd,
        modality_outcomes=persistence.modality_outcomes,
        misconceptions=persistence.misconceptions,
        events=persistence.events,
    )
    bundle = SessionBundle(profile=profile, session=session)
    ctx.state.put(bundle)

    io.say("> Resuming session...")
    if session.primed_block is not None:
        io.say(
            f"  ✓ Topic: {session.topic or session.domain.value}\n"
            f"  ✓ Age bracket: {profile.age_bracket.value}\n"
            f"  ✓ Picking up at: {session.primed_block.concept}\n"
            f"  ✓ Provider: {_format_provider_label(ctx.router)}"
        )

    _run_teach_loop(io, ctx, profile, session)
    ctx.runner.close(profile, session)
    ctx.state.drop(session.id)
    _render_session_summary(io, profile, session)


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _resolve_learner_id(inputs: ChatInputs, io: ChatIO) -> str:
    if inputs.learner_id is not None:
        return inputs.learner_id
    return io.ask_text("What's your name?")


def _resolve_age(inputs: ChatInputs, io: ChatIO) -> int:
    if inputs.age is not None:
        return inputs.age
    return io.ask_int("How old are you?")


def _resolve_topic(inputs: ChatInputs, io: ChatIO) -> str:
    if inputs.topic is not None:
        return inputs.topic
    io.say(
        "What would you like to learn about today?\n"
        "  Try: the Haitian Revolution, photosynthesis, supply and "
        "demand,\n       the Fibonacci sequence, Shakespeare's sonnets"
    )
    # The prompt glyph is a deliberate UX choice lifted from the
    # Part 2A spec; ruff's ambiguous-character lint (RUF001) would
    # otherwise complain that it looks like a greater-than sign.
    return io.ask_text("›")  # noqa: RUF001


# ---------------------------------------------------------------------------
# Teach / calibration loops
# ---------------------------------------------------------------------------


def _run_calibration_loop(
    io: ChatIO,
    ctx: _ChatContext,
    profile: LearnerProfile,
    session: Session,
) -> None:
    """Run the seed-library calibration phase if the runner asked for it.

    Only fires when ``session.phase is CALIBRATING``. For live-topic
    sessions (the default path via ``onboard_with_topic``) the runner
    hands back a TEACHING session and this helper is never called.
    """
    io.say(
        "\n> Calibrating...\n"
        "I'll ask 3 quick questions to figure out where to start.\n"
        "No grades. No scores. Just so I don't bore you or lose you."
    )
    items = ctx.runner.calibration_items(session, size=3)
    for i, item in enumerate(items, start=1):
        io.say(f"\nQ{i}/{len(items)}. {item.prompt}")
        answer = io.ask_text("  ›")  # noqa: RUF001 — UX prompt glyph
        result = ctx.evaluator.evaluate(item, answer)
        ctx.runner.record_calibration_answer(
            profile, session, item, result,
        )
        ctx.state.checkpoint(session.id)
    ctx.runner.finish_calibration(profile, session)
    ctx.state.checkpoint(session.id)


def _run_teach_loop(
    io: ChatIO,
    ctx: _ChatContext,
    profile: LearnerProfile,
    session: Session,
) -> None:
    """Drive teach→check cycles until the runner signals done or pause.

    Every loop iteration ends with an ``AppState.checkpoint`` so a
    process kill mid-teach leaves durable state behind for
    ``clawstu resume``.
    """
    while True:
        directive = ctx.runner.next_directive(profile, session)
        if directive.phase in (SessionPhase.CLOSING, SessionPhase.CLOSED):
            break
        if directive.phase is SessionPhase.CRISIS_PAUSE:
            io.say(
                directive.message or "Session paused for safety.",
                panel_title="Paused",
                border_style="red",
            )
            break
        if directive.block is not None:
            _render_block(io, directive.block)
            io.ask_text(
                "Press enter when you're ready for the check",
                default="",
            )
        # After presenting the block the runner moves the session
        # into CHECKING; the check item is selected via select_check
        # rather than returned on the directive.
        if session.phase is SessionPhase.CHECKING:
            check_item = ctx.runner.select_check(session)
            _render_check(io, check_item)
            answer = io.ask_text("  ›")  # noqa: RUF001 — UX prompt glyph
            result = ctx.evaluator.evaluate(check_item, answer)
            outcome = ctx.runner.record_check(
                profile, session, check_item, result,
            )
            _render_feedback(io, outcome)
        ctx.state.checkpoint(session.id)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _render_block(io: ChatIO, block: LearningBlock) -> None:
    header = (
        f"> Block · {block.modality.value} · "
        f"~{block.estimated_minutes} min · {block.tier.value}"
    )
    io.say(header)
    io.say(
        block.body,
        panel_title=block.title,
        border_style="blue",
        markdown=True,
    )


def _render_check(io: ChatIO, item: AssessmentItem) -> None:
    io.say("\n> Check")
    io.say(item.prompt)


def _render_feedback(io: ChatIO, outcome: TeachBlockResult) -> None:
    evaluation = outcome.evaluation
    if evaluation.correct and not outcome.reteach:
        io.say("  ✓ Correct. Moving to the next block.")
        return
    if outcome.reteach:
        feedback = (
            evaluation.notes
            or "Let me reteach this in a different modality."
        )
        io.say(f"  ✗ {feedback}")
        return
    # Partial credit without a reteach -- rare, but the evaluator can
    # produce it for a CRQ that hit some rubric points.
    io.say(
        f"  ~ Partially correct (score {evaluation.score:.0%}). "
        "Moving on."
    )


def _render_session_summary(
    io: ChatIO, profile: LearnerProfile, session: Session,
) -> None:
    """Print the closing summary screen.

    Pulls duration, modality mix, and the session-domain ZPD estimate
    from the profile + session. The "what's next" suggestions
    reference ``clawstu resume``, ``clawstu progress``, and
    ``clawstu wiki`` -- progress and wiki land in Part 2B, but
    advertising them now gives the student a through-line.
    """
    duration_minutes = max(
        1,
        int(
            (datetime.now(UTC) - session.started_at).total_seconds() // 60
        ),
    )
    summary_lines: list[str] = [
        f"You spent {duration_minutes} minutes on "
        f"{session.topic or session.domain.value}.",
    ]
    if profile.modality_outcomes:
        parts: list[str] = []
        for modality, outcome in profile.modality_outcomes.items():
            if outcome.attempts > 0:
                parts.append(f"{modality.value} ({outcome.attempts})")
        if parts:
            summary_lines.append(f"Modality mix: {', '.join(parts)}.")
    if session.domain in profile.zpd_by_domain:
        zpd = profile.zpd_by_domain[session.domain]
        summary_lines.append(
            f"ZPD estimate: {session.domain.value} = {zpd.tier.value} "
            f"(confidence {zpd.confidence:.2f})."
        )
    io.say(
        "\n".join(summary_lines),
        panel_title="Session closed",
        border_style="green",
    )
    io.say(
        "\nWhat's next:\n"
        "  • `clawstu resume` to pick this session back up later\n"
        "  • `clawstu progress` to see your learner dashboard\n"
        "  • `clawstu wiki <concept>` to get Stuart's notes on a concept"
    )


__all__ = [
    "OPENING_BANNER",
    "ChatIO",
    "ChatInputs",
    "NoArtifactError",
    "run_chat_session",
    "run_resume_session",
]
