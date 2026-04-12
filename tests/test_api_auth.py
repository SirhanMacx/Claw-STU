"""Tests for the learner-facing bearer-token auth dependency.

Spec reference: SS4.9.2 (N8). The dependency is a no-op when
``STU_LEARNER_AUTH_TOKEN`` is unset (dev mode), and enforces a
constant-time bearer-token match when the env var is set.

These tests exercise the dependency through a throwaway FastAPI app
so the Header(...) machinery actually runs -- calling the function
directly would bypass the dependency-injection layer that pulls the
``Authorization`` header off the request.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from clawstu.api.auth import require_learner_auth


def _auth_app() -> FastAPI:
    """Build a minimal FastAPI app with one route behind the dep."""
    app = FastAPI()

    @app.get("/learners/{learner_id}/ping")
    def ping(
        learner_id: str,
        _auth: None = Depends(require_learner_auth),
    ) -> dict[str, str]:
        return {"learner_id": learner_id, "status": "ok"}

    return app


class TestLearnerAuth:
    def test_no_token_set_passes_without_header(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dev mode: env var unset -> any request is allowed through."""
        monkeypatch.delenv("STU_LEARNER_AUTH_TOKEN", raising=False)
        with TestClient(_auth_app()) as client:
            response = client.get("/learners/alice/ping")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"

    def test_token_set_correct_bearer_passes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Token set + matching bearer header -> 200 ok."""
        monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "s3cret-token")
        with TestClient(_auth_app()) as client:
            response = client.get(
                "/learners/alice/ping",
                headers={"Authorization": "Bearer s3cret-token"},
            )
            assert response.status_code == 200
            assert response.json()["learner_id"] == "alice"

    def test_token_set_missing_or_wrong_bearer_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Token set -> missing header, wrong prefix, or wrong value all 401."""
        monkeypatch.setenv("STU_LEARNER_AUTH_TOKEN", "s3cret-token")
        with TestClient(_auth_app()) as client:
            # Missing header entirely.
            missing = client.get("/learners/alice/ping")
            assert missing.status_code == 401
            assert missing.json() == {"detail": "unauthorized"}

            # Header present but not a bearer prefix.
            wrong_scheme = client.get(
                "/learners/alice/ping",
                headers={"Authorization": "Basic s3cret-token"},
            )
            assert wrong_scheme.status_code == 401

            # Bearer prefix but wrong token.
            wrong_value = client.get(
                "/learners/alice/ping",
                headers={"Authorization": "Bearer not-the-token"},
            )
            assert wrong_value.status_code == 401
            assert wrong_value.json() == {"detail": "unauthorized"}
