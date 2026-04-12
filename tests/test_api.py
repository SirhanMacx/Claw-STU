"""Smoke tests for the FastAPI app.

These are not exhaustive — the detailed behavior is tested in the
module-level tests. Here we prove the routes wire up, serialize the
right shapes, and honor the session phases at the HTTP boundary.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    # Replace the app state with a fresh instance so tests don't leak
    # sessions between each other.
    fresh_state = AppState()
    app.dependency_overrides[get_state] = lambda: fresh_state
    with TestClient(app) as tc:
        yield tc


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/admin/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["active_sessions"] == 0


def test_onboard_returns_calibration_items(client: TestClient) -> None:
    response = client.post(
        "/sessions",
        json={
            "learner_id": "test",
            "age": 15,
            "domain": "us_history",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["phase"] == "calibrating"
    assert len(body["calibration_items"]) >= 1


def test_profile_get_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/profile/nonexistent-session-id")
    assert response.status_code == 404


def test_profile_export_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/profile/nonexistent-session-id/export")
    assert response.status_code == 404


def test_profile_export_returns_attachment(client: TestClient) -> None:
    onboard = client.post(
        "/sessions",
        json={"learner_id": "export-test", "age": 15, "domain": "us_history"},
    )
    assert onboard.status_code == 201
    session_id = onboard.json()["session_id"]

    response = client.get(f"/profile/{session_id}/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "export-test" in response.headers["content-disposition"]


def test_profile_delete_is_idempotent(client: TestClient) -> None:
    onboard = client.post(
        "/sessions",
        json={"learner_id": "delete-test", "age": 15, "domain": "us_history"},
    )
    session_id = onboard.json()["session_id"]

    first = client.delete(f"/profile/{session_id}")
    assert first.status_code == 204
    second = client.delete(f"/profile/{session_id}")
    assert second.status_code == 204
