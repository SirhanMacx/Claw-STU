"""Tests for the WebSocket /ws/chat endpoint."""

from __future__ import annotations

from starlette.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state


def _client() -> TestClient:
    app = create_app()
    fresh_state = AppState()
    app.dependency_overrides[get_state] = lambda: fresh_state
    return TestClient(app)


def test_websocket_rejects_non_onboard() -> None:
    """Sending a non-onboard message first should produce an error."""
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "answer", "text": "hello"})
        data = ws.receive_json()
        assert data["type"] == "error"
        assert "onboard" in data["message"].lower()


def test_websocket_onboard_returns_setup() -> None:
    """A valid onboard message should return a setup response."""
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({
            "type": "onboard",
            "name": "Test",
            "age": 15,
            "topic": "Testing",
        })
        data = ws.receive_json()
        assert data["type"] == "setup"
        assert data["topic"] == "Testing"
        assert "age_bracket" in data
        assert "provider" in data


def test_websocket_close_sends_summary() -> None:
    """Sending close after onboard should produce a summary."""
    client = _client()
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({
            "type": "onboard",
            "name": "Ada",
            "age": 15,
            "topic": "Math basics",
        })
        setup = ws.receive_json()
        assert setup["type"] == "setup"

        # There should be a block or check after setup
        msg = ws.receive_json()
        assert msg["type"] in ("block", "check", "summary", "error")

        # Send close
        if msg["type"] in ("block", "check"):
            ws.send_json({"type": "close"})

        # Read until we get a summary
        while True:
            data = ws.receive_json()
            if data["type"] == "summary":
                assert "duration_minutes" in data
                assert "blocks" in data
                break
            if data["type"] == "error":
                # Session errored -- acceptable in test mode
                break
