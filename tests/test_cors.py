"""Tests for the CORS middleware configured in ``create_app()``.

Verifies that the middleware honours default localhost origins, custom
origins via ``CLAW_STU_CORS_ORIGINS``, and the Chrome-extension regex
pattern.  Uses ``starlette.testclient.TestClient`` to issue preflight
OPTIONS requests directly against the FastAPI app.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clawstu.api.main import create_app
from clawstu.api.state import AppState, get_state


def _make_client(monkeypatch: pytest.MonkeyPatch, *, cors_env: str | None = None) -> TestClient:
    """Build a TestClient with optional CORS env var override.

    The env var must be patched *before* ``create_app()`` runs because
    the middleware reads ``CLAW_STU_CORS_ORIGINS`` at import time inside
    ``create_app()``.
    """
    if cors_env is not None:
        monkeypatch.setenv("CLAW_STU_CORS_ORIGINS", cors_env)
    else:
        monkeypatch.delenv("CLAW_STU_CORS_ORIGINS", raising=False)
    app = create_app()
    fresh_state = AppState()
    app.dependency_overrides[get_state] = lambda: fresh_state
    return TestClient(app, raise_server_exceptions=False)


# ── Default origins ──────────────────────────────────────────────────


class TestDefaultOrigins:
    """When CLAW_STU_CORS_ORIGINS is unset, localhost:8000 is allowed."""

    def test_preflight_from_localhost(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"
        # Allowed methods must include GET and POST.
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        assert "GET" in allow_methods
        assert "POST" in allow_methods

    def test_preflight_from_127(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"

    def test_allowed_headers(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        allow_headers = resp.headers.get("access-control-allow-headers", "")
        assert "authorization" in allow_headers.lower()
        assert "content-type" in allow_headers.lower()


# ── Chrome extension origins ────────────────────────────────────────


class TestChromeExtensionOrigin:
    """The regex ``^chrome-extension://[a-z]{32}$`` allows extensions."""

    def test_valid_extension_origin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        origin = "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef"
        client = _make_client(monkeypatch)
        resp = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == origin

    def test_invalid_extension_origin_too_short(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        origin = "chrome-extension://abc"
        client = _make_client(monkeypatch)
        resp = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None

    def test_invalid_extension_origin_uppercase(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Uppercase letters should not match [a-z]{32}.
        origin = "chrome-extension://ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEF"
        client = _make_client(monkeypatch)
        resp = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None


# ── Disallowed origins ──────────────────────────────────────────────


class TestDisallowedOrigin:
    """Origins not in the allow-list must not get CORS headers."""

    def test_random_origin_rejected(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None


# ── Custom env var origins ──────────────────────────────────────────


class TestCustomOrigins:
    """``CLAW_STU_CORS_ORIGINS`` overrides the default list."""

    def test_custom_origin_allowed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client(
            monkeypatch, cors_env="https://school.example.com,https://lab.example.com",
        )
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://school.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://school.example.com"

    def test_default_origin_not_in_custom_list(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When custom origins are set, the defaults are replaced."""
        client = _make_client(
            monkeypatch, cors_env="https://only-this.example.com",
        )
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None

    def test_chrome_extension_still_works_with_custom_origins(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The regex pattern is independent of the explicit allow list."""
        origin = "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef"
        client = _make_client(
            monkeypatch, cors_env="https://only-this.example.com",
        )
        resp = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == origin
