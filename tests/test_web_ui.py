"""Tests for the web UI static-file serving at GET /."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    fresh_state = AppState()
    app.dependency_overrides[get_state] = lambda: fresh_state
    with TestClient(app) as tc:
        yield tc


def test_get_root_returns_html(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Stuart" in resp.text


def test_static_css_loads(client: TestClient) -> None:
    resp = client.get("/static/stu.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_static_js_loads(client: TestClient) -> None:
    resp = client.get("/static/stu.js")
    assert resp.status_code == 200
    ct = resp.headers["content-type"]
    assert "javascript" in ct or "text/plain" in ct


def test_onboard_form_present_in_html(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="onboard-form"' in resp.text


def test_health_alias_returns_ok(client: TestClient) -> None:
    """GET /health is an alias for GET /admin/health."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "invariants" in body


def test_admin_health_returns_ok(client: TestClient) -> None:
    """The canonical /admin/health endpoint returns the same payload."""
    resp = client.get("/admin/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
