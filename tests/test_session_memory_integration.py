"""Session close → memory writer end-to-end integration.

Phase 5 wires `write_session_to_memory` into the `/sessions/{id}/close`
API handler. When the app state is constructed with a `BrainStore`,
closing a session mints the post-session brain pages and emits KG
triples; without a brain store the handler is a no-op (so the 301
pre-Phase-5 tests keep working with `AppState()` defaults).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state
from clawstu.memory.knowledge_graph import find_by_subject
from clawstu.memory.pages import LearnerPage, PageKind, SessionPage
from clawstu.memory.store import BrainStore


@pytest.fixture()
def brain_client(tmp_path: Path) -> Iterator[tuple[TestClient, AppState, BrainStore]]:
    brain = BrainStore(tmp_path / "brain")
    state = AppState(brain_store=brain)
    app = create_app()
    app.dependency_overrides[get_state] = lambda: state
    with TestClient(app) as tc:
        yield tc, state, brain


def _onboard_and_close(
    client: TestClient, learner_id: str = "mem-learner"
) -> str:
    onboard = client.post(
        "/sessions",
        json={
            "learner_id": learner_id,
            "age": 15,
            "domain": "us_history",
        },
    )
    assert onboard.status_code == 201, onboard.text
    session_id = str(onboard.json()["session_id"])

    # Drive the session through a minimal happy path so a SessionPage
    # can be minted with a non-empty pathway + blocks_presented count.
    client.post(f"/sessions/{session_id}/finish-calibration")
    client.post(f"/sessions/{session_id}/next")

    close = client.post(f"/sessions/{session_id}/close")
    assert close.status_code == 200, close.text
    return session_id


class TestSessionCloseWritesBrainPages:
    def test_close_mints_session_and_learner_pages(
        self,
        brain_client: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, _state, brain = brain_client
        session_id = _onboard_and_close(client, learner_id="mem-learner-01")

        # SessionPage exists for the closed session.
        session_page = brain.get(PageKind.SESSION, session_id, "mem-learner-01")
        assert isinstance(session_page, SessionPage)
        assert session_page.session_id == session_id
        assert session_page.learner_id == "mem-learner-01"
        # The session-close summary landed in the compiled truth.
        assert "Session" in session_page.compiled_truth

        # LearnerPage gained a timeline entry.
        learner_page = brain.get(
            PageKind.LEARNER, "mem-learner-01", "mem-learner-01"
        )
        assert isinstance(learner_page, LearnerPage)
        assert len(learner_page.timeline) >= 1
        assert any(
            session_id[:8] in entry.text for entry in learner_page.timeline
        )

        # KG triples emitted for at least one concept touched.
        session_triples = find_by_subject(
            brain_client[1].persistence.kg, session_id
        )
        assert any(t.predicate == "includes" for t in session_triples)

    def test_close_without_brain_store_is_a_noop(
        self, tmp_path: Path
    ) -> None:
        """Default `AppState()` (no brain store) closes cleanly without
        attempting to mint pages. This is the invariant the 301
        pre-Phase-5 tests rely on."""
        state = AppState()  # no brain_store=...
        app = create_app()
        app.dependency_overrides[get_state] = lambda: state
        with TestClient(app) as client:
            onboard = client.post(
                "/sessions",
                json={
                    "learner_id": "noop-learner",
                    "age": 15,
                    "domain": "us_history",
                },
            )
            assert onboard.status_code == 201
            session_id = onboard.json()["session_id"]
            close = client.post(f"/sessions/{session_id}/close")
            assert close.status_code == 200
            # No attribute errors, no exceptions.
            assert state.brain_store is None
