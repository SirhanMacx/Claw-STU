"""Brain page base class, frontmatter parser, and timeline primitives.

Every brain page renders to a markdown file shaped like this::

    ---
    kind: learner
    learner_id: test-learner
    updated_at: 2026-04-11T14:23:00+00:00
    schema_version: 1
    ---

    # Compiled Truth

    (Stuart's current best understanding, rewritten on update. This is the
    section the context assembler pulls into LLM prompts.)

    # Timeline

    - 2026-04-11T14:20:00+00:00 — calibration_answer — correct on tier=meeting
    - 2026-04-11T14:21:30+00:00 — check_for_understanding — missed tier=meeting

The timeline is append-only; the compiled-truth section is rewritten on
update by the dream cycle.

Why a custom frontmatter parser?
--------------------------------
The spec sketch (§4.3.2) uses YAML-style frontmatter, but Claw-STU does
not (and will not, as part of Phase 4) pull in PyYAML. Instead we use a
minimal line-based ``key: value`` parser that accepts scalars only.
Every frontmatter value in the Phase 4 page types is a string, an int,
or a datetime — no nested structures, no lists, no quoting rules. The
renderer and parser are tight inverses over that restricted grammar,
and the test suite round-trips every page type through them.

Extending the page model with a field that needs nesting (a list, a
map) should push that field into the markdown body, not into the
frontmatter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_FRONTMATTER_DELIMITER = "---"
_COMPILED_TRUTH_HEADER = "# Compiled Truth"
_TIMELINE_HEADER = "# Timeline"


class PageKind(str, Enum):
    """Discriminator tag in each page's frontmatter.

    Must match the directory name under ``~/.claw-stu/brain/<hash>/<kind>/``
    that `BrainStore` uses on disk. Renaming a value is a wire-format
    break and requires a schema migration.
    """

    LEARNER = "learner"
    CONCEPT = "concept"
    SESSION = "session"
    SOURCE = "source"
    MISCONCEPTION = "misconception"
    TOPIC = "topic"


class TimelineEntry(BaseModel):
    """One row in a brain page's append-only timeline.

    Timeline entries are small on purpose — rich structured data belongs
    in the compiled truth section, which the dream cycle rewrites.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    kind: str
    text: str


def _format_scalar(value: Any) -> str:
    """Render a frontmatter value as a single-line string.

    Accepts ``str``, ``int``, ``bool``, ``datetime``, and enum members.
    Anything else is rejected — frontmatter is a flat scalar namespace
    by design; complex values belong in the markdown body.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (int, str)):
        return str(value)
    raise TypeError(
        f"unsupported frontmatter scalar type: {type(value).__name__}"
    )


def render_frontmatter(fields: dict[str, Any]) -> str:
    """Render an ordered dict of frontmatter fields as a YAML-ish block.

    Returns a string that starts and ends with ``---`` lines, with one
    ``key: value`` per interior line. Preserves the caller's iteration
    order, which lets each page type fix its canonical field order.
    """
    lines = [_FRONTMATTER_DELIMITER]
    for key, value in fields.items():
        lines.append(f"{key}: {_format_scalar(value)}")
    lines.append(_FRONTMATTER_DELIMITER)
    return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a page body into its frontmatter dict and body remainder.

    Raises ``ValueError`` if the frontmatter block is malformed — a
    missing opening delimiter, an unterminated block, or a line without
    a ``key: value`` shape. The body is returned verbatim (including
    any leading blank line after the closing delimiter).
    """
    if not text.startswith(_FRONTMATTER_DELIMITER):
        raise ValueError(
            "brain page must start with a '---' frontmatter delimiter"
        )
    lines = text.split("\n")
    # lines[0] is the opening '---'; scan for the closing one.
    closing_index: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx] == _FRONTMATTER_DELIMITER:
            closing_index = idx
            break
    if closing_index is None:
        raise ValueError("brain page frontmatter is unterminated")
    fields: dict[str, str] = {}
    for line in lines[1:closing_index]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(
                f"malformed frontmatter line (no ':'): {line!r}"
            )
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    body = "\n".join(lines[closing_index + 1 :])
    return fields, body


class BrainPage(BaseModel):
    """Base class every page type inherits from.

    Subclasses set ``kind`` to a fixed ``PageKind`` and add their own
    typed fields. Each subclass overrides ``_frontmatter_fields`` to
    enumerate the dict of fields to render (in declaration order) and
    ``_parse_frontmatter_fields`` to interpret the frontmatter dict
    returned by `parse_frontmatter`.

    The compiled-truth / timeline split is universal across page
    types, so it lives here and is serialized the same way for every
    page.
    """

    model_config = ConfigDict(validate_assignment=True)

    kind: PageKind
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = 1
    compiled_truth: str = ""
    timeline: list[TimelineEntry] = Field(default_factory=list)

    # -- rendering -----------------------------------------------------

    def _frontmatter_fields(self) -> dict[str, Any]:
        """Return the frontmatter field dict in canonical order.

        Subclasses override and call ``super()._frontmatter_fields()`` to
        pick up the base fields (kind, the subclass id, updated_at,
        schema_version). By convention the base class only emits the
        ``kind``, ``updated_at``, and ``schema_version`` fields — the
        subclass id field is injected by the subclass so it can place
        the id immediately after the kind line.
        """
        return {
            "kind": self.kind,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
        }

    def render(self) -> str:
        """Render the page to a full markdown document string."""
        frontmatter = render_frontmatter(self._frontmatter_fields())
        body_parts = [
            frontmatter,
            "",
            _COMPILED_TRUTH_HEADER,
            "",
            self.compiled_truth,
            "",
            _TIMELINE_HEADER,
            "",
        ]
        if self.timeline:
            for entry in self.timeline:
                stamp = entry.timestamp.isoformat()
                body_parts.append(
                    f"- {stamp} — {entry.kind} — {entry.text}"
                )
        else:
            body_parts.append("- (no timeline entries)")
        return "\n".join(body_parts) + "\n"

    def append_timeline(self, entry: TimelineEntry) -> None:
        """Append a timeline entry and bump ``updated_at``."""
        self.timeline.append(entry)
        self.updated_at = datetime.now(UTC)

    # -- parsing -------------------------------------------------------

    @staticmethod
    def split_body(body: str) -> tuple[str, list[TimelineEntry]]:
        """Split a post-frontmatter body into (compiled_truth, timeline).

        Tolerant of extra blank lines. Unknown timeline entries fall
        through to the compiled truth section. The inverse of the
        ``render`` method above.
        """
        lines = body.split("\n")
        compiled_lines: list[str] = []
        timeline_lines: list[str] = []
        in_timeline = False
        in_compiled = False
        for line in lines:
            stripped = line.strip()
            if stripped == _COMPILED_TRUTH_HEADER:
                in_compiled = True
                in_timeline = False
                continue
            if stripped == _TIMELINE_HEADER:
                in_timeline = True
                in_compiled = False
                continue
            if in_timeline:
                timeline_lines.append(line)
            elif in_compiled:
                compiled_lines.append(line)
        compiled_truth = "\n".join(compiled_lines).strip("\n")
        timeline: list[TimelineEntry] = []
        for line in timeline_lines:
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            payload = stripped[2:]
            if payload == "(no timeline entries)":
                continue
            parts = payload.split(" — ", 2)
            if len(parts) != 3:
                continue
            try:
                stamp = datetime.fromisoformat(parts[0])
            except ValueError:
                continue
            timeline.append(
                TimelineEntry(timestamp=stamp, kind=parts[1], text=parts[2])
            )
        return compiled_truth, timeline
