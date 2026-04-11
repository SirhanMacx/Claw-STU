"""Enforce the Phase-1 import rename: no `from src.xxx` or `import src.xxx`.

After Task 2 of the Phase 1 plan, every import inside `clawstu/` and
`tests/` must reference the package as `clawstu`, not `src`. The
filesystem directory is `clawstu/` on disk; there is no `src/` directory
anymore, and any import that still says `from src.xxx` is a bug that
this test catches.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAWSTU = REPO_ROOT / "clawstu"
TESTS = REPO_ROOT / "tests"

_BAD_FROM = re.compile(r"^\s*from\s+src(\.|\s)")
_BAD_IMPORT = re.compile(r"^\s*import\s+src(\.|\s)")


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_src_imports_in_clawstu() -> None:
    offenders: list[str] = []
    for path in _python_files(CLAWSTU):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _BAD_FROM.match(line) or _BAD_IMPORT.match(line):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                )
    assert not offenders, (
        "Found `from src.xxx` / `import src.xxx` imports:\n  "
        + "\n  ".join(offenders)
    )


def test_no_src_imports_in_tests() -> None:
    offenders: list[str] = []
    for path in _python_files(TESTS):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _BAD_FROM.match(line) or _BAD_IMPORT.match(line):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                )
    assert not offenders, (
        "Found `from src.xxx` / `import src.xxx` imports:\n  "
        + "\n  ".join(offenders)
    )


def test_clawstu_directory_exists() -> None:
    """Sanity check: the package directory is `clawstu/`, not `src/`."""
    assert CLAWSTU.exists(), f"Expected {CLAWSTU} to exist"
    assert CLAWSTU.is_dir()
    assert (REPO_ROOT / "src").exists() is False, (
        "src/ should not exist after Task 2 — the on-disk rename was "
        "the whole point of the task. If you see src/ here, the rename "
        "was not committed."
    )
