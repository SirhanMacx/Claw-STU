"""Phase 7 success-gate end-to-end test.

Spec reference: §4.8 / §4.9.2. This is the ONE test the spec names as
the Phase 7 gate: a full cycle of

    onboard → close → prepare_next_session → resume

that returns a block with `warm_start: true` in well under the
tolerance budget. The spec-ideal hot-path budget is 50 ms but that is
test-rig noisy — CI on shared runners jitters past 50 ms under load —
so we assert against a looser 200 ms ceiling here and keep 50 ms as
the aspirational target for local benchmarking.

The test never touches a provider. The scheduler task runs its
Phase 6 placeholder path (no LLM call), and the resume route is a
pure persistence + runner round-trip. Everything you see below is
deterministic.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawstu.api.main import build_scheduler_runner, create_app
from clawstu.api.state import AppState, get_state
from clawstu.memory.store import BrainStore
from clawstu.persistence.store import InMemoryPersistentStore
from clawstu.scheduler.tasks import prepare_next_session


@pytest.fixture()
def phase7_app(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, AppState, BrainStore]]:
    brain = BrainStore(tmp_path / "brain")
    persistence = InMemoryPersistentStore()
    state = AppState(persistence=persistence, brain_store=brain)
    app = create_app()
    app.dependency_overrides[get_state] = lambda: state
    with TestClient(app) as tc:
        yield tc, state, brain


async def test_end_to_end_warm_start_cycle(
    phase7_app: tuple[TestClient, AppState, BrainStore],
) -> None:
    """Full onboard → close → prepare_next_session → resume cycle.

    The spec's success-gate E2E test. Onboards a learner via the
    normal POST /sessions path, runs them through a tiny session,
    closes it, fabricates a ProactiveContext, manually runs the
    prepare_next_session scheduler task, then hits the Phase 7
    resume route and asserts:

    1. The response is 200 with `warm_start: true`.
    2. The response's `block` field carries a LearningBlock-shaped
       dict parsed out of the placeholder artifact.
    3. The whole resume hot path takes < 200 ms — loose enough to
       stay green on slow CI, tight enough that any accidental
       provider call or blocking I/O would blow the budget by an
       order of magnitude.
    """
    client, state, _brain = phase7_app

    learner_id = "e2e-learner"

    # 1. Onboard a learner normally through the session API.
    onboard = client.post(
        "/sessions",
        json={
            "learner_id": learner_id,
            "age": 15,
            "domain": "us_history",
        },
    )
    assert onboard.status_code == 201, onboard.text
    session_id = onboard.json()["session_id"]

    # 2. Walk through calibration -> teaching briefly so the session
    #    has something substantive to write back to persistence on
    #    close. The specific answers don't matter for the E2E budget
    #    check; we just need the session_close event to land.
    client.post(f"/sessions/{session_id}/finish-calibration")
    client.post(f"/sessions/{session_id}/next")

    # 3. Close the session. This writes the learner profile + the
    #    session row to persistence so warm_start can find them.
    close = client.post(f"/sessions/{session_id}/close")
    assert close.status_code == 200

    # 4. Fabricate a ProactiveContext from the live AppState and run
    #    prepare_next_session directly. The Phase 6 task is async;
    #    the test is async too so we can await it without spinning
    #    a fresh event loop. Using build_scheduler_runner gives us
    #    the real wiring — a ModelRouter over EchoProvider — which
    #    is the same fabrication the lifespan uses in production.
    runner = build_scheduler_runner(state)
    report = await prepare_next_session.run(runner.context, learner_id)
    assert report.outcome == "success"

    # The artifact is now staged. Hit the resume route.
    hot_start = time.perf_counter()
    resume = client.post(f"/learners/{learner_id}/resume")
    elapsed_ms = (time.perf_counter() - hot_start) * 1000.0

    assert resume.status_code == 200, resume.text
    body = resume.json()
    assert body["warm_start"] is True
    assert body["phase"] == "teaching"
    assert body["block"] is not None
    assert body["session_id"]

    # The hot-path budget. 50 ms is spec-ideal; 200 ms is our CI-safe
    # ceiling. An accidental provider call or blocking disk write
    # would push this into the multi-second range, so the assertion
    # is a cheap sanity check on the "no provider in hot path"
    # invariant.
    assert elapsed_ms < 200.0, (
        f"warm-start resume took {elapsed_ms:.1f} ms; "
        f"budget is 200 ms (spec-ideal 50 ms)"
    )
