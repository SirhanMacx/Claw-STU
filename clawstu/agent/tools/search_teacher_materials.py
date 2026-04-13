"""Search Ed's ingested curriculum knowledge base.

Reads from SHARED_KB_PATH (defaults to ``~/.eduagent/``).  Returns
an empty list when no KB exists -- never errors.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext

_DEFAULT_KB = Path.home() / ".eduagent"


def _kb_path() -> Path:
    return Path(os.environ.get("SHARED_KB_PATH", str(_DEFAULT_KB)))


class SearchTeacherMaterialsTool(BaseTool):
    name = "search_teacher_materials"
    description = "Search the teacher's ingested curriculum knowledge base."
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 5)"},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        query = args.get("query", "")
        limit = int(args.get("limit", 5))
        kb = _kb_path()

        try:
            from clawed.knowledge.curriculum_kb import CurriculumKB  # type: ignore[import-untyped]

            results = CurriculumKB(kb).search(query, limit=limit)
            rows = [{"title": r.title, "preview": r.snippet[:200]} for r in results]
            return json.dumps(rows) if rows else "No teacher materials found."
        except Exception:
            pass

        db = kb / "kb" / "sources.db"
        if not db.is_file():
            return "No teacher knowledge base found."
        conn = sqlite3.connect(str(db))
        try:
            rows_raw = conn.execute(
                "SELECT title, content FROM sources WHERE content LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            rows = [{"title": r[0], "preview": r[1][:200]} for r in rows_raw]
            return json.dumps(rows) if rows else "No results."
        finally:
            conn.close()
