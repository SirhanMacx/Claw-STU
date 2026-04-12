"""Tests for curriculum/sources.py PrimarySourceLibrary.

Covers the get-error path, contains(), ids(), and custom-source
construction that the existing test_topic.py does not exercise.
"""

from __future__ import annotations

import pytest

from clawstu.curriculum.sources import PrimarySource, PrimarySourceLibrary


def _custom_source() -> PrimarySource:
    return PrimarySource(
        id="test_src",
        title="Test Source",
        author="Author",
        year=2000,
        text="body text",
        citation="Test Citation",
    )


def test_get_known_source() -> None:
    lib = PrimarySourceLibrary()
    src = lib.get("declaration_preamble")
    assert src.id == "declaration_preamble"
    assert src.year == 1776


def test_get_unknown_source_raises() -> None:
    lib = PrimarySourceLibrary()
    with pytest.raises(KeyError, match="unknown primary source"):
        lib.get("does_not_exist")


def test_contains_true() -> None:
    lib = PrimarySourceLibrary()
    assert lib.contains("declaration_preamble") is True


def test_contains_false() -> None:
    lib = PrimarySourceLibrary()
    assert lib.contains("nonexistent") is False


def test_ids() -> None:
    lib = PrimarySourceLibrary()
    ids = lib.ids()
    assert "declaration_preamble" in ids
    assert isinstance(ids, tuple)


def test_custom_sources_override_seeds() -> None:
    custom = _custom_source()
    lib = PrimarySourceLibrary(sources=(custom,))
    assert lib.ids() == ("test_src",)
    assert lib.get("test_src").title == "Test Source"
    assert not lib.contains("declaration_preamble")
