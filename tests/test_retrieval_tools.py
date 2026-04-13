"""Tests for retrieval tools (Phase 4).

HTTP calls are mocked; no real network access.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawstu.agent.base_tool import ToolContext


def _make_ctx(tmp_path: Path | None = None) -> ToolContext:
    """Build a ToolContext with mocked heavy deps."""
    return ToolContext(
        profile=MagicMock(),
        session_id="test-session",
        brain=MagicMock(),
        router=MagicMock(),
        output_dir=tmp_path or Path("/tmp"),
    )


# ---------- search_web ----------


@pytest.mark.asyncio
async def test_search_web_returns_results() -> None:
    from clawstu.agent.tools.search_web import SearchWebTool

    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "AbstractText": "Photosynthesis is the process...",
        "AbstractURL": "https://en.wikipedia.org/wiki/Photosynthesis",
        "Heading": "Photosynthesis",
        "RelatedTopics": [
            {"Text": "Light reactions in plants", "FirstURL": "https://example.com/light"},
        ],
    }
    fake_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=fake_resp)

    with patch("clawstu.agent.tools.search_web.httpx.AsyncClient", return_value=mock_client):
        tool = SearchWebTool()
        result = await tool.execute({"query": "photosynthesis"}, _make_ctx())

    parsed = json.loads(result)
    assert len(parsed) >= 1
    assert parsed[0]["title"] == "Photosynthesis"


@pytest.mark.asyncio
async def test_search_web_filters_adult_content() -> None:
    from clawstu.agent.tools.search_web import SearchWebTool

    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "RelatedTopics": [
            {"Text": "Safe topic about biology", "FirstURL": "https://example.com/bio"},
            {"Text": "Contains porn keyword", "FirstURL": "https://example.com/bad"},
        ],
    }
    fake_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=fake_resp)

    with patch("clawstu.agent.tools.search_web.httpx.AsyncClient", return_value=mock_client):
        tool = SearchWebTool()
        result = await tool.execute({"query": "biology"}, _make_ctx())

    parsed = json.loads(result)
    assert len(parsed) == 1
    assert "porn" not in json.dumps(parsed).lower()


# ---------- search_teacher_materials ----------


@pytest.mark.asyncio
async def test_search_teacher_materials_no_kb() -> None:
    """When no KB exists, returns a no-materials message."""
    from clawstu.agent.tools.search_teacher_materials import SearchTeacherMaterialsTool

    with patch(
        "clawstu.agent.tools.search_teacher_materials._kb_path",
        return_value=Path("/nonexistent"),
    ):
        tool = SearchTeacherMaterialsTool()
        result = await tool.execute({"query": "civil war"}, _make_ctx())

    # Should return a message (not raise), indicating no KB found.
    assert "no" in result.lower() or "not found" in result.lower() or result == "[]"


@pytest.mark.asyncio
async def test_search_teacher_materials_sqlite_fallback(tmp_path: Path) -> None:
    """Fallback SQLite query works when Ed is not importable."""
    import sqlite3

    kb_dir = tmp_path / "kb"
    kb_dir.mkdir(parents=True)
    db_path = kb_dir / "sources.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE sources (title TEXT, content TEXT, path TEXT)")
    conn.execute(
        "INSERT INTO sources VALUES (?, ?, ?)",
        ("Civil War Notes", "The causes of the civil war...", "/docs/cw.md"),
    )
    conn.commit()
    conn.close()

    from clawstu.agent.tools.search_teacher_materials import SearchTeacherMaterialsTool

    with patch(
        "clawstu.agent.tools.search_teacher_materials._kb_path",
        return_value=tmp_path,
    ):
        tool = SearchTeacherMaterialsTool()
        result = await tool.execute({"query": "civil war"}, _make_ctx(tmp_path))

    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Civil War Notes"


# ---------- fetch_source ----------


@pytest.mark.asyncio
async def test_fetch_source_local_file(tmp_path: Path) -> None:
    from clawstu.agent.tools.fetch_source import FetchSourceTool

    f = tmp_path / "notes.txt"
    f.write_text("Short content here.", encoding="utf-8")

    tool = FetchSourceTool()
    result = await tool.execute({"path_or_url": str(f)}, _make_ctx(tmp_path))

    assert "Short content here." in result


@pytest.mark.asyncio
async def test_fetch_source_missing_file() -> None:
    from clawstu.agent.tools.fetch_source import FetchSourceTool

    tool = FetchSourceTool()
    result = await tool.execute({"path_or_url": "/nonexistent/file.txt"}, _make_ctx())

    assert "not found" in result.lower() or "error" in result.lower()


@pytest.mark.asyncio
async def test_fetch_source_url() -> None:
    from clawstu.agent.tools.fetch_source import FetchSourceTool

    fake_resp = MagicMock()
    fake_resp.text = "Hello from the web"
    fake_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=fake_resp)

    with patch("clawstu.agent.tools.fetch_source.httpx.AsyncClient", return_value=mock_client):
        tool = FetchSourceTool()
        result = await tool.execute({"path_or_url": "https://example.com/page"}, _make_ctx())

    assert "Hello from the web" in result


@pytest.mark.asyncio
async def test_fetch_source_truncates_long_content(tmp_path: Path) -> None:
    from clawstu.agent.tools.fetch_source import FetchSourceTool

    f = tmp_path / "big.txt"
    f.write_text("x" * 10000, encoding="utf-8")

    tool = FetchSourceTool()
    result = await tool.execute({"path_or_url": str(f)}, _make_ctx(tmp_path))

    assert len(result) < 10000
    assert "[...truncated...]" in result
