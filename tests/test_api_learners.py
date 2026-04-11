"""HTTP-level tests for the Phase 7 learner-facing routes.

Spec reference: §4.9.2. These tests spin up the real FastAPI app
with a fresh `AppState` wired to a tmp-path `BrainStore` and an
`InMemoryPersistentStore`, then exercise each route end-to-end.

Routes covered:

- `GET  /learners/{id}/wiki/{concept}` — returns markdown
- `POST /learners/{id}/resume` — 409 without artifact, 200 with
- `GET  /learners/{id}/queue` — counts + flags
- `POST /learners/{id}/capture` — writes SourcePage; 400 on crisis;
  401 when auth is required and missing
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state
from clawstu.memory.store import BrainStore
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.profile.model import (
    AgeBracket,
    ComplexityTier,
    Domain,
    EventKind,
    LearnerProfile,
    Modality,
    ObservationEvent,
)


@pytest.fixture
def wired(
    tmp_path: Path,
) -> tuple[TestClient, AppState, BrainStore]:
    """Return (client, state, brain) with both stores wired.

    A per-test AppState ensures no state leaks between tests. The
    BrainStore lives under tmp_path so the atomic-write machinery
    has a real directory to work against.
    """
    brain = BrainStore(tmp_path / "brain")
    persistence = InMemoryPersistentStore()
    state = AppState(persistence=persistence, brain_store=brain)
    app = create_app()
    app.dependency_overrides[get_state] = lambda: state
    return TestClient(app), state, brain


def _seed_learner(
    state: AppState,
    learner_id: str = "alice",
    age: AgeBracket = AgeBracket.EARLY_HIGH,
) -> LearnerProfile:
    profile = LearnerProfile(learner_id=learner_id, age_bracket=age)
    state.persistence.learners.upsert(profile)
    return profile


def _seed_artifact(
    state: AppState,
    learner_id: str = "alice",
) -> None:
    state.persistence.artifacts.upsert(
        learner_id=learner_id,
        pathway_json=json.dumps(
            {"concepts": ["declaration_of_independence_purpose"]}
        ),
        first_block_json=json.dumps(
            {
                "title": "A short reading",
                "body": "Read the preamble carefully.",
            }
        ),
        first_check_json=json.dumps(
            {
                "prompt": "Who was the audience?",
                "type": "crq",
                "rubric": ["names an audience"],
            }
        ),
    )


class TestWikiRoute:
    def test_wiki_returns_markdown(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, state, _brain = wired
        _seed_learner(state, "alice")
        response = client.get(
            "/learners/alice/wiki/declaration_of_independence_purpose"
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        body = response.text
        assert "Concept: declaration_of_independence_purpose" in body
        # Wiki should render even for a learner with no ConceptPage.
        assert "What Stuart knows about" in body

    def test_wiki_returns_503_without_brain_store(
        self,
    ) -> None:
        state = AppState()  # no brain_store
        app = create_app()
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)
        response = client.get("/learners/alice/wiki/anything")
        assert response.status_code == 503
        assert response.json()["detail"] == "brain store not configured"


class TestResumeRoute:
    def test_resume_without_artifact_returns_409(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, state, _brain = wired
        _seed_learner(state, "alice")
        response = client.post("/learners/alice/resume")
        assert response.status_code == 409
        body = response.json()
        assert "POST /sessions" in body["detail"]

    def test_resume_with_artifact_returns_teaching_block(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, state, _brain = wired
        _seed_learner(state, "alice")
        _seed_artifact(state, "alice")
        response = client.post("/learners/alice/resume")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["warm_start"] is True
        assert body["phase"] == "teaching"
        assert body["session_id"]
        # The block field should carry a LearningBlock-shaped dict.
        block = body["block"]
        assert block is not None
        assert block["title"] == "A short reading"
        assert "preamble" in block["body"].lower()
        # The session must be reachable via GET /sessions/{id} —
        # confirms resume wrote it to the cache.
        follow_up = client.get(f"/sessions/{body['session_id']}")
        assert follow_up.status_code == 200


class TestQueueRoute:
    def test_queue_returns_empty_buckets_for_fresh_learner(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, state, _brain = wired
        _seed_learner(state, "alice")
        response = client.get("/learners/alice/queue")
        assert response.status_code == 200
        body = response.json()
        assert body["learner_id"] == "alice"
        assert body["pending_reviews"] == 0
        assert body["pending_artifact"] is False
        assert body["flagged_gaps"] == []

    def test_queue_reflects_pending_artifact(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, state, _brain = wired
        _seed_learner(state, "alice")
        _seed_artifact(state, "alice")
        response = client.get("/learners/alice/queue")
        assert response.status_code == 200
        assert response.json()["pending_artifact"] is True

    def test_queue_counts_stale_concepts_as_pending_reviews(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        """A concept whose last check-event is > 7 days old counts as
        a pending review; a fresh one does not."""
        client, state, _brain = wired
        _seed_learner(state, "alice")
        stale = datetime.now(UTC) - timedelta(days=30)
        fresh = datetime.now(UTC) - timedelta(hours=1)
        for concept, ts in (
            ("stale_concept", stale),
            ("fresh_concept", fresh),
        ):
            state.persistence.events.append(
                ObservationEvent(
                    kind=EventKind.CHECK_FOR_UNDERSTANDING,
                    domain=Domain.US_HISTORY,
                    modality=Modality.TEXT_READING,
                    tier=ComplexityTier.MEETING,
                    correct=True,
                    concept=concept,
                    timestamp=ts,
                ),
                learner_id="alice",
                session_id=None,
            )
        response = client.get("/learners/alice/queue")
        assert response.status_code == 200
        assert response.json()["pending_reviews"] == 1


class TestCaptureRoute:
    def test_capture_writes_source_and_returns_id(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, state, _brain = wired
        _seed_learner(state, "alice")
        response = client.post(
            "/learners/alice/capture",
            json={
                "title": "Emancipation Proclamation excerpt",
                "text": (
                    "That on the first day of January, in the year of our "
                    "Lord one thousand eight hundred and sixty-three, all "
                    "persons held as slaves within any State shall be "
                    "thenceforward, and forever free."
                ),
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert "source_id" in body
        assert body["source_id"]

    def test_capture_rejects_crisis_text(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        client, state, _brain = wired
        _seed_learner(state, "alice")
        response = client.post(
            "/learners/alice/capture",
            json={
                "title": "Note",
                "text": "I want to kill myself tonight.",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "crisis_detected"

    def test_capture_returns_401_when_auth_required_and_missing(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With STU_LEARNER_AUTH_TOKEN set, the route must 401 on a
        missing bearer header."""
        monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "the-secret")
        client, state, _brain = wired
        _seed_learner(state, "alice")
        response = client.post(
            "/learners/alice/capture",
            json={"title": "Hello", "text": "harmless note"},
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "unauthorized"}

    def test_capture_returns_404_for_unknown_learner(
        self,
        wired: tuple[TestClient, AppState, BrainStore],
    ) -> None:
        """Unknown learner id → 404 with a clear detail string."""
        client, _state, _brain = wired
        response = client.post(
            "/learners/ghost/capture",
            json={"title": "Hello", "text": "harmless note"},
        )
        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_capture_returns_503_without_brain_store(
        self,
    ) -> None:
        """Capture requires a brain store; 503 if the app has none."""
        state = AppState()  # no brain store
        state.persistence.learners.upsert(
            LearnerProfile(
                learner_id="alice", age_bracket=AgeBracket.EARLY_HIGH
            )
        )
        app = create_app()
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)
        response = client.post(
            "/learners/alice/capture",
            json={"title": "Hello", "text": "note"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "brain store not configured"
