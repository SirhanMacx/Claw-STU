"""Smoke tests for docs/API.md completeness."""

from __future__ import annotations

from pathlib import Path

_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def test_api_md_exists() -> None:
    """docs/API.md must exist."""
    assert (_DOCS_DIR / "API.md").exists()


def test_api_md_covers_key_endpoints() -> None:
    """API.md must document every major endpoint."""
    content = (_DOCS_DIR / "API.md").read_text(encoding="utf-8")
    required = [
        "POST /sessions",
        "GET /sessions/{session_id}",
        "/calibration-answer",
        "/finish-calibration",
        "/next",
        "/check-answer",
        "/socratic",
        "/close",
        "POST /api/ask",
        "GET /profile/",
        "DELETE /profile/",
        "/wiki/",
        "/resume",
        "/queue",
        "/capture",
        "GET /health",
        "GET /admin/health",
        "GET /admin/scheduler",
        "WS /ws/chat",
    ]
    for endpoint in required:
        assert endpoint in content, f"API.md missing: {endpoint}"
