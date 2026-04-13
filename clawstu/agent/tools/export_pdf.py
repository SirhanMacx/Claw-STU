"""Export any markdown/HTML artifact as PDF.

Uses WeasyPrint when available; falls back to returning markdown as-is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class ExportPDFTool(BaseTool):
    name = "export_pdf"
    description = "Export a markdown or HTML file as a PDF document."
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "source_path": {"type": "string", "description": "Path to source file"},
            "output_path": {"type": "string", "description": "Output PDF path"},
        },
        "required": ["source_path"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        source_path = Path(args["source_path"])
        output_path = Path(args.get("output_path") or source_path.with_suffix(".pdf"))
        content = source_path.read_text(encoding="utf-8")

        if source_path.suffix.lower() == ".md":
            content = f"<html><body><pre>{content}</pre></body></html>"

        try:
            from weasyprint import HTML

            HTML(string=content).write_pdf(str(output_path))
            return f"Exported PDF: {output_path} ({output_path.stat().st_size} bytes)"
        except ImportError:
            fallback = output_path.with_suffix(source_path.suffix)
            fallback.write_text(content, encoding="utf-8")
            return f"WeasyPrint not installed. Saved source as {fallback}"
