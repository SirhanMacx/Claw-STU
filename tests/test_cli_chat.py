"""Tests for the ``clawstu learn`` conversational chat loop.

The chat loop is exercised through a small :class:`_FakeChatIO` shim
that replaces stdin/stdout. Session machinery runs against an
:class:`InMemoryPersistentStore`-backed :class:`AppState`, so nothing
touches the filesystem; providers default to the ``EchoProvider``
stub when no API keys are set in env.

Many of these tests monkey-patch ``_offline_pathway`` so the
``LiveContentGenerator``'s offline stub returns a single concept.
The default stub returns three concepts, which would drive the teach
loop into a second iteration that needs seed-library content the
offline domains (``OTHER``, ``GLOBAL_HISTORY``) do not have. One
concept is enough to exercise every branch the chat loop cares
about (block render, check render, feedback, close).
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from clawstu import cli_chat
from clawstu.api.state import AppState
from clawstu.cli_chat import (
    ChatInputs,
    _format_provider_label,
    _render_session_summary,
    run_chat_session,
    run_resume_session,
)
from clawstu.engagement.session import NoArtifactError, Session, SessionPhase
from clawstu.orchestrator.live_content import LiveContentGenerator
from clawstu.orchestrator.router import ModelRouter
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    LearnerProfile,
    Modality,
    ZPDEstimate,
)

# A check answer long enough to clear the CRQ min-length threshold
# (40 chars) and rubric-matching enough to earn a "correct" result
# from the deterministic rubric-keyword evaluator. The offline
# check stub uses the rubric points ``explains the concept in the
# student's own words`` and ``includes at least one specific
# example``; any answer that mentions ``example`` / ``concept`` and
# clears 40 characters will score >= 0.5 and count as correct.
_PASSING_ANSWER = (
    "The concept is that sunlight is converted to chemical energy; "
    "one example is photosynthesis happening inside chloroplasts."
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeChatIO:
    """A scripted :class:`ChatIO` that returns canned answers in order.

    ``text_answers`` is the queue of strings the loop would have read
    from stdin. ``int_answers`` is the queue of integer answers for
    age prompts. ``confirms`` holds yes/no answers. Every emitted
    message lands in ``messages`` for later assertion; each entry is a
    tuple of ``(text, panel_title, border_style, markdown)``.

    Mismatched script lengths surface as ``AssertionError`` rather
    than a silent default, which is exactly what a test wants — a
    script that is too short means the chat loop asked an
    unanticipated question.

    ``raise_on_text`` is a one-shot knob: set it to the index at which
    ``ask_text`` should raise ``KeyboardInterrupt`` instead of
    returning the scripted answer. The Ctrl-C test uses this to drive
    the checkpoint-on-interrupt path deterministically.
    """

    text_answers: list[str] = field(default_factory=list)
    int_answers: list[int] = field(default_factory=list)
    confirms: list[bool] = field(default_factory=list)
    messages: list[tuple[str, str | None, str | None, bool]] = field(
        default_factory=list,
    )
    raise_on_text: int | None = None
    _text_idx: int = 0
    _int_idx: int = 0
    _confirm_idx: int = 0

    def ask_text(self, prompt: str, *, default: str | None = None) -> str:
        idx = self._text_idx
        if self.raise_on_text is not None and idx == self.raise_on_text:
            # Don't advance the counter — re-raising KeyboardInterrupt
            # here simulates the operator hitting Ctrl-C at exactly
            # this prompt. The chat loop's outer wrapper should
            # translate this into a clean checkpoint + exit.
            raise KeyboardInterrupt
        if idx >= len(self.text_answers):
            if default is not None:
                # Mirror Rich's Prompt behavior: a default means an
                # empty string is acceptable and the default wins.
                return default
            raise AssertionError(
                f"FakeChatIO ran out of scripted text answers; "
                f"loop asked: {prompt!r}"
            )
        value = self.text_answers[idx]
        self._text_idx += 1
        return value

    def ask_int(self, prompt: str, *, default: int | None = None) -> int:
        if self._int_idx >= len(self.int_answers):
            if default is not None:
                return default
            raise AssertionError(
                f"FakeChatIO ran out of scripted int answers; "
                f"loop asked: {prompt!r}"
            )
        value = self.int_answers[self._int_idx]
        self._int_idx += 1
        return value

    def say(
        self,
        message: str,
        *,
        panel_title: str | None = None,
        border_style: str | None = None,
        markdown: bool = False,
    ) -> None:
        self.messages.append((message, panel_title, border_style, markdown))

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        if self._confirm_idx >= len(self.confirms):
            raise AssertionError(
                f"FakeChatIO ran out of scripted confirms; "
                f"loop asked: {prompt!r}"
            )
        value = self.confirms[self._confirm_idx]
        self._confirm_idx += 1
        return value

    def transcript(self) -> str:
        """Return every emitted message joined for cheap substring checks."""
        return "\n".join(text for text, *_ in self.messages)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[Path]:
    """Pin ``CLAW_STU_DATA_DIR`` to a fresh tmp dir for each test.

    Also clears every provider env var so ambient developer
    credentials cannot leak into the chat loop's ``load_config``.

    Crucially, this fixture also force-stubs ``build_providers`` to
    return an echo-only dict. Without that stub the chat loop would
    resolve non-echo tasks to the local Ollama daemon (which IS
    reachable on this test host, but ships without the GLM model the
    default router picks), and every live-content generation call
    would raise ``LiveGenerationError``. The chat loop is a
    presentation layer; pinning the providers dict is the right
    boundary.
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

    from clawstu.orchestrator.config import AppConfig
    from clawstu.orchestrator.providers import EchoProvider, LLMProvider

    def _echo_only(_cfg: AppConfig) -> dict[str, LLMProvider]:
        return {"echo": EchoProvider()}

    monkeypatch.setattr(
        "clawstu.cli_chat.build_providers", _echo_only,
    )
    yield tmp_path


@pytest.fixture
def single_concept_pathway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``_offline_pathway`` return a single-concept pathway.

    The default offline stub returns three concepts, but the seed-
    library content selector only has US_HISTORY blocks, so second
    and third iterations of the teach loop raise ``RuntimeError``
    when the live-topic path falls through on non-US-History
    domains. A one-concept pathway closes cleanly after a single
    teach → check cycle.
    """
    from clawstu.curriculum.topic import Topic  # local to satisfy layering

    def _one(_topic: Topic) -> list[str]:
        return ["single_concept"]

    monkeypatch.setattr(
        "clawstu.orchestrator.live_content._offline_pathway", _one,
    )


@pytest.fixture
def in_memory_state() -> AppState:
    """Return an :class:`AppState` backed by an in-memory store.

    Tests use this instead of the default state so bundle writes
    stay in memory and assertions can inspect the persistence store
    after the chat loop completes.
    """
    return AppState(persistence=InMemoryPersistentStore(), cache_size=4)


# ---------------------------------------------------------------------------
# Happy path + provider warning + seeded inputs
# ---------------------------------------------------------------------------


def test_run_chat_session_full_flow_with_fake_io(
    isolated_data_dir: Path,
    in_memory_state: AppState,
    single_concept_pathway: None,
) -> None:
    """End-to-end happy path: seeded inputs, one teach/check cycle, close."""
    io = _FakeChatIO(
        text_answers=[
            "",               # press-enter before the check
            _PASSING_ANSWER,  # check answer (rubric-matching)
        ],
    )
    inputs = ChatInputs(
        learner_id="ada",
        age=15,
        topic="Photosynthesis",
        domain=Domain.SCIENCE,
    )
    run_chat_session(inputs=inputs, io=io, state=in_memory_state)

    transcript = io.transcript()
    # Banner ran once.
    assert "I'm Stuart" in transcript
    # The setup summary block mentions the topic + age bracket + domain.
    assert "Photosynthesis" in transcript
    assert AgeBracket.EARLY_HIGH.value in transcript
    assert Domain.SCIENCE.value in transcript
    # The session-close summary ran.
    assert any(
        panel_title == "Session closed" for _, panel_title, *_ in io.messages
    )


def test_run_chat_session_echo_mode_shows_warning(
    isolated_data_dir: Path,
    in_memory_state: AppState,
    single_concept_pathway: None,
) -> None:
    """With no API keys configured, the offline warning is emitted."""
    io = _FakeChatIO(
        text_answers=[
            "",
            _PASSING_ANSWER,
        ],
    )
    inputs = ChatInputs(
        learner_id="ada", age=15, topic="Mitosis", domain=Domain.SCIENCE,
    )
    run_chat_session(inputs=inputs, io=io, state=in_memory_state)

    assert "offline demo mode" in io.transcript()


def test_run_chat_session_real_provider_does_not_show_warning(
    monkeypatch: pytest.MonkeyPatch,
    isolated_data_dir: Path,
    in_memory_state: AppState,
    single_concept_pathway: None,
) -> None:
    """When a real provider is present, the offline warning does NOT fire.

    We re-stub ``build_providers`` to return an echo + anthropic pair;
    the chat loop's ``_real_providers`` helper sees anthropic and
    suppresses the offline warning. We still only call echo
    operationally -- the router falls back to echo for every task --
    because the fake anthropic entry is an EchoProvider under the
    hood.
    """
    from clawstu.orchestrator.config import AppConfig
    from clawstu.orchestrator.providers import EchoProvider, LLMProvider

    def _echo_plus_anthropic(_cfg: AppConfig) -> dict[str, LLMProvider]:
        return {"echo": EchoProvider(), "anthropic": EchoProvider()}

    monkeypatch.setattr(
        "clawstu.cli_chat.build_providers", _echo_plus_anthropic,
    )

    io = _FakeChatIO(
        text_answers=[
            "",
            _PASSING_ANSWER,
        ],
    )
    inputs = ChatInputs(
        learner_id="ada", age=15, topic="Mitosis", domain=Domain.SCIENCE,
    )
    run_chat_session(inputs=inputs, io=io, state=in_memory_state)

    assert "offline demo mode" not in io.transcript()


def test_run_chat_session_seeded_inputs_skip_prompts(
    isolated_data_dir: Path,
    in_memory_state: AppState,
    single_concept_pathway: None,
) -> None:
    """All four inputs seeded -> no name / age / topic prompts issued.

    The loop still asks for the press-enter and check answer, so the
    text queue needs exactly two entries. If the loop also asked for a
    name, the queue would run out and raise.
    """
    io = _FakeChatIO(text_answers=["", _PASSING_ANSWER])
    inputs = ChatInputs(
        learner_id="ada",
        age=15,
        topic="Supply and demand",
        domain=Domain.OTHER,
    )
    run_chat_session(inputs=inputs, io=io, state=in_memory_state)
    # Text prompts consumed: press-enter + check answer = 2.
    assert io._text_idx == 2
    # Int prompts: none, because age was seeded.
    assert io._int_idx == 0


def test_run_chat_session_prompts_for_missing_inputs(
    isolated_data_dir: Path,
    in_memory_state: AppState,
    single_concept_pathway: None,
) -> None:
    """When inputs are None, the loop prompts for name / age / topic."""
    io = _FakeChatIO(
        text_answers=[
            "ada",                     # name
            "The Fibonacci sequence",  # topic
            "",                        # press-enter before check
            _PASSING_ANSWER,           # check answer (rubric-matching)
        ],
        int_answers=[15],              # age
    )
    run_chat_session(inputs=None, io=io, state=in_memory_state)
    assert io._text_idx == 4
    assert io._int_idx == 1


# ---------------------------------------------------------------------------
# Ctrl-C + crisis handling
# ---------------------------------------------------------------------------


def test_run_chat_session_ctrl_c_during_teach_checkpoints_and_exits(
    isolated_data_dir: Path,
    in_memory_state: AppState,
    single_concept_pathway: None,
) -> None:
    """A KeyboardInterrupt mid-loop triggers the pause / checkpoint path.

    The fake IO raises KeyboardInterrupt at the "press enter for the
    check" prompt (index 0). The outer run_chat_session wrapper must
    translate that into a SystemExit(0) and a yellow pause message.
    """
    io = _FakeChatIO(text_answers=["should not be read"], raise_on_text=0)
    inputs = ChatInputs(
        learner_id="ada",
        age=15,
        topic="Photosynthesis",
        domain=Domain.SCIENCE,
    )
    with pytest.raises(SystemExit) as excinfo:
        run_chat_session(inputs=inputs, io=io, state=in_memory_state)

    assert excinfo.value.code == 0
    assert "Pausing session" in io.transcript()

    # AppState.put was called with the bundle BEFORE the interrupt,
    # so persistence holds the session -- that's the contract for
    # `clawstu resume` to find something to rehydrate. The bundle
    # may have been evicted, so check persistence directly.
    stored = in_memory_state.persistence.sessions.list_all()
    assert len(stored) == 1, (
        f"expected 1 persisted session, got {len(stored)}"
    )


def test_run_chat_session_crisis_during_check_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    isolated_data_dir: Path,
    in_memory_state: AppState,
    single_concept_pathway: None,
) -> None:
    """A session flipped to CRISIS_PAUSE stops the teach loop gracefully.

    We patch ``SessionRunner.next_directive`` to return a CRISIS_PAUSE
    directive on the second call so the first block/check cycle runs
    and then the loop halts in a paused state. The chat loop should
    emit the red "paused" panel and exit without raising.
    """
    from clawstu.engagement.session import (
        SessionDirective,
        SessionRunner,
    )

    original = SessionRunner.next_directive
    call_count = {"n": 0}

    def _patched(
        self: SessionRunner,
        profile: LearnerProfile,
        session: Session,
    ) -> SessionDirective:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: return the normal block directive.
            return original(self, profile, session)
        # Flip the session to CRISIS_PAUSE so downstream checkpoints
        # and the runner's own guardrail match.
        session.phase = SessionPhase.CRISIS_PAUSE
        return SessionDirective(
            phase=SessionPhase.CRISIS_PAUSE,
            message="Session paused for safety. Reach out to an adult.",
        )

    monkeypatch.setattr(SessionRunner, "next_directive", _patched)

    io = _FakeChatIO(
        text_answers=[
            "",
            _PASSING_ANSWER,
        ],
    )
    inputs = ChatInputs(
        learner_id="ada",
        age=15,
        topic="Photosynthesis",
        domain=Domain.SCIENCE,
    )
    run_chat_session(inputs=inputs, io=io, state=in_memory_state)
    # The red Paused panel fired.
    assert any(
        panel_title == "Paused" and border_style == "red"
        for _, panel_title, border_style, _ in io.messages
    )


# ---------------------------------------------------------------------------
# Resume path
# ---------------------------------------------------------------------------


def _seed_artifact_for_resume(
    store: InMemoryPersistentStore, learner_id: str,
) -> None:
    """Plant a minimal artifact + profile for a resume test."""
    store.learners.upsert(
        LearnerProfile(learner_id=learner_id, age_bracket=AgeBracket.EARLY_HIGH)
    )
    store.artifacts.upsert(
        learner_id=learner_id,
        pathway_json='{"concepts": ["single_concept"]}',
        first_block_json=(
            '{"concept": "single_concept", '
            '"title": "Resume: single_concept", '
            '"body": "Resume-primed body. What do you already know?"}'
        ),
        first_check_json=(
            '{"concept": "single_concept", '
            '"prompt": "Explain single_concept in your own words.", '
            '"rubric": ["mentions the concept", "gives an example"]}'
        ),
    )


def test_run_resume_session_with_existing_artifact(
    isolated_data_dir: Path,
    single_concept_pathway: None,
) -> None:
    """Happy-path resume: primed block + check drive one cycle to close."""
    persistence = InMemoryPersistentStore()
    _seed_artifact_for_resume(persistence, "ada")
    state = AppState(persistence=persistence, cache_size=4)

    io = _FakeChatIO(
        text_answers=[
            "",
            _PASSING_ANSWER,
        ],
    )
    run_resume_session(learner_id="ada", io=io, state=state)

    transcript = io.transcript()
    assert "Resuming session" in transcript
    # Artifact is marked consumed after a successful warm-start.
    artifact = persistence.artifacts.get("ada")
    assert artifact is None or artifact.get("consumed_at") is not None


def test_run_resume_session_without_artifact_raises_no_artifact(
    isolated_data_dir: Path,
) -> None:
    """Resume without an artifact bubbles NoArtifactError to the caller."""
    state = AppState(persistence=InMemoryPersistentStore(), cache_size=4)
    io = _FakeChatIO()
    with pytest.raises(NoArtifactError):
        run_resume_session(learner_id="ghost", io=io, state=state)


# ---------------------------------------------------------------------------
# Unit tests on dataclass + rendering helpers
# ---------------------------------------------------------------------------


def test_chat_inputs_defaults_to_all_none() -> None:
    """ChatInputs() with no args has every field unset."""
    inputs = ChatInputs()
    assert inputs.learner_id is None
    assert inputs.age is None
    assert inputs.topic is None
    assert inputs.domain is None


def test_render_session_summary_mentions_topic_and_modality() -> None:
    """The closing summary includes duration, modality mix, and ZPD."""
    profile = LearnerProfile(
        learner_id="ada", age_bracket=AgeBracket.EARLY_HIGH,
    )
    # Seed a single modality outcome so the mix line renders.
    outcome = profile.outcome_for(Modality.SOCRATIC_DIALOGUE)
    outcome.record(correct=True, latency_seconds=10.0)
    # Seed a ZPD estimate on the session's domain so the ZPD line renders.
    profile.zpd_by_domain[Domain.SCIENCE] = ZPDEstimate(
        domain=Domain.SCIENCE, tier=ComplexityTier.MEETING,
        confidence=0.42, samples=1,
    )
    session = Session(
        learner_id="ada",
        domain=Domain.SCIENCE,
        topic="Photosynthesis",
    )
    io = _FakeChatIO()
    _render_session_summary(io, profile, session)
    transcript = io.transcript()
    assert "Photosynthesis" in transcript
    assert Modality.SOCRATIC_DIALOGUE.value in transcript
    assert "ZPD estimate" in transcript
    assert "0.42" in transcript


def test_format_provider_label_returns_lowercase_name(
    isolated_data_dir: Path,
) -> None:
    """The provider label is a lowercased ``name/model`` pair."""
    from clawstu.api.main import build_providers
    from clawstu.orchestrator.config import load_config

    cfg = load_config()
    providers = build_providers(cfg)
    router = ModelRouter(config=cfg, providers=providers)
    label = _format_provider_label(router)
    # Every provider class name ends with "Provider"; the label strips
    # that suffix and lowercases what remains.
    assert "/" in label
    name, _ = label.split("/", 1)
    assert name == name.lower()


def test_chat_module_reuses_build_providers_from_api_main() -> None:
    """cli_chat imports ``build_providers`` (not the old private one).

    The rename from ``_build_providers`` to ``build_providers`` is
    Phase 8 Part 2A; this test pins that the rename happened and that
    the chat module consumes the public name. ``getattr`` on the
    module object is deliberate so mypy does not demand an
    ``__all__`` entry for an internal helper.
    """
    import clawstu.api.main as api_main
    assert hasattr(api_main, "build_providers")
    module_fn = getattr(cli_chat, "build_providers", None)
    assert module_fn is api_main.build_providers


def test_live_content_generator_is_wired_in_chat_context(
    isolated_data_dir: Path,
) -> None:
    """``_build_chat_context`` constructs a LiveContentGenerator.

    Protects against future refactors dropping the live content wiring
    and accidentally reverting the chat loop to the seed-library
    ``onboard`` path. ``isolated_data_dir`` stubs ``build_providers``
    to return echo-only, so the exact contents of ``ctx.providers``
    reflect the stub, not the real production dict. What we care
    about is that (a) the live generator exists, (b) the router is
    constructed on top of the providers dict, and (c) echo is always
    present as the fallback floor.
    """
    ctx = cli_chat._build_chat_context()
    assert isinstance(ctx.live, LiveContentGenerator)
    assert ctx.router is not None
    # Echo is the guaranteed fallback floor; the router construction
    # would fail loudly without it, so the mere fact that _build_chat_context
    # returned means echo is present.
    assert "echo" in ctx.providers
