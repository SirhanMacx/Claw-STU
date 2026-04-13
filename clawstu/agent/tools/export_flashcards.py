"""Export flashcards as Anki .apkg or CSV for Quizlet.

Supports two formats:
  - csv: two-column (front, back) with tab separator.
  - anki: .apkg via genanki if available; falls back to CSV.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext


class ExportFlashcardsTool(BaseTool):
    name = "export_flashcards"
    description = "Export flashcards as Anki .apkg or Quizlet-compatible CSV."
    parameters: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "cards_json": {
                "type": "string",
                "description": "JSON array of {front, back} objects",
            },
            "format": {
                "type": "string",
                "enum": ["csv", "anki"],
                "description": "Export format (default: csv)",
            },
        },
        "required": ["cards_json"],
    }

    async def execute(self, args: dict[str, Any], context: ToolContext) -> str:
        cards = json.loads(args["cards_json"])
        fmt = args.get("format", "csv")
        output_path = context.output_dir / "flashcards"

        if fmt == "anki":
            try:
                import genanki

                model = genanki.Model(
                    1607392319, "Simple",
                    fields=[{"name": "Front"}, {"name": "Back"}],
                    templates=[{
                        "name": "Card 1",
                        "qfmt": "{{Front}}",
                        "afmt": "{{Back}}",
                    }],
                )
                deck = genanki.Deck(2059400110, "Stuart Export")
                for c in cards:
                    deck.add_note(genanki.Note(model=model, fields=[c["front"], c["back"]]))
                out = output_path.with_suffix(".apkg")
                genanki.Package(deck).write_to_file(str(out))
                return f"Exported Anki deck: {out}"
            except ImportError:
                fmt = "csv"

        out = output_path.with_suffix(".csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="\t")
        for c in cards:
            writer.writerow([c["front"], c["back"]])
        out.write_text(buf.getvalue(), encoding="utf-8")
        return f"Exported flashcards CSV: {out} ({len(cards)} cards)"
