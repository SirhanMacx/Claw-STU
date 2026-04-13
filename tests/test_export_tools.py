"""Tests for export tools (Phase 3).

All file I/O uses tmp_path so nothing touches real disk.
ToolContext fields that tools don't use are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawstu.agent.base_tool import ToolContext


def _make_ctx(tmp_path: Path) -> ToolContext:
    """Build a ToolContext with mocked heavy deps."""
    return ToolContext(
        profile=MagicMock(),
        session_id="test-session",
        brain=MagicMock(),
        router=MagicMock(),
        output_dir=tmp_path,
    )


# ---------- export_pdf ----------


@pytest.mark.asyncio
async def test_export_pdf_fallback(tmp_path: Path) -> None:
    """When WeasyPrint is missing, returns a fallback message."""
    from clawstu.agent.tools.export_pdf import ExportPDFTool

    md = tmp_path / "notes.md"
    md.write_text("# Hello\nWorld", encoding="utf-8")
    ctx = _make_ctx(tmp_path)

    with patch.dict("sys.modules", {"weasyprint": None}):
        tool = ExportPDFTool()
        result = await tool.execute({"source_path": str(md)}, ctx)

    assert "WeasyPrint" in result or "not installed" in result.lower()


@pytest.mark.asyncio
async def test_export_pdf_weasyprint(tmp_path: Path) -> None:
    """When WeasyPrint is available, produces a PDF."""
    from clawstu.agent.tools.export_pdf import ExportPDFTool

    html = tmp_path / "page.html"
    html.write_text("<html><body>Hello</body></html>", encoding="utf-8")
    out = tmp_path / "page.pdf"
    ctx = _make_ctx(tmp_path)

    mock_html_cls = MagicMock()
    mock_html_cls.return_value.write_pdf = MagicMock(
        side_effect=lambda p: Path(p).write_bytes(b"%PDF"),
    )

    with patch.dict("sys.modules", {"weasyprint": MagicMock(HTML=mock_html_cls)}):
        tool = ExportPDFTool()
        result = await tool.execute({"source_path": str(html), "output_path": str(out)}, ctx)

    assert "pdf" in result.lower() or "PDF" in result
    assert out.exists()


# ---------- export_docx ----------


@pytest.mark.asyncio
async def test_export_docx(tmp_path: Path) -> None:
    from clawstu.agent.tools.export_docx import ExportDocxTool

    md = tmp_path / "guide.md"
    md.write_text("# Title\n\nParagraph\n\n- bullet\n\n1. numbered", encoding="utf-8")
    out = tmp_path / "guide.docx"
    ctx = _make_ctx(tmp_path)

    mock_doc = MagicMock()
    mock_document = MagicMock(return_value=mock_doc)
    mock_doc.save = MagicMock(side_effect=lambda p: Path(p).write_bytes(b"PK"))

    with patch.dict("sys.modules", {"docx": MagicMock(Document=mock_document)}):
        tool = ExportDocxTool()
        result = await tool.execute({"source_path": str(md), "output_path": str(out)}, ctx)

    assert "DOCX" in result or "docx" in result
    assert out.exists()


# ---------- export_html ----------


@pytest.mark.asyncio
async def test_export_html_inlines_assets(tmp_path: Path) -> None:
    from clawstu.agent.tools.export_html import ExportHTMLTool

    img = tmp_path / "logo.png"
    img.write_bytes(b"\x89PNG")
    src = tmp_path / "game.html"
    src.write_text('<html><body><img src="logo.png"></body></html>', encoding="utf-8")
    ctx = _make_ctx(tmp_path)

    tool = ExportHTMLTool()
    result = await tool.execute({"source_path": str(src)}, ctx)

    assert "standalone" in result.lower() or "HTML" in result
    # The output file should have inlined the image.
    out = tmp_path / "game_standalone.html"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "data:image/png;base64," in content
    assert 'src="logo.png"' not in content


# ---------- export_flashcards ----------


@pytest.mark.asyncio
async def test_export_flashcards_csv(tmp_path: Path) -> None:
    from clawstu.agent.tools.export_flashcards import ExportFlashcardsTool

    cards = [{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"}]
    ctx = _make_ctx(tmp_path)
    tool = ExportFlashcardsTool()
    result = await tool.execute({"cards_json": json.dumps(cards), "format": "csv"}, ctx)

    assert "CSV" in result or "csv" in result.lower()
    out = tmp_path / "flashcards.csv"
    assert out.exists()
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    assert "Q1" in lines[0]


@pytest.mark.asyncio
async def test_export_flashcards_anki_fallback(tmp_path: Path) -> None:
    """When genanki is missing, falls back to CSV."""
    from clawstu.agent.tools.export_flashcards import ExportFlashcardsTool

    cards = [{"front": "Q1", "back": "A1"}]
    ctx = _make_ctx(tmp_path)

    with patch.dict("sys.modules", {"genanki": None}):
        tool = ExportFlashcardsTool()
        result = await tool.execute({"cards_json": json.dumps(cards), "format": "anki"}, ctx)

    assert "CSV" in result or "csv" in result.lower()
