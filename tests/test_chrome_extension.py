"""Tests for the Chrome extension and the /api/ask endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state

_EXT_DIR = Path(__file__).resolve().parent.parent / "extension"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    fresh_state = AppState()
    app.dependency_overrides[get_state] = lambda: fresh_state
    with TestClient(app) as tc:
        yield tc


def test_chrome_extension_manifest_exists() -> None:
    """Extension directory must contain a valid Manifest V3."""
    manifest = _EXT_DIR / "manifest.json"
    assert manifest.exists(), f"manifest.json not found at {manifest}"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["manifest_version"] == 3
    assert "Claw-STU" in data["name"]


def test_extension_has_required_files() -> None:
    """Extension must have popup, background, content script, and styles."""
    for filename in ["popup.html", "popup.js", "background.js", "content.js", "styles.css"]:
        path = _EXT_DIR / filename
        assert path.exists(), f"Missing extension file: {filename}"


def test_extension_icons_exist() -> None:
    """Extension must have icon files referenced by manifest."""
    for size in [16, 48, 128]:
        icon = _EXT_DIR / "icons" / f"icon{size}.png"
        assert icon.exists(), f"Missing icon: icon{size}.png"


def test_api_ask_returns_response(client: TestClient) -> None:
    """POST /api/ask should return a Socratic response."""
    resp = client.post("/api/ask", json={"question": "What is photosynthesis?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert data["crisis"] is False
    assert len(data["response"]) > 0


def test_api_ask_rejects_empty_question(client: TestClient) -> None:
    """POST /api/ask should reject an empty question."""
    resp = client.post("/api/ask", json={"question": ""})
    assert resp.status_code == 422
