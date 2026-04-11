"""Profile portability: export and import.

The learner profile is owned by the student. That is not a marketing
claim — it's a technical contract. This module exists so that at any time
the student (or their guardian, for a minor) can take their profile and
leave. It is the escape hatch from lock-in.

JSON is the canonical format. It is human-readable, diff-able, and cannot
contain executable code.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.profile.model import LearnerProfile


def export_to_json(profile: LearnerProfile, *, indent: int = 2) -> str:
    """Serialize a learner profile to a JSON string."""
    return json.dumps(profile.to_dict(), indent=indent, sort_keys=True)


def import_from_json(raw: str) -> LearnerProfile:
    """Parse a learner profile from a JSON string.

    Raises `ValueError` if the input is not valid JSON or not a
    well-formed profile. We intentionally do not attempt to "recover"
    from a corrupted profile — silent recovery is how ghosts end up in
    student data.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"profile is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("profile JSON must be a top-level object")
    return LearnerProfile.from_dict(data)


def write_profile(profile: LearnerProfile, path: Path) -> None:
    """Write a profile to disk atomically.

    Uses a temp-file-and-rename pattern so a crash mid-write cannot leave
    a partially-written profile file behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(export_to_json(profile), encoding="utf-8")
    tmp_path.replace(path)


def read_profile(path: Path) -> LearnerProfile:
    """Read a profile from disk. Raises if the file does not exist or is
    not a valid profile."""
    if not path.exists():
        raise FileNotFoundError(f"no profile at {path}")
    return import_from_json(path.read_text(encoding="utf-8"))
