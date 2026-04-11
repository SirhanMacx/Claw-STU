"""Tests that pyproject.toml ships with the right metadata.

These are cheap catch-the-obvious-mistake tests. They don't cover the
wheel build itself — that's what CI's `python -m build` step does.
They DO cover:

- the package name has PEP 503 normalized to `clawstu` (no dash)
- the build backend is hatchling
- the wheel target uses the in-tree clawstu/ package (no src: rewrite)
- the console script points at the real entry point we just created
- Python version + core dependencies survived the rename
- classifiers include the ones spec §4.10.1 calls out
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _load_pyproject() -> dict[str, Any]:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def _dep_name(raw: str) -> str:
    """Strip extras and version specifiers from a PEP 508 dep string.

    "uvicorn[standard]>=0.29,<1.0" -> "uvicorn"
    "typer>=0.12,<1.0"             -> "typer"
    """
    # Split on the first of [, >, <, =, !, ~, ;, or whitespace
    return re.split(r"[\[><=!~;\s]", raw, maxsplit=1)[0].strip()


def test_project_name_is_clawstu() -> None:
    pyproject = _load_pyproject()
    assert pyproject["project"]["name"] == "clawstu"


def test_build_backend_is_hatchling() -> None:
    pyproject = _load_pyproject()
    assert pyproject["build-system"]["build-backend"] == "hatchling.build"
    assert any(
        req.startswith("hatchling")
        for req in pyproject["build-system"]["requires"]
    )


def test_hatch_wheel_packages_contains_clawstu() -> None:
    """The wheel target must pick up the clawstu/ package in-tree.

    We use `packages = ["clawstu"]` (not a `sources` rewrite) because
    hatchling's editable install path does not support prefix
    rewrites — see the note in pyproject.toml from the Task 2 rename.
    """
    pyproject = _load_pyproject()
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert "packages" in wheel, "hatch wheel target missing 'packages' key"
    assert wheel["packages"] == ["clawstu"]


def test_console_script_points_at_clawstu_cli_main() -> None:
    pyproject = _load_pyproject()
    scripts = pyproject["project"]["scripts"]
    assert scripts["clawstu"] == "clawstu.cli:main"


def test_requires_python_is_3_11_or_higher() -> None:
    pyproject = _load_pyproject()
    assert pyproject["project"]["requires-python"] == ">=3.11"


def test_dependencies_include_all_runtime_essentials() -> None:
    pyproject = _load_pyproject()
    deps = pyproject["project"]["dependencies"]
    dep_names = {_dep_name(d) for d in deps}
    # Every dep that Phase 1 runtime code actually imports:
    expected = {
        "anthropic",
        "apscheduler",
        "fastapi",
        "httpx",
        "numpy",
        "onnxruntime",
        "openai",
        "pydantic",
        "tokenizers",
        "typer",
        "uvicorn",
    }
    missing = expected - dep_names
    assert not missing, f"pyproject.toml dependencies missing: {missing}"


def test_dev_dependencies_include_pytest_and_mypy() -> None:
    pyproject = _load_pyproject()
    dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
    dep_names = {_dep_name(d) for d in dev_deps}
    for required in ("pytest", "pytest-cov", "pytest-asyncio", "ruff", "mypy"):
        assert required in dep_names, f"dev deps missing {required}"


def test_license_is_mit() -> None:
    pyproject = _load_pyproject()
    license_value = pyproject["project"]["license"]
    # hatchling accepts either {"file": "LICENSE"}, {"text": "MIT"}, or a string.
    if isinstance(license_value, dict):
        # The repo ships with `license = { file = "LICENSE" }`.
        assert license_value.get("file") == "LICENSE"
    else:
        assert license_value in ("MIT", "MIT License")


def test_classifiers_include_spec_required_items() -> None:
    """Spec §4.10.1 requires specific trove classifiers for PyPI discovery."""
    pyproject = _load_pyproject()
    classifiers = pyproject["project"]["classifiers"]
    for required in (
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Framework :: FastAPI",
        "Intended Audience :: Education",
        "Topic :: Education",
        "Topic :: Education :: Computer Aided Instruction (CAI)",
    ):
        assert required in classifiers, f"classifiers missing: {required!r}"


def test_pytest_config_enforces_warnings_as_errors() -> None:
    """Defense in depth: if anyone relaxes filterwarnings, this fails."""
    pyproject = _load_pyproject()
    filterwarnings = pyproject["tool"]["pytest"]["ini_options"]["filterwarnings"]
    assert "error" in filterwarnings


def test_coverage_floor_is_80_or_higher() -> None:
    pyproject = _load_pyproject()
    fail_under = pyproject["tool"]["coverage"]["report"]["fail_under"]
    assert fail_under >= 80, (
        f"coverage floor dropped below 80%: got {fail_under}"
    )
