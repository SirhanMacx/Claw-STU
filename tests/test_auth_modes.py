"""Tests for auth mode hardening (dev / enforce / generate).

Exercises the three ``STU_AUTH_MODE`` modes through a throwaway
FastAPI app that wires up ``require_learner_auth`` as a dependency,
so the full Header injection path runs.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from clawstu.api.auth import require_learner_auth


def _auth_app() -> FastAPI:
    """Minimal app with one route behind learner auth."""
    app = FastAPI()

    @app.get("/learners/{learner_id}/ping")
    def ping(
        learner_id: str,
        _auth: None = Depends(require_learner_auth),
    ) -> dict[str, str]:
        return {"learner_id": learner_id, "status": "ok"}

    return app


# ── Dev mode ─────────────────────────────────────────────────────────


class TestDevMode:
    """``STU_AUTH_MODE=dev`` (default for localhost)."""

    def test_no_token_no_header_succeeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dev + no token env var -> requests pass without auth."""
        monkeypatch.setenv("STU_AUTH_MODE", "dev")
        monkeypatch.delenv("STU_LEARNER_AUTH_TOKEN", raising=False)
        with TestClient(_auth_app()) as client:
            resp = client.get("/learners/alice/ping")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_token_set_requires_bearer(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dev + token env var set -> bearer header is enforced."""
        monkeypatch.setenv("STU_AUTH_MODE", "dev")
        monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "dev-token")
        with TestClient(_auth_app()) as client:
            # No header -> 401.
            resp = client.get("/learners/alice/ping")
            assert resp.status_code == 401

            # Correct header -> 200.
            resp = client.get(
                "/learners/alice/ping",
                headers={"Authorization": "Bearer dev-token"},
            )
            assert resp.status_code == 200


# ── Enforce mode ─────────────────────────────────────────────────────


class TestEnforceMode:
    """``STU_AUTH_MODE=enforce``."""

    def test_no_token_returns_500(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Enforce + no token -> 500 misconfiguration error."""
        monkeypatch.setenv("STU_AUTH_MODE", "enforce")
        monkeypatch.delenv("STU_LEARNER_AUTH_TOKEN", raising=False)
        with TestClient(_auth_app(), raise_server_exceptions=False) as client:
            resp = client.get("/learners/alice/ping")
            assert resp.status_code == 500
            assert "misconfigured" in resp.json()["detail"].lower()

    def test_correct_bearer_succeeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Enforce + correct token -> 200."""
        monkeypatch.setenv("STU_AUTH_MODE", "enforce")
        monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "enforce-secret")
        with TestClient(_auth_app()) as client:
            resp = client.get(
                "/learners/alice/ping",
                headers={"Authorization": "Bearer enforce-secret"},
            )
            assert resp.status_code == 200
            assert resp.json()["learner_id"] == "alice"

    def test_wrong_bearer_returns_401(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Enforce + wrong token -> 401."""
        monkeypatch.setenv("STU_AUTH_MODE", "enforce")
        monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "enforce-secret")
        with TestClient(_auth_app()) as client:
            resp = client.get(
                "/learners/alice/ping",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status_code == 401
            assert resp.json()["detail"] == "unauthorized"

    def test_missing_header_returns_401(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Enforce + no auth header -> 401."""
        monkeypatch.setenv("STU_AUTH_MODE", "enforce")
        monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "enforce-secret")
        with TestClient(_auth_app()) as client:
            resp = client.get("/learners/alice/ping")
            assert resp.status_code == 401


# ── Generate mode ────────────────────────────────────────────────────


class TestGenerateMode:
    """``STU_AUTH_MODE=generate`` auto-creates a token file."""

    def test_generates_token_and_allows_requests(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """Generate mode creates a token file, then enforces it."""
        token_file = tmp_path / "api_token"  # type: ignore[operator]
        data_dir = tmp_path  # type: ignore[assignment]

        monkeypatch.setenv("STU_AUTH_MODE", "generate")
        monkeypatch.delenv("STU_LEARNER_AUTH_TOKEN", raising=False)
        # Redirect the token file to a temp location.
        monkeypatch.setattr("clawstu.api.auth._DATA_DIR", data_dir)
        monkeypatch.setattr("clawstu.api.auth._TOKEN_FILE", token_file)

        with TestClient(_auth_app()) as client:
            # First request without header -> 401 (token generated but
            # the request still needs the bearer).
            resp = client.get("/learners/alice/ping")
            assert resp.status_code == 401

            # Token file should exist now.
            assert token_file.exists()
            token = token_file.read_text(encoding="utf-8").strip()
            assert len(token) > 16  # urlsafe token is ~43 chars.

            # Request with the generated token -> 200.
            resp = client.get(
                "/learners/alice/ping",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_reuses_persisted_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """If the token file already exists, generate mode reuses it."""
        token_file = tmp_path / "api_token"  # type: ignore[operator]
        data_dir = tmp_path  # type: ignore[assignment]
        token_file.write_text("preexisting-token\n", encoding="utf-8")

        monkeypatch.setenv("STU_AUTH_MODE", "generate")
        monkeypatch.delenv("STU_LEARNER_AUTH_TOKEN", raising=False)
        monkeypatch.setattr("clawstu.api.auth._DATA_DIR", data_dir)
        monkeypatch.setattr("clawstu.api.auth._TOKEN_FILE", token_file)

        with TestClient(_auth_app()) as client:
            resp = client.get(
                "/learners/alice/ping",
                headers={"Authorization": "Bearer preexisting-token"},
            )
            assert resp.status_code == 200
