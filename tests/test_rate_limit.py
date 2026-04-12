"""Tests for the in-memory per-IP rate limiter.

Exercises the ``_RateLimiter`` decorator, the ``_rate_store`` /
``_rate_request_count`` globals, the ``reset_rate_state()`` helper,
and the ``_cleanup_rate_store()`` pruning logic.

The autouse ``_clear_rate_limits`` fixture in conftest already calls
``reset_rate_state()`` before every test, so each test starts clean.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from clawstu.api.rate_limit import (
    _cleanup_rate_store,
    _rate_store,
    limiter,
    reset_rate_state,
)


def _rate_app(rate_string: str = "3/minute") -> FastAPI:
    """Minimal FastAPI app with one rate-limited route."""
    app = FastAPI()

    @app.get("/ping")
    @limiter.limit(rate_string)
    async def ping(request: Request) -> dict[str, str]:
        return {"status": "ok"}

    return app


# ── Burst / 429 ──────────────────────────────────────────────────────


class TestRateLimitBurst:
    """Requests exceeding the limit return 429."""

    def test_burst_returns_429(self) -> None:
        app = _rate_app("3/minute")
        with TestClient(app) as client:
            for _ in range(3):
                resp = client.get("/ping")
                assert resp.status_code == 200

            # 4th request should be rate-limited.
            resp = client.get("/ping")
            assert resp.status_code == 429
            assert "Rate limit exceeded" in resp.json()["detail"]

    def test_second_per_limit(self) -> None:
        """A per-second limit triggers within a tight loop."""
        app = _rate_app("2/second")
        with TestClient(app) as client:
            for _ in range(2):
                resp = client.get("/ping")
                assert resp.status_code == 200

            resp = client.get("/ping")
            assert resp.status_code == 429


# ── Reset ────────────────────────────────────────────────────────────


class TestResetRateState:
    """``reset_rate_state()`` clears the store so new requests pass."""

    def test_reset_allows_new_requests(self) -> None:
        app = _rate_app("2/minute")
        with TestClient(app) as client:
            # Exhaust the limit.
            for _ in range(2):
                client.get("/ping")
            assert client.get("/ping").status_code == 429

            # Reset and verify requests succeed again.
            reset_rate_state()
            resp = client.get("/ping")
            assert resp.status_code == 200


# ── Cleanup ──────────────────────────────────────────────────────────


class TestCleanup:
    """``_cleanup_rate_store()`` prunes stale entries."""

    def test_cleanup_removes_expired_entries(self) -> None:
        # Manually populate the store with old timestamps.
        _rate_store.clear()
        old_time = time.time() - 120  # 2 minutes ago
        _rate_store["1.2.3.4:ping"] = [old_time, old_time + 1]

        # Cleanup with a 60-second window should remove both.
        _cleanup_rate_store(window=60)
        assert "1.2.3.4:ping" not in _rate_store

    def test_cleanup_keeps_recent_entries(self) -> None:
        _rate_store.clear()
        now = time.time()
        _rate_store["1.2.3.4:ping"] = [now - 5, now - 2, now]

        _cleanup_rate_store(window=60)
        # All entries are within the 60-second window.
        assert "1.2.3.4:ping" in _rate_store
        assert len(_rate_store["1.2.3.4:ping"]) == 3

    def test_cleanup_partial_prune(self) -> None:
        """Only timestamps older than `window` are pruned."""
        _rate_store.clear()
        now = time.time()
        _rate_store["ip:fn"] = [now - 90, now - 30, now - 5]

        _cleanup_rate_store(window=60)
        # The 90-second-old entry is gone; the two recent ones stay.
        assert len(_rate_store["ip:fn"]) == 2
