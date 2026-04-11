"""Brain page base class, frontmatter parser, and timeline tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clawstu.memory.pages.base import (
    BrainPage,
    PageKind,
    TimelineEntry,
    parse_frontmatter,
    render_frontmatter,
)


def test_render_frontmatter_emits_delimited_block() -> None:
    text = render_frontmatter(
        {
            "kind": PageKind.LEARNER,
            "learner_id": "abc",
            "updated_at": datetime(2026, 4, 11, 14, 23, 0, tzinfo=UTC),
            "schema_version": 1,
        }
    )
    lines = text.split("\n")
    assert lines[0] == "---"
    assert lines[-1] == "---"
    assert "kind: learner" in lines
    assert "learner_id: abc" in lines
    assert "schema_version: 1" in lines


def test_parse_frontmatter_round_trips_the_renderer() -> None:
    fields = {
        "kind": PageKind.CONCEPT,
        "concept_id": "civil_war",
        "updated_at": datetime(2026, 4, 11, 14, 23, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    rendered = render_frontmatter(fields) + "\n\nbody content"
    parsed, body = parse_frontmatter(rendered)
    assert parsed["kind"] == "concept"
    assert parsed["concept_id"] == "civil_war"
    assert parsed["schema_version"] == "1"
    assert "body content" in body


def test_parse_frontmatter_rejects_missing_opening_delimiter() -> None:
    with pytest.raises(ValueError, match="frontmatter delimiter"):
        parse_frontmatter("kind: learner\n---\n")


def test_parse_frontmatter_rejects_unterminated_block() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        parse_frontmatter("---\nkind: learner\n")


def test_parse_frontmatter_rejects_malformed_line() -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_frontmatter("---\nno-colon-here\n---\n")


def test_brain_page_render_emits_both_sections() -> None:
    page = BrainPage(
        kind=PageKind.LEARNER,
        compiled_truth="This learner works best with primary sources.",
        timeline=[
            TimelineEntry(
                timestamp=datetime(2026, 4, 11, 14, 20, 0, tzinfo=UTC),
                kind="calibration_answer",
                text="correct on tier=meeting",
            ),
        ],
    )
    rendered = page.render()
    assert "# Compiled Truth" in rendered
    assert "# Timeline" in rendered
    assert "This learner works best" in rendered
    assert "calibration_answer" in rendered
    assert "correct on tier=meeting" in rendered


def test_brain_page_render_handles_empty_timeline() -> None:
    page = BrainPage(kind=PageKind.CONCEPT, compiled_truth="blank")
    rendered = page.render()
    assert "(no timeline entries)" in rendered


def test_brain_page_split_body_recovers_compiled_truth_and_timeline() -> None:
    page = BrainPage(
        kind=PageKind.SESSION,
        compiled_truth="Session summary: student re-taught twice.",
        timeline=[
            TimelineEntry(
                timestamp=datetime(2026, 4, 11, 14, 25, 0, tzinfo=UTC),
                kind="session_close",
                text="closed after 40 minutes",
            ),
        ],
    )
    rendered = page.render()
    _, body = parse_frontmatter(rendered)
    compiled, timeline = BrainPage.split_body(body)
    assert compiled == "Session summary: student re-taught twice."
    assert len(timeline) == 1
    assert timeline[0].kind == "session_close"
    assert timeline[0].text == "closed after 40 minutes"


def test_append_timeline_bumps_updated_at() -> None:
    page = BrainPage(kind=PageKind.LEARNER, compiled_truth="start")
    original = page.updated_at
    page.append_timeline(
        TimelineEntry(
            timestamp=datetime(2026, 4, 11, 14, 30, 0, tzinfo=UTC),
            kind="voluntary_question",
            text="asked about Reconstruction",
        )
    )
    assert len(page.timeline) == 1
    assert page.updated_at >= original


def test_render_frontmatter_rejects_unsupported_scalar() -> None:
    with pytest.raises(TypeError, match="unsupported frontmatter"):
        render_frontmatter({"tags": ["not", "allowed"]})
