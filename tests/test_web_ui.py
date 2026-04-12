"""Tests for the web UI static-file serving at GET /."""

from __future__ import annotations

from fastapi.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state


def _client() -> TestClient:
    app = create_app()
    fresh_state = AppState()
    app.dependency_overrides[get_state] = lambda: fresh_state
    return TestClient(app)


def test_get_root_returns_html() -> None:
    client = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Stuart" in resp.text


def test_static_css_loads() -> None:
    client = _client()
    resp = client.get("/static/stu.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_static_js_loads() -> None:
    client = _client()
    resp = client.get("/static/stu.js")
    assert resp.status_code == 200
    ct = resp.headers["content-type"]
    assert "javascript" in ct or "text/plain" in ct


def test_onboard_form_present_in_html() -> None:
    client = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="onboard-form"' in resp.text
