"""Functional tests for the Part 2B companion commands.

Every test seeds an :class:`InMemoryPersistentStore` and/or a
:class:`BrainStore` via ``monkeypatch`` so the command bodies under
test never touch the real ``~/.claw-stu`` directory. The Typer
``CliRunner`` captures stdout so we can assert on Rich-rendered
tables and panels without driving a real TTY.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawstu.cli import app
from clawstu.cli_state import (
    save_persistence_to_disk,
)
from clawstu.engagement.session import Session
from clawstu.memory.pages.concept import ConceptPage
from clawstu.memory.store import BrainStore
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ModalityOutcome,
    ObservationEvent,
    ZPDEstimate,
)

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _plain(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _make_profile(
    learner_id: str = "ada",
    bracket: AgeBracket = AgeBracket.MIDDLE,
) -> LearnerProfile:
    return LearnerProfile(learner_id=learner_id, age_bracket=bracket)


def _make_session(
    learner_id: str = "ada",
    *,
    domain: Domain = Domain.SCIENCE,
    topic: str = "photosynthesis",
    started_at: datetime | None = None,
) -> Session:
    return Session(
        learner_id=learner_id,
        domain=domain,
        topic=topic,
        started_at=started_at or datetime.now(UTC),
    )


def _seed_store(
    tmp_path: Path,
    store: InMemoryPersistentStore | None = None,
) -> InMemoryPersistentStore:
    """Seed a store with a single learner and a single session, then save."""
    if store is None:
        store = InMemoryPersistentStore()
    if store.learners.get("ada") is None:
        store.learners.upsert(_make_profile("ada"))
    if not store.sessions.list_for_learner("ada"):
        store.sessions.upsert(_make_session("ada"))
    save_persistence_to_disk(store, tmp_path / "state.json")
    return store


def _monkeypatch_stores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    store: InMemoryPersistentStore | None = None,
    brain_store: BrainStore | None = None,
) -> InMemoryPersistentStore:
    """Redirect CLAW_STU_DATA_DIR and optionally inject a pre-seeded store."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    st = _seed_store(tmp_path, store)
    return st


# ── wiki ──────────────────────────────────────────────────────────


def test_wiki_prints_markdown_for_existing_concept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Seed a ConceptPage in the BrainStore, run ``wiki``, assert rendered."""
    _monkeypatch_stores(monkeypatch, tmp_path)
    brain = BrainStore(base_dir=tmp_path / "brain")
    page = ConceptPage(
        learner_id="ada",
        concept_id="photosynthesis",
        compiled_truth="Plants convert light energy into chemical energy.",
    )
    brain.put(page, learner_id="ada")

    result = runner.invoke(
        app, ["wiki", "photosynthesis", "--learner", "ada"],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "photosynthesis" in stdout.lower()
    # The ConceptPage compiled truth should appear in the rendered
    # wiki markdown.
    assert "Plants convert light energy" in stdout


def test_wiki_friendly_error_for_unknown_concept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No brain page for the concept -- command prints a placeholder, not crash."""
    _monkeypatch_stores(monkeypatch, tmp_path)
    result = runner.invoke(
        app, ["wiki", "unknown_topic", "--learner", "ada"],
    )
    assert result.exit_code == 0, result.stdout
    # The wiki generator always returns markdown (with a placeholder
    # for missing pages), so exit code 0 + output is the contract.
    stdout = _plain(result.stdout)
    assert "unknown_topic" in stdout


def test_wiki_no_learners_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Empty persistence -- friendly 'no learners yet' message."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    # Do NOT seed the store -- no state.json at all.
    result = runner.invoke(app, ["wiki", "test_concept"])
    assert result.exit_code == 1
    stdout = _plain(result.stdout)
    assert "no learners yet" in stdout


# ── progress ──────────────────────────────────────────────────────


def test_progress_renders_zpd_and_modality_tables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Seed ZPD and modality data, assert the tables show expected values."""
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    store.sessions.upsert(_make_session("ada"))
    store.zpd.upsert_all(
        "ada",
        {
            Domain.SCIENCE: ZPDEstimate(
                domain=Domain.SCIENCE,
                tier=ComplexityTier.MEETING,
                confidence=0.72,
                samples=5,
            ),
        },
    )
    store.modality_outcomes.upsert_all(
        "ada",
        {
            Modality.TEXT_READING: ModalityOutcome(
                attempts=10, successes=7, total_latency_seconds=120.0,
            ),
        },
    )
    store.misconceptions.upsert_all("ada", {"chlorophyll_is_green": 3})
    _monkeypatch_stores(monkeypatch, tmp_path, store)

    result = runner.invoke(app, ["progress", "--learner", "ada"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "science" in stdout
    assert "meeting" in stdout
    assert "0.72" in stdout
    assert "text_reading" in stdout
    assert "70%" in stdout
    assert "chlorophyll_is_green" in stdout


def test_progress_empty_learner_shows_valid_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Fresh learner with no events still renders without crash."""
    _monkeypatch_stores(monkeypatch, tmp_path)
    result = runner.invoke(app, ["progress", "--learner", "ada"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    # The empty-state tables should render with "no data yet" markers
    # and the header should show the learner name.
    assert "ada" in stdout
    assert "no data yet" in stdout


def test_progress_most_recent_learner_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Omitting --learner auto-resolves to the most recently active one."""
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    store.learners.upsert(_make_profile("bob"))
    now = datetime.now(UTC)
    store.sessions.upsert(
        _make_session("ada", started_at=now - timedelta(hours=2)),
    )
    store.sessions.upsert(
        _make_session("bob", started_at=now - timedelta(hours=1)),
    )
    _monkeypatch_stores(monkeypatch, tmp_path, store)

    result = runner.invoke(app, ["progress"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "bob" in stdout


# ── history ───────────────────────────────────────────────────────


def test_history_lists_sessions_in_descending_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Sessions should appear newest-first in the table."""
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    now = datetime.now(UTC)
    store.sessions.upsert(
        _make_session("ada", topic="older", started_at=now - timedelta(hours=2)),
    )
    store.sessions.upsert(
        _make_session("ada", topic="newer", started_at=now - timedelta(hours=1)),
    )
    _monkeypatch_stores(monkeypatch, tmp_path, store)

    result = runner.invoke(app, ["history", "--learner", "ada"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    # "newer" should appear before "older" in the rendered output.
    newer_pos = stdout.find("newer")
    older_pos = stdout.find("older")
    assert newer_pos < older_pos, (
        f"'newer' ({newer_pos}) should appear before 'older' ({older_pos})"
    )


def test_history_respects_limit_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    now = datetime.now(UTC)
    for i in range(5):
        store.sessions.upsert(
            _make_session(
                "ada",
                topic=f"topic_{i}",
                started_at=now - timedelta(hours=i),
            ),
        )
    _monkeypatch_stores(monkeypatch, tmp_path, store)

    result = runner.invoke(
        app, ["history", "--learner", "ada", "--limit", "2"],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    # With --limit 2 only the two newest topics should appear.
    assert "topic_0" in stdout
    assert "topic_1" in stdout
    assert "topic_4" not in stdout


def test_history_no_sessions_shows_friendly_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Learner exists but has zero sessions -- friendly message."""
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    # Do not add sessions. Save only the learner.
    save_persistence_to_disk(store, tmp_path / "state.json")
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    result = runner.invoke(app, ["history", "--learner", "ada"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "No sessions yet" in stdout or "no sessions yet" in stdout.lower()


# ── review ────────────────────────────────────────────────────────


def test_review_identifies_concepts_older_than_7_days(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A concept whose last event is 10 days ago should appear in review."""
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("ada"))
    store.sessions.upsert(_make_session("ada"))

    ten_days_ago = datetime.now(UTC) - timedelta(days=10)
    event = ObservationEvent(
        kind=EventKind.CHECK_FOR_UNDERSTANDING,
        domain=Domain.SCIENCE,
        concept="photosynthesis",
        correct=True,
        timestamp=ten_days_ago,
    )
    store.events.append(event, learner_id="ada", session_id=None)
    _monkeypatch_stores(monkeypatch, tmp_path, store)

    result = runner.invoke(app, ["review", "--learner", "ada"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "photosynthesis" in stdout
    assert "10" in stdout  # days ago


def test_review_empty_returns_friendly_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No concepts due -- friendly 'nothing due yet' message."""
    _monkeypatch_stores(monkeypatch, tmp_path)
    result = runner.invoke(app, ["review", "--learner", "ada"])
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "nothing due yet" in stdout.lower()


# ── ask ───────────────────────────────────────────────────────────


def _force_echo_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Force the CLI to route everything through the EchoProvider.

    Writes a ``secrets.json`` that overrides ``primary_provider`` to
    ``echo`` AND rewrites the task routing table so every task uses the
    ``echo`` provider. Also clears ambient API keys so
    ``build_providers`` doesn't build any real provider besides echo +
    the always-present ollama stub.

    The Ollama provider is always constructed (it uses localhost and
    fails at ``.complete()`` time, not at construction time), so the
    only reliable way to keep it off the hot path is to route every
    task-kind primary to echo in the config.
    """
    monkeypatch.setenv("STU_PRIMARY_PROVIDER", "echo")
    for key in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "OPENROUTER_API_KEY", "OLLAMA_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    # Write a secrets.json that overrides the task routing table.
    import json as _json

    from clawstu.orchestrator.task_kinds import TaskKind

    echo_route = {"provider": "echo", "model": "echo-stub"}
    routing: dict[str, dict[str, str | int | float]] = {}
    for kind in TaskKind:
        routing[kind.value] = echo_route
    secrets = {"primary_provider": "echo", "task_routing": routing}
    (tmp_path / "secrets.json").write_text(
        _json.dumps(secrets), encoding="utf-8",
    )


def test_ask_with_echo_provider_returns_deterministic_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """In echo mode the response is a deterministic stub containing [echo]."""
    _monkeypatch_stores(monkeypatch, tmp_path)
    _force_echo_mode(monkeypatch, tmp_path)
    result = runner.invoke(
        app, ["ask", "What is photosynthesis?", "--learner", "ada"],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "[echo]" in stdout


def test_ask_shows_offline_warning_in_echo_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """When no real providers are configured, the offline warning appears."""
    _monkeypatch_stores(monkeypatch, tmp_path)
    _force_echo_mode(monkeypatch, tmp_path)
    result = runner.invoke(
        app, ["ask", "What is mitosis?", "--learner", "ada"],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "offline demo mode" in stdout or "clawstu setup" in stdout


def test_ask_passes_question_through_reasoning_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The question text appears in the echo response, confirming chain usage."""
    _monkeypatch_stores(monkeypatch, tmp_path)
    _force_echo_mode(monkeypatch, tmp_path)
    result = runner.invoke(
        app, ["ask", "Explain supply and demand", "--learner", "ada"],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    # The EchoProvider returns the prompt back verbatim, so the user's
    # question (or a prefix of it) should appear in the response.
    assert "supply" in stdout.lower() or "demand" in stdout.lower()


# ── profile export / import ───────────────────────────────────────


def test_export_creates_valid_tarball(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """``profile export`` produces a .tar.gz with the expected files."""
    import tarfile

    _monkeypatch_stores(monkeypatch, tmp_path)
    out = str(tmp_path / "ada.tar.gz")
    result = runner.invoke(
        app, ["profile", "export", "ada", "--out", out],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "Exported" in stdout

    # Verify tarball contents.
    assert Path(out).exists()
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert "profile.json" in names
    assert "meta.json" in names
    assert "sessions.jsonl" in names
    assert "events.jsonl" in names


def test_import_round_trips_a_learner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Export then import into a fresh persistence -- learner comes back."""
    # Phase 1: seed and export.
    store = InMemoryPersistentStore()
    store.learners.upsert(_make_profile("bob"))
    store.sessions.upsert(
        _make_session("bob", topic="mitosis"),
    )
    event = ObservationEvent(
        kind=EventKind.SESSION_START,
        domain=Domain.SCIENCE,
    )
    store.events.append(event, learner_id="bob", session_id=None)
    _monkeypatch_stores(monkeypatch, tmp_path, store)

    out = str(tmp_path / "bob.tar.gz")
    result = runner.invoke(
        app, ["profile", "export", "bob", "--out", out],
    )
    assert result.exit_code == 0, result.stdout

    # Phase 2: import into a fresh data dir.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(fresh))

    result = runner.invoke(
        app, ["profile", "import", out],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "bob" in stdout
    assert "1 sessions" in stdout or "1 session" in stdout

    # Phase 3: verify the imported learner is visible.
    result = runner.invoke(
        app, ["progress", "--learner", "bob"],
    )
    assert result.exit_code == 0, result.stdout
    stdout = _plain(result.stdout)
    assert "bob" in stdout
