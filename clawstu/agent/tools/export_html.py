"""Package interactive content as standalone HTML.

Copies the HTML file and inlines any referenced local assets (images as
base64 data-URIs, CSS/JS as inline blocks) so the result is self-contained.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


def _inline_assets(html: str, base_dir: Path) -> str:
    """Replace local src/href references with inline data."""

    def _replace_src(match: re.Match[str]) -> str:
        attr, path_str = match.group(1), match.group(2)
        asset = base_dir / path_str
        if not asset.is_file():
            return match.group(0)
        mime = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
        data = base64.b64encode(asset.read_bytes()).decode()
        return f'{attr}="data:{mime};base64,{data}"'

    return re.sub(r'(src|href)="(?!data:|https?://|#)([^"]+)"', _replace_src, html)


class ExportHTMLTool(BaseTool):
    name = "export_html"
    description = "Package an HTML file as standalone with inlined assets."
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "source_path": {"type": "string", "description": "Path to HTML file"},
            "output_path": {"type": "string", "description": "Output path"},
        },
        "required": ["source_path"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        source_path = Path(args["source_path"])
        output_path = Path(
            args.get("output_path")
            or source_path.with_stem(source_path.stem + "_standalone"),
        )
        html = source_path.read_text(encoding="utf-8")
        standalone = _inline_assets(html, source_path.parent)
        output_path.write_text(standalone, encoding="utf-8")
        return f"Exported standalone HTML: {output_path}"
