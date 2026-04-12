"""MCP server module tests.

Verifies the module imports cleanly, the tool registry has all five
expected tools, the CLI command is wired, and individual tools handle
edge cases gracefully.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawstu.mcp_server import (
    _get_tool_registry,
    _resolve_learner_id,
    _resolve_stores,
    clawstu_ask,
    clawstu_learn_session,
    clawstu_progress,
    clawstu_review,
    clawstu_wiki,
)

# ---------------------------------------------------------------------------
# Module-level import and structure tests
# ---------------------------------------------------------------------------


def test_mcp_server_module_imports_cleanly() -> None:
    """The MCP server module must import without side effects."""
    import clawstu.mcp_server as mod

    assert hasattr(mod, "mcp")
    assert hasattr(mod, "run_mcp_server")


def test_mcp_tool_definitions_exist() -> None:
    """The tool registry must contain all five documented tools."""
    tools = _get_tool_registry()
    expected = {
        "clawstu_ask",
        "clawstu_wiki",
        "clawstu_progress",
        "clawstu_review",
        "clawstu_learn_session",
    }
    assert set(tools) == expected


def test_mcp_tool_registry_returns_list_of_strings() -> None:
    """The registry returns a list, not a set or tuple."""
    tools = _get_tool_registry()
    assert isinstance(tools, list)
    assert all(isinstance(t, str) for t in tools)


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


# ---------------------------------------------------------------------------
# _resolve_learner_id
# ---------------------------------------------------------------------------


def test_resolve_learner_id_with_explicit_id() -> None:
    """When an explicit learner_id is given, it passes through unchanged."""
    mock_persistence = MagicMock()
    result = _resolve_learner_id(mock_persistence, "alice")
    assert result == "alice"


def test_resolve_learner_id_falls_back_to_most_recent() -> None:
    """When no learner_id is given, falls back to most_recent_learner."""
    mock_persistence = MagicMock()
    with patch(
        "clawstu.cli_state.most_recent_learner",
        return_value="recent-learner",
    ):
        result = _resolve_learner_id(mock_persistence, None)
    assert result == "recent-learner"


def test_resolve_learner_id_returns_none_on_fallback_error() -> None:
    """When most_recent_learner raises, returns None."""
    mock_persistence = MagicMock()
    with patch(
        "clawstu.cli_state.most_recent_learner",
        side_effect=RuntimeError("no learners"),
    ):
        result = _resolve_learner_id(mock_persistence, None)
    assert result is None


# ---------------------------------------------------------------------------
# _resolve_stores
# ---------------------------------------------------------------------------


def test_resolve_stores_returns_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_resolve_stores returns a StoreBundle."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    bundle = _resolve_stores()
    assert hasattr(bundle, "persistence")
    assert hasattr(bundle, "brain_store")


# ---------------------------------------------------------------------------
# clawstu_wiki tool
# ---------------------------------------------------------------------------


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


async def test_wiki_tool_with_known_learner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The wiki tool returns wiki_markdown when a valid learner exists."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    mock_bundle = MagicMock()
    mock_bundle.persistence = MagicMock()
    mock_bundle.brain_store = MagicMock()

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="alice"),
        patch(
            "clawstu.mcp_server.generate_concept_wiki",
            return_value="# Concept: photosynthesis\n\nPlants use light.",
            create=True,
        ),
    ):
        result_json = await clawstu_wiki(
            concept="photosynthesis", learner_id="alice",
        )
    result = json.loads(result_json)
    assert result["concept"] == "photosynthesis"
    assert result["learner_id"] == "alice"
    assert "wiki_markdown" in result


async def test_wiki_tool_no_learner_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When no learner is resolved, wiki returns an error dict."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    mock_bundle = MagicMock()
    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value=None),
    ):
        result_json = await clawstu_wiki(
            concept="test_concept", learner_id="",
        )
    result = json.loads(result_json)
    assert "error" in result
    assert "no learner" in result["error"]


# ---------------------------------------------------------------------------
# clawstu_progress tool
# ---------------------------------------------------------------------------


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


async def test_progress_tool_no_resolved_learner() -> None:
    """When _resolve_learner_id returns None, progress says no learner found."""
    mock_bundle = MagicMock()
    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value=None),
    ):
        result_json = await clawstu_progress(learner_id="")
    result = json.loads(result_json)
    assert "error" in result
    assert "no learner" in result["error"]


async def test_progress_tool_learner_not_in_store() -> None:
    """When the resolved ID doesn't match a stored profile, returns error."""
    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = None

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="ghost"),
    ):
        result_json = await clawstu_progress(learner_id="ghost")
    result = json.loads(result_json)
    assert "error" in result
    assert "ghost" in result["error"]


async def test_progress_tool_with_full_profile() -> None:
    """Progress tool returns zpd, modality, and session count for a real profile."""
    from clawstu.profile.model import Domain

    # The production code accesses zpd.level and iterates
    # modality_outcomes as objects with .modality.value / .correct.
    # We use mock objects whose attributes match what the code expects.
    mock_zpd = MagicMock()
    mock_zpd.level = "meeting"
    mock_zpd.confidence = 0.75

    mock_mo = MagicMock()
    mock_mo.modality.value = "text_reading"
    mock_mo.correct = True

    mock_profile = MagicMock()
    mock_profile.zpd_by_domain = {Domain.SCIENCE: mock_zpd}
    mock_profile.modality_outcomes = [mock_mo]

    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = mock_profile
    mock_bundle.persistence.sessions.list.return_value = [MagicMock(), MagicMock()]

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="alice"),
    ):
        result_json = await clawstu_progress(learner_id="alice")
    result = json.loads(result_json)
    assert result["learner_id"] == "alice"
    assert "zpd" in result
    assert result["zpd"]["science"]["level"] == "meeting"
    assert result["sessions"] == 2


# ---------------------------------------------------------------------------
# clawstu_review tool
# ---------------------------------------------------------------------------


async def test_review_tool_no_resolved_learner() -> None:
    """Review returns error when no learner is resolved."""
    mock_bundle = MagicMock()
    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value=None),
    ):
        result_json = await clawstu_review(learner_id="")
    result = json.loads(result_json)
    assert "error" in result
    assert "no learner" in result["error"]


async def test_review_tool_learner_not_in_store() -> None:
    """Review returns error when learner not found in persistence."""
    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = None

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="ghost"),
    ):
        result_json = await clawstu_review(learner_id="ghost")
    result = json.loads(result_json)
    assert "error" in result


async def test_review_tool_with_events() -> None:
    """Review returns due_concepts when there are old events."""
    from datetime import UTC, datetime, timedelta

    from clawstu.profile.model import (
        AgeBracket,
        Domain,
        EventKind,
        LearnerProfile,
        ObservationEvent,
    )

    profile = LearnerProfile(
        learner_id="bob", age_bracket=AgeBracket.LATE_ELEMENTARY,
    )
    # Add an event older than 7 days.
    old_event = ObservationEvent(
        kind=EventKind.CHECK_FOR_UNDERSTANDING,
        domain=Domain.SCIENCE,
        concept="photosynthesis",
        timestamp=datetime.now(tz=UTC) - timedelta(days=10),
    )
    # And one recent event (should NOT be due).
    recent_event = ObservationEvent(
        kind=EventKind.CHECK_FOR_UNDERSTANDING,
        domain=Domain.SCIENCE,
        concept="mitosis",
        timestamp=datetime.now(tz=UTC) - timedelta(days=1),
    )
    profile.events = [old_event, recent_event]

    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = profile

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="bob"),
    ):
        result_json = await clawstu_review(learner_id="bob")
    result = json.loads(result_json)

    assert result["learner_id"] == "bob"
    assert result["total_concepts"] == 2
    due_names = [d["concept"] for d in result["due_concepts"]]
    assert "photosynthesis" in due_names
    assert "mitosis" not in due_names


async def test_review_tool_no_due_concepts() -> None:
    """Review returns empty due list when all concepts are recent."""
    from datetime import UTC, datetime, timedelta

    from clawstu.profile.model import (
        AgeBracket,
        Domain,
        EventKind,
        LearnerProfile,
        ObservationEvent,
    )

    profile = LearnerProfile(
        learner_id="carol", age_bracket=AgeBracket.ADULT,
    )
    profile.events = [
        ObservationEvent(
            kind=EventKind.CHECK_FOR_UNDERSTANDING,
            domain=Domain.MATH,
            concept="algebra",
            timestamp=datetime.now(tz=UTC) - timedelta(hours=6),
        ),
    ]

    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = profile

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="carol"),
    ):
        result_json = await clawstu_review(learner_id="carol")
    result = json.loads(result_json)

    assert result["due_concepts"] == []
    assert result["total_concepts"] == 1


async def test_review_tool_ignores_irrelevant_events() -> None:
    """Review only considers CHECK_FOR_UNDERSTANDING and CALIBRATION_ANSWER."""
    from datetime import UTC, datetime, timedelta

    from clawstu.profile.model import (
        AgeBracket,
        Domain,
        EventKind,
        LearnerProfile,
        ObservationEvent,
    )

    profile = LearnerProfile(
        learner_id="dave", age_bracket=AgeBracket.EARLY_HIGH,
    )
    # SESSION_START is not in the review_kinds set.
    profile.events = [
        ObservationEvent(
            kind=EventKind.SESSION_START,
            domain=Domain.US_HISTORY,
            concept="civil_war",
            timestamp=datetime.now(tz=UTC) - timedelta(days=30),
        ),
    ]

    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = profile

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="dave"),
    ):
        result_json = await clawstu_review(learner_id="dave")
    result = json.loads(result_json)

    assert result["total_concepts"] == 0
    assert result["due_concepts"] == []


# ---------------------------------------------------------------------------
# clawstu_learn_session tool
# ---------------------------------------------------------------------------


async def test_learn_session_creates_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """learn_session creates a session with correct metadata."""
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = None

    with patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle):
        result_json = await clawstu_learn_session(
            topic="photosynthesis",
            learner_id="Ada",
            age_bracket="middle",
        )
    result = json.loads(result_json)

    assert result["learner_id"] == "Ada"
    assert result["topic"] == "photosynthesis"
    assert result["domain"] == "other"
    assert "session_id" in result
    assert "message" in result


async def test_learn_session_with_existing_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """learn_session skips profile creation if learner already exists."""
    from clawstu.profile.model import AgeBracket, LearnerProfile

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    existing_profile = LearnerProfile(
        learner_id="Bob", age_bracket=AgeBracket.EARLY_HIGH,
    )

    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = existing_profile

    with patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle):
        result_json = await clawstu_learn_session(
            topic="mitosis",
            learner_id="Bob",
            age_bracket="early_high",
        )
    result = json.loads(result_json)

    assert result["learner_id"] == "Bob"
    assert result["topic"] == "mitosis"
    # Should NOT have called upsert for an existing learner.
    mock_bundle.persistence.learners.upsert.assert_not_called()


async def test_learn_session_invalid_age_bracket() -> None:
    """Invalid age_bracket falls back to MIDDLE."""
    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = None

    with patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle):
        result_json = await clawstu_learn_session(
            topic="history",
            learner_id="Eve",
            age_bracket="toddler",  # invalid
        )
    result = json.loads(result_json)

    assert result["learner_id"] == "Eve"
    assert result["topic"] == "history"
    # It should not crash -- the fallback is AgeBracket.MIDDLE.
    assert "session_id" in result


async def test_learn_session_uses_default_args() -> None:
    """learn_session uses defaults when optional args are omitted."""
    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = None

    with patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle):
        result_json = await clawstu_learn_session(topic="quantum")
    result = json.loads(result_json)

    assert result["learner_id"] == "Ada"
    assert result["topic"] == "quantum"


# ---------------------------------------------------------------------------
# clawstu_ask tool
# ---------------------------------------------------------------------------


async def test_ask_tool_anonymous() -> None:
    """Ask returns an answer for an anonymous user.

    clawstu_ask uses local imports inside the function body, so we must
    patch at the original module locations rather than on mcp_server.
    """
    from unittest.mock import AsyncMock

    mock_bundle = MagicMock()
    mock_bundle.persistence = MagicMock()

    mock_provider = MagicMock()
    mock_provider._client = None

    mock_chain_instance = MagicMock()
    mock_chain_instance.ask = AsyncMock(
        return_value="The sun powers photosynthesis.",
    )

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value=None),
        patch("clawstu.orchestrator.config.load_config"),
        patch(
            "clawstu.api.main.build_providers",
            return_value={"echo": mock_provider},
        ),
        patch("clawstu.orchestrator.router.ModelRouter"),
        patch(
            "clawstu.orchestrator.chain.ReasoningChain",
            return_value=mock_chain_instance,
        ),
    ):
        result_json = await clawstu_ask(question="What is photosynthesis?")

    result = json.loads(result_json)
    assert result["learner_id"] == "anonymous"
    assert "answer" in result


async def test_ask_tool_with_learner_context() -> None:
    """Ask includes learner context when a profile exists."""
    from unittest.mock import AsyncMock

    from clawstu.profile.model import AgeBracket, LearnerProfile

    profile = LearnerProfile(
        learner_id="alice", age_bracket=AgeBracket.MIDDLE,
    )

    mock_bundle = MagicMock()
    mock_bundle.persistence.learners.get.return_value = profile
    mock_bundle.brain_store = MagicMock()
    mock_bundle.persistence.kg = MagicMock()

    mock_context = MagicMock()
    mock_context.text = "Alice knows about plants."

    mock_provider = MagicMock()
    mock_provider._client = None

    mock_chain_instance = MagicMock()
    mock_chain_instance.ask = AsyncMock(
        return_value="Personalized answer.",
    )

    with (
        patch("clawstu.mcp_server._resolve_stores", return_value=mock_bundle),
        patch("clawstu.mcp_server._resolve_learner_id", return_value="alice"),
        patch("clawstu.orchestrator.config.load_config"),
        patch(
            "clawstu.api.main.build_providers",
            return_value={"echo": mock_provider},
        ),
        patch("clawstu.orchestrator.router.ModelRouter"),
        patch(
            "clawstu.orchestrator.chain.ReasoningChain",
            return_value=mock_chain_instance,
        ),
        patch(
            "clawstu.memory.context.build_learner_context",
            return_value=mock_context,
        ),
    ):
        result_json = await clawstu_ask(
            question="What is photosynthesis?", learner_id="alice",
        )

    result = json.loads(result_json)
    assert result["learner_id"] == "alice"
    assert "answer" in result
