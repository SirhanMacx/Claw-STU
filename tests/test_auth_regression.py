"""Regression tests: security hardening must stay in place.

These tests prove that protected routes REJECT unauthorized calls and
that the auth layer cannot be silently removed by a refactor. Every
test pins an expected HTTP status code for a specific auth scenario.

Environment:
- STU_AUTH_MODE=enforce + STU_LEARNER_AUTH_TOKEN=test-secret for most tests.
- STU_AUTH_MODE=dev + no token for the dev-mode WebSocket test.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# ── Helpers ─────────────────────────────────────────────────────────


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI):
    """Lifespan that does nothing -- skips scheduler and auth startup."""
    yield


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def _enforce_auth(monkeypatch):
    """Set enforce mode with a known token for the auth module."""
    monkeypatch.setenv("STU_AUTH_MODE", "enforce")
    monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "test-secret")


@pytest.fixture()
def _dev_mode_no_token(monkeypatch):
    """Dev mode with no token configured -- connections allowed."""
    monkeypatch.setenv("STU_AUTH_MODE", "dev")
    monkeypatch.delenv("STU_LEARNER_AUTH_TOKEN", raising=False)


@pytest.fixture()
def client(_enforce_auth):
    """Test client with auth enforcement enabled.

    Bypasses the full lifespan (scheduler startup requires a real
    config) by building the app without starting the scheduler.
    The app factory itself does not require lifespan to wire routes.
    """
    from clawstu.api.main import create_app

    # Build the app but skip lifespan (no scheduler, no startup check)
    app = create_app()
    # Override lifespan so TestClient doesn't trigger validate_auth_on_startup
    # which would call SystemExit. We test routes, not startup validation.
    app.router.lifespan_context = _noop_lifespan
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def dev_client(_dev_mode_no_token):
    """Test client in dev mode (no auth required)."""
    from clawstu.api.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    return TestClient(app, raise_server_exceptions=False)


# ── 1-9: Protected HTTP routes must reject unauthenticated requests ──


class TestHttpRoutesRejectNoAuth:
    """Every protected HTTP route returns 401 without a Bearer token."""

    def test_post_sessions_without_auth_returns_401(self, client: TestClient):
        """POST /sessions without auth -> 401 (not 201)."""
        resp = client.post(
            "/sessions",
            json={
                "learner_id": "alice",
                "age": 12,
                "domain": "us_history",
            },
        )
        assert resp.status_code == 401, (
            f"POST /sessions without auth must be 401, got {resp.status_code}"
        )

    def test_get_session_without_auth_returns_401(self, client: TestClient):
        """GET /sessions/{id} without auth -> 401."""
        resp = client.get("/sessions/nonexistent")
        assert resp.status_code == 401

    def test_post_calibration_answer_without_auth_returns_401(
        self, client: TestClient,
    ):
        """POST /sessions/{id}/calibration-answer without auth -> 401."""
        resp = client.post(
            "/sessions/nonexistent/calibration-answer",
            json={"item_id": "x", "response": "y"},
        )
        assert resp.status_code == 401

    def test_post_check_answer_without_auth_returns_401(
        self, client: TestClient,
    ):
        """POST /sessions/{id}/check-answer without auth -> 401."""
        resp = client.post(
            "/sessions/nonexistent/check-answer",
            json={"item_id": "x", "response": "y"},
        )
        assert resp.status_code == 401

    def test_post_socratic_without_auth_returns_401(
        self, client: TestClient,
    ):
        """POST /sessions/{id}/socratic without auth -> 401."""
        resp = client.post(
            "/sessions/nonexistent/socratic",
            json={"student_input": "what is democracy?"},
        )
        assert resp.status_code == 401

    def test_get_profile_without_auth_returns_401(self, client: TestClient):
        """GET /profile/{id} without auth -> 401."""
        resp = client.get("/profile/nonexistent")
        assert resp.status_code == 401

    def test_get_profile_export_without_auth_returns_401(
        self, client: TestClient,
    ):
        """GET /profile/{id}/export without auth -> 401."""
        resp = client.get("/profile/nonexistent/export")
        assert resp.status_code == 401

    def test_delete_profile_without_auth_returns_401(
        self, client: TestClient,
    ):
        """DELETE /profile/{id} without auth -> 401."""
        resp = client.delete("/profile/nonexistent")
        assert resp.status_code == 401

    def test_get_admin_scheduler_without_auth_returns_401(
        self, client: TestClient,
    ):
        """GET /admin/scheduler without auth -> 401."""
        resp = client.get("/admin/scheduler")
        assert resp.status_code == 401


# ── 10: Health endpoint stays public ─────────────────────────────────


class TestHealthStaysPublic:
    """GET /admin/health must remain accessible without auth."""

    def test_admin_health_returns_200_without_auth(self, client: TestClient):
        """GET /admin/health without auth -> 200."""
        resp = client.get("/admin/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")


# ── 11-13: WebSocket auth ────────────────────────────────────────────


class TestWebSocketAuth:
    """WebSocket /ws/chat enforces token auth in enforce mode."""

    def test_ws_no_token_receives_error_and_close_1008(
        self, client: TestClient,
    ):
        """WS /ws/chat without token -> error message + close 1008."""
        with client.websocket_connect("/ws/chat") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "unauthorized" in msg["message"].lower()
            # Server should close with code 1008 after sending error.
            # The next receive will raise or return close frame.
            try:
                ws.receive_json()
                pytest.fail("Expected WebSocket to close after error")
            except Exception:
                pass  # Expected: close frame or disconnect

    def test_ws_bad_token_receives_error_and_close_1008(
        self, client: TestClient,
    ):
        """WS /ws/chat with wrong token -> error message + close 1008."""
        with client.websocket_connect("/ws/chat?token=wrong-token") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "unauthorized" in msg["message"].lower()
            try:
                ws.receive_json()
                pytest.fail("Expected WebSocket to close after error")
            except Exception:
                pass

    def test_ws_dev_mode_connects_without_token(
        self, dev_client: TestClient,
    ):
        """WS /ws/chat in dev mode with no token -> connects OK."""
        with dev_client.websocket_connect("/ws/chat") as ws:
            # In dev mode without a token, the connection should be
            # accepted. Send an onboard message to prove the session
            # handshake proceeds past the auth check.
            ws.send_json({
                "type": "onboard",
                "name": "Test",
                "age": 10,
            })
            msg = ws.receive_json()
            # Should get a setup, degraded, or error about domain --
            # anything other than "unauthorized" proves auth passed.
            assert msg.get("type") != "error" or "unauthorized" not in msg.get(
                "message", "",
            ).lower(), (
                f"Dev mode WS should not reject as unauthorized, got: {msg}"
            )


# ── Bonus: wrong token on HTTP routes also rejected ──────────────────


class TestWrongTokenRejected:
    """A bad bearer token must also be rejected, not just missing."""

    def test_post_sessions_with_wrong_token_returns_401(
        self, client: TestClient,
    ):
        resp = client.post(
            "/sessions",
            json={
                "learner_id": "alice",
                "age": 12,
                "domain": "us_history",
            },
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_get_session_with_wrong_token_returns_401(
        self, client: TestClient,
    ):
        resp = client.get(
            "/sessions/x",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
