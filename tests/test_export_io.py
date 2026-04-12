"""Tests for profile/export.py write_profile and read_profile functions.

These exercise the atomic-write and file-read paths that the
existing test_profile_model.py does not cover (it tests
export_to_json / import_from_json on strings, not files).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawstu.profile.export import read_profile, write_profile
from clawstu.profile.model import AgeBracket, LearnerProfile


def _make_profile() -> LearnerProfile:
    return LearnerProfile(
        learner_id="test-export",
        name="TestLearner",
        age_bracket=AgeBracket.MIDDLE,
    )


def test_write_profile_creates_file(tmp_path: Path) -> None:
    """write_profile should create the file and its parent directories."""
    out = tmp_path / "sub" / "nested" / "profile.json"
    write_profile(_make_profile(), out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert '"test-export"' in content


def test_write_profile_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    """The .tmp file should not be left behind after a successful write."""
    out = tmp_path / "profile.json"
    write_profile(_make_profile(), out)
    assert not out.with_suffix(".json.tmp").exists()


def test_read_profile_roundtrip(tmp_path: Path) -> None:
    """write + read should round-trip a profile."""
    out = tmp_path / "profile.json"
    original = _make_profile()
    write_profile(original, out)
    restored = read_profile(out)
    assert restored.learner_id == original.learner_id
    assert restored.age_bracket == original.age_bracket


def test_read_profile_missing_file(tmp_path: Path) -> None:
    """read_profile should raise FileNotFoundError for a missing path."""
    with pytest.raises(FileNotFoundError, match="no profile at"):
        read_profile(tmp_path / "nonexistent.json")


def test_read_profile_invalid_json(tmp_path: Path) -> None:
    """read_profile should raise ValueError for garbage content."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_profile(bad)
