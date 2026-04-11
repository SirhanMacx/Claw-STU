"""Tests for src/curriculum/topic.py.

`Topic` is the small validated wrapper around a student-provided free-text
learning topic. It is referenced by the (future) live-content path that
lets a learner start a session on any subject, not just the deterministic
seed library. These tests cover:

- happy-path construction via `from_student_input`
- whitespace stripping
- length floor and ceiling
- slug normalization (spaces, punctuation, unicode, case)
- slug length cap
- rejection of inputs that sluggify to nothing
- explicit Domain tag propagation
- frozen-model semantics
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.curriculum.topic import Topic
from src.profile.model import Domain


def test_from_student_input_happy_path() -> None:
    topic = Topic.from_student_input("The French Revolution")
    assert topic.raw == "The French Revolution"
    assert topic.slug == "the-french-revolution"
    assert topic.domain is Domain.OTHER


def test_from_student_input_explicit_domain() -> None:
    topic = Topic.from_student_input(
        "Photosynthesis", domain=Domain.SCIENCE
    )
    assert topic.domain is Domain.SCIENCE
    assert topic.slug == "photosynthesis"


def test_from_student_input_strips_surrounding_whitespace() -> None:
    topic = Topic.from_student_input("   Industrial Revolution   ")
    assert topic.raw == "Industrial Revolution"
    assert topic.slug == "industrial-revolution"


def test_from_student_input_rejects_empty() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        Topic.from_student_input("")


def test_from_student_input_rejects_whitespace_only() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        Topic.from_student_input("   \t\n  ")


def test_from_student_input_rejects_too_long() -> None:
    with pytest.raises(ValueError, match="too long"):
        Topic.from_student_input("x" * 201)


def test_from_student_input_rejects_unsluggable() -> None:
    # Characters that _SLUG_RE strips entirely (emoji + punctuation)
    # leave no alphanumeric slug.
    with pytest.raises(ValueError, match="no sluggable content"):
        Topic.from_student_input("!?.?!")


def test_slug_collapses_punctuation_and_case() -> None:
    topic = Topic.from_student_input("What is MITOSIS?!")
    assert topic.slug == "what-is-mitosis"


def test_slug_collapses_consecutive_separators() -> None:
    topic = Topic.from_student_input("A --- B --- C")
    assert topic.slug == "a-b-c"


def test_slug_drops_leading_trailing_separators() -> None:
    topic = Topic.from_student_input("---hello---")
    assert topic.slug == "hello"


def test_slug_max_length_is_enforced() -> None:
    long_text = "hello " * 40  # ~240 chars of raw, but raw max is 200
    raw_text = long_text[:195]  # within raw cap
    topic = Topic.from_student_input(raw_text)
    assert len(topic.slug) <= 80


def test_direct_construction_requires_both_fields() -> None:
    # Pydantic validation: both raw and slug are required.
    with pytest.raises(ValidationError):
        Topic(raw="Hello")  # type: ignore[call-arg]


def test_direct_construction_rejects_too_short_raw() -> None:
    with pytest.raises(ValidationError):
        Topic(raw="a", slug="a")


def test_direct_construction_validator_strips_raw() -> None:
    # The `raw` field validator trims whitespace before the length check.
    topic = Topic(raw="  Algebra  ", slug="algebra")
    assert topic.raw == "Algebra"


def test_topic_is_frozen() -> None:
    topic = Topic.from_student_input("Cells")
    with pytest.raises(ValidationError):
        topic.raw = "something else"  # type: ignore[misc]


def test_round_trip_preserves_all_fields() -> None:
    original = Topic.from_student_input(
        "Haitian Revolution", domain=Domain.GLOBAL_HISTORY
    )
    dumped = original.model_dump()
    rebuilt = Topic(**dumped)
    assert rebuilt == original
    assert rebuilt.domain is Domain.GLOBAL_HISTORY
