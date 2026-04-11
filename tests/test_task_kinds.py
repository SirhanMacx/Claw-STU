"""Tests for the TaskKind enum."""
from __future__ import annotations

from clawstu.orchestrator.task_kinds import TaskKind


def test_task_kind_has_seven_members() -> None:
    # Seven task kinds per the design spec §4.2.2.
    assert len(TaskKind) == 7


def test_task_kind_values_are_snake_case_strings() -> None:
    for kind in TaskKind:
        assert isinstance(kind.value, str)
        assert kind.value == kind.value.lower()
        assert " " not in kind.value


def test_task_kind_members_stable_across_versions() -> None:
    # These values are the wire format for AppConfig serialization, so
    # renaming one is a breaking change. Snapshot them here.
    expected = {
        "socratic_dialogue",
        "block_generation",
        "check_generation",
        "rubric_evaluation",
        "pathway_planning",
        "content_classify",
        "dream_consolidation",
    }
    actual = {kind.value for kind in TaskKind}
    assert actual == expected


def test_task_kind_round_trips_through_string() -> None:
    for kind in TaskKind:
        assert TaskKind(kind.value) is kind
