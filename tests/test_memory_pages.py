"""Brain page base class, frontmatter parser, and timeline tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clawstu.memory.pages import (
    BrainPage,
    ConceptPage,
    LearnerPage,
    MisconceptionPage,
    PageKind,
    SessionPage,
    SourcePage,
    TimelineEntry,
    TopicPage,
    parse_frontmatter,
    render_frontmatter,
)

# -- base-class behavior ---------------------------------------------


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


# -- LearnerPage -----------------------------------------------------


def test_learner_page_round_trip() -> None:
    original = LearnerPage(
        learner_id="test-learner",
        compiled_truth="Visual learner; avoid dense text blocks.",
        timeline=[
            TimelineEntry(
                timestamp=datetime(2026, 4, 11, 14, 20, 0, tzinfo=UTC),
                kind="session_close",
                text="40 minutes, 3 blocks, 1 reteach",
            ),
        ],
    )
    parsed = LearnerPage.parse(original.render())
    assert parsed.learner_id == "test-learner"
    assert parsed.compiled_truth == "Visual learner; avoid dense text blocks."
    assert len(parsed.timeline) == 1
    assert parsed.timeline[0].kind == "session_close"


def test_learner_page_parse_rejects_wrong_kind() -> None:
    page = ConceptPage(
        learner_id="l1", concept_id="civil_war", compiled_truth="x"
    )
    with pytest.raises(ValueError, match="expected kind=learner"):
        LearnerPage.parse(page.render())


# -- ConceptPage -----------------------------------------------------


def test_concept_page_round_trip() -> None:
    original = ConceptPage(
        learner_id="test-learner",
        concept_id="civil_war",
        compiled_truth="Student confident on causes, shaky on outcomes.",
    )
    rendered = original.render()
    assert "concept_id: civil_war" in rendered
    parsed = ConceptPage.parse(rendered)
    assert parsed.learner_id == "test-learner"
    assert parsed.concept_id == "civil_war"


# -- SessionPage -----------------------------------------------------


def test_session_page_round_trip() -> None:
    original = SessionPage(
        session_id="sess-001",
        learner_id="test-learner",
        compiled_truth="Covered Reconstruction; 2 blocks; 0 reteaches.",
    )
    parsed = SessionPage.parse(original.render())
    assert parsed.session_id == "sess-001"
    assert parsed.learner_id == "test-learner"


# -- SourcePage ------------------------------------------------------


def test_source_page_round_trip_with_all_fields() -> None:
    original = SourcePage(
        source_id="emancipation-proclamation",
        title="Emancipation Proclamation",
        attribution="Abraham Lincoln, 1863",
        age_bracket="late_high",
        compiled_truth="Primary source. Use for causation discussion.",
    )
    rendered = original.render()
    assert "title: Emancipation Proclamation" in rendered
    assert "attribution: Abraham Lincoln, 1863" in rendered
    parsed = SourcePage.parse(rendered)
    assert parsed.source_id == "emancipation-proclamation"
    assert parsed.title == "Emancipation Proclamation"
    assert parsed.attribution == "Abraham Lincoln, 1863"
    assert parsed.age_bracket == "late_high"


# -- MisconceptionPage -----------------------------------------------


def test_misconception_page_round_trip_preserves_occurrences() -> None:
    original = MisconceptionPage(
        learner_id="test-learner",
        misconception_id="civil_war_states_rights",
        concept_id="civil_war",
        occurrences=3,
        compiled_truth="Student believes the war was fought over states' rights alone.",
    )
    parsed = MisconceptionPage.parse(original.render())
    assert parsed.occurrences == 3
    assert parsed.misconception_id == "civil_war_states_rights"
    assert parsed.concept_id == "civil_war"


# -- TopicPage -------------------------------------------------------


def test_topic_page_round_trip() -> None:
    original = TopicPage(
        learner_id="test-learner",
        topic_id="reform_movements",
        compiled_truth="Groups abolition, suffrage, labor, temperance.",
    )
    parsed = TopicPage.parse(original.render())
    assert parsed.topic_id == "reform_movements"
    assert parsed.learner_id == "test-learner"


# -- Cross-type kind enforcement --------------------------------------


def test_every_page_type_enforces_its_kind_on_parse() -> None:
    learner = LearnerPage(learner_id="l1", compiled_truth="x")
    concept = ConceptPage(learner_id="l1", concept_id="c1", compiled_truth="x")
    session = SessionPage(
        session_id="s1", learner_id="l1", compiled_truth="x"
    )

    with pytest.raises(ValueError, match="expected kind=concept"):
        ConceptPage.parse(learner.render())
    with pytest.raises(ValueError, match="expected kind=session"):
        SessionPage.parse(concept.render())
    with pytest.raises(ValueError, match="expected kind=learner"):
        LearnerPage.parse(session.render())
