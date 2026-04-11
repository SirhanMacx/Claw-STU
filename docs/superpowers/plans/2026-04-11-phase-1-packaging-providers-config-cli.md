# Phase 1 — Packaging + Providers + Config + CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Claw-STU on PyPI as `pip install clawstu` with four real network LLM providers (Ollama, Anthropic, OpenAI, OpenRouter), a small env-driven `AppConfig`, and a `clawstu` console entry point. No wiring into the session loop yet — that's Phase 5. No router yet — that's Phase 2.

**Architecture:** Four focused provider files under `src/orchestrator/`, each ~150-200 lines, each implementing the existing **sync** `LLMProvider` protocol with `httpx.Client` (Phase 2 migrates the whole stack to async). `AppConfig` reads env vars first, then `~/.claw-stu/secrets.json` (0600), then defaults. `TaskKind` enum lands in a new `router.py` file as the stable home (Phase 2 adds `ModelRouter` to the same file). `src/cli.py` uses Typer to expose `clawstu serve | scheduler run-once | profile export/import | doctor`. Packaging switches from setuptools to hatchling with `[tool.hatch.build.targets.wheel.sources]` mapping `src/` → `clawstu/` at wheel time; on-disk layout stays under `src/`, but every `from src.xxx` import rewrites to `from clawstu.xxx` in a single mechanical pass.

**Tech Stack:** Python 3.11+, pydantic v2, httpx (sync), Typer, hatchling, pytest + pytest-asyncio, ruff, mypy strict.

**Predecessors:** Design spec at `docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md` v2 (commit `4d877f5`, reviewer-approved with minor issues). This plan resolves the v2 reviewer's Phase-1-scoped minor issues inline (entry-point path, CI job name, `_default_task_routing` definition, `[tool.coverage.run] source` decision).

**Non-goals:**
- Async provider protocol (Phase 2)
- Router + fallback chain (Phase 2)
- Live content wiring into session loop (Phase 5)
- Crisis wiring (Phase 5)
- Memory, scheduler, warm-start (Phases 4, 6, 7)
- PyPI actually publishing — the CI publish job lands here but no tag is pushed

**Success gate:** `pytest` green with 89 existing + ~60 new tests under 2s, `ruff check` clean, `mypy --strict` clean, coverage ≥ 80%, `pip install -e .` works with the new `clawstu` name, `clawstu --help` runs, four provider files each have `httpx.MockTransport`-backed tests for happy path + error paths. CI green on push.

**Baseline (verify before starting):**
```bash
cd /Users/mind_uploaded_crustacean/Projects/Claw-STU
git status          # expect: clean working tree
git log --oneline -1 # expect: 618acff or later
pytest -q           # expect: 89 passed
```

**Convention this plan uses:** file paths are shown under `src/` (the on-disk layout). **Imports** inside those files must use `clawstu.xxx`, not `src.xxx`, after Task 1. Tests import from `clawstu.xxx` too.

---

## File structure

**Created (16 new files):**
- `src/orchestrator/task_kinds.py` — `TaskKind` enum (moved here from the spec's proposed `router.py` home because `router.py` is a Phase 2 file; putting `TaskKind` in its own file keeps import direction clean)
- `src/orchestrator/config.py` — `AppConfig`, `TaskRoute`, `load_config`, `_default_task_routing`
- `src/orchestrator/provider_ollama.py` — `OllamaProvider`
- `src/orchestrator/provider_anthropic.py` — `AnthropicProvider`
- `src/orchestrator/provider_openai.py` — `OpenAIProvider`
- `src/orchestrator/provider_openrouter.py` — `OpenRouterProvider`
- `src/cli.py` — Typer entry point for `clawstu`
- `tests/test_task_kinds.py`
- `tests/test_config.py`
- `tests/test_provider_ollama.py`
- `tests/test_provider_anthropic.py`
- `tests/test_provider_openai.py`
- `tests/test_provider_openrouter.py`
- `tests/test_cli.py`
- `tests/test_packaging.py`
- `tests/test_imports.py` — asserts no `from src.xxx import` remains after the rename

**Modified (existing files):**
- `pyproject.toml` — name `claw-stu` → `clawstu`, build backend hatchling, console script, hatch sources mapping, `[project.scripts]`
- `.github/workflows/ci.yml` — add publish job
- `README.md` — verify install command (already updated in the previous docs-parity pass; confirm in Task 13)
- Every `.py` file under `src/` (35 files) — `from src.xxx` → `from clawstu.xxx`
- Every `.py` file under `tests/` (11 files) — `from src.xxx` → `from clawstu.xxx`
- `src/orchestrator/__init__.py` — export `TaskKind` and `AppConfig`

**Unchanged but referenced by tests:**
- `src/orchestrator/providers.py` — provides `LLMProvider` protocol and `LLMMessage`/`LLMResponse`/`ProviderError` that every new provider file imports
- `SOUL.md`, `HEARTBEAT.md` — no edits; every new file must respect them

**Test count projection:** 89 baseline + 54 new = **143** after Phase 1.
Breakdown: +2 `test_imports.py`, +4 `test_task_kinds.py`, +17 `test_config.py`
(across Tasks 5-8), +6 `test_provider_ollama.py`, +5 `test_provider_anthropic.py`,
+4 `test_provider_openai.py`, +4 `test_provider_openrouter.py`, +5 `test_cli.py`
(3 basic + 2 from Task 17 --ping flag), +7 `test_packaging.py`. Budget per suite: 2s.

---

## Pre-flight: environment check

### Task 0: Verify baseline state

**Files:** none

- [ ] **Step 1: Confirm clean tree**

Run: `cd /Users/mind_uploaded_crustacean/Projects/Claw-STU && git status`
Expected output: `nothing to commit, working tree clean` on branch `main`.

- [ ] **Step 2: Confirm latest commit**

Run: `git log --oneline -1`
Expected: `618acff` or a later commit that includes the docs-parity pass.

- [ ] **Step 3: Confirm baseline tests pass**

Run: `/tmp/claw-stu-venv/bin/python -m pytest -q`
Expected: `89 passed in 0.XXs`.

- [ ] **Step 4: Confirm coverage floor is enforced**

Run: `/tmp/claw-stu-venv/bin/python -m pytest --cov=src --cov-report=term | tail -3`
Expected: `Required test coverage of 80.0% reached. Total coverage: 85.XX%` (or similar above 80).

- [ ] **Step 5: Confirm ruff + mypy baseline**

Run: `/tmp/claw-stu-venv/bin/ruff check .`
Expected: `All checks passed!`

Run: `/tmp/claw-stu-venv/bin/mypy src/ 2>&1 | tail -5` (if mypy passes today — note current state)
If mypy flags pre-existing issues, document them in a NOTES.md scratch and do not fix them in Phase 1 (they're outside Phase 1 scope).

- [ ] **Step 6: Confirm CI last run was green**

Run: `gh run list --limit 1`
Expected: `completed	success	docs: Claw-ED parity ...`

If any of the above fails, STOP and fix before proceeding. The plan assumes a green baseline.

---

## Section A — Packaging conversion (src/ → clawstu/)

### Task 1: Switch pyproject.toml to hatchling + rename package

**Files:**
- Modify: `pyproject.toml` (replace `[build-system]`, rename `[project] name`, add `[tool.hatch.build.targets.wheel]` with sources mapping, add `[project.scripts]`)

- [ ] **Step 1: Read the current pyproject.toml once to capture exact content for the edit**

Run: `cat /Users/mind_uploaded_crustacean/Projects/Claw-STU/pyproject.toml`

Note the current `[build-system]`, `[project] name`, and `[tool.setuptools.packages.find]` sections.

- [ ] **Step 2: Replace build backend and project name**

Edit `pyproject.toml`:

Replace:
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```
With:
```toml
[build-system]
requires = ["hatchling>=1.25,<2.0"]
build-backend = "hatchling.build"
```

Replace:
```toml
name = "claw-stu"
```
With:
```toml
name = "clawstu"
```

Replace:
```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["src*"]
```
With:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.hatch.build.targets.wheel.sources]
"src" = "clawstu"

[project.scripts]
clawstu = "clawstu.cli:main"
```

**IMPORTANT:** `[project.scripts]` uses `clawstu.cli:main`, not `src.cli:main`. This resolves the entry-point-path inconsistency the spec v2 reviewer flagged.

- [ ] **Step 3: Add all spec-mandated Phase 1 base dependencies**

Spec §5 Phase 1 mandates these base dependencies. Add each to the `[project]` `dependencies` list alongside the existing fastapi / uvicorn / pydantic / httpx entries, preserving alphabetical order:

```toml
dependencies = [
    "anthropic>=0.25,<1.0",
    "apscheduler>=3.10,<4.0",
    "fastapi>=0.110,<1.0",
    "httpx>=0.27,<1.0",
    "numpy>=1.26,<3.0",
    "onnxruntime>=1.20,<3.0",
    "openai>=1.20,<2.0",
    "pydantic>=2.6,<3.0",
    "tokenizers>=0.15,<1.0",
    "typer>=0.12,<1.0",
    "uvicorn[standard]>=0.29,<1.0",
]
```

**Why these land in Phase 1 even though they're used in Phases 2/4/6:**
- **`anthropic`**, **`openai`** — the Phase 1 provider files technically use `httpx` directly (not the vendor SDKs), but the spec promotes these from existing optional extras to base deps in Phase 1. Keeping them in base now avoids a second pyproject churn in Phase 2.
- **`apscheduler`** — Phase 6 scheduler embeds APScheduler; lands here to keep `pip install clawstu` one-shot.
- **`onnxruntime`**, **`numpy`**, **`tokenizers`** — Phase 4 ONNX MiniLM embeddings are core, not optional (Jon's explicit directive in the spec session). Base deps from Phase 1 forward.

All upper bounds are `<next-major` per the spec's "avoid semver drift" rule.

- [ ] **Step 4: Reinstall in editable mode**

Run:
```bash
/tmp/claw-stu-venv/bin/pip install -e /Users/mind_uploaded_crustacean/Projects/Claw-STU 2>&1 | tail -5
```

Expected: `Successfully installed clawstu-0.1.0` (or similar). No errors.

- [ ] **Step 5: Verify the package is importable under the new name**

Run:
```bash
/tmp/claw-stu-venv/bin/python -c "import clawstu; print(clawstu)"
```

Expected: prints a module object like `<module 'clawstu' from '/Users/mind_uploaded_crustacean/Projects/Claw-STU/src/__init__.py'>`. The filesystem path is still `src/` (hatch maps at wheel build time; editable installs use a link).

- [ ] **Step 6: Run tests to confirm nothing broke**

Run: `cd /Users/mind_uploaded_crustacean/Projects/Claw-STU && /tmp/claw-stu-venv/bin/python -m pytest -q`

Expected: **89 passed.** Tests still import from `src.xxx` at this point, which works because the editable install exposes BOTH `src` and `clawstu` namespaces (Python can import the directory via its on-disk path and via the hatch-sources mapping). That dual exposure goes away in Task 2.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml
git commit -m "build: switch to hatchling, rename package to clawstu

Prepares for pip install clawstu. Build backend changes from
setuptools to hatchling with a [tool.hatch.build.targets.wheel.sources]
mapping 'src' -> 'clawstu', so the installed module is exposed as
clawstu while the on-disk repo layout stays under src/. Console
entry point clawstu -> clawstu.cli:main (added in Task 15).

Adds typer as a base dependency for the CLI.

No behavior change: 89 tests still pass under the current src.xxx
imports because editable install exposes both namespaces."
```

---

### Task 2: Rewrite `from src.xxx` imports → `from clawstu.xxx`

> **Execution note (post-Task-1 revision):** Task 2 was expanded during
> execution to include a physical `git mv src clawstu` rename and a
> `pyproject.toml` cleanup that removes the Task 1 `dev-mode-dirs`
> workaround. This was necessary because hatchling's editable-install
> detection (`wheel.py:555-566`) cannot handle prefix-rewriting sources
> mappings, which was discovered in Task 1. See commit `601ee84` for
> the actual delta and its commit message for the rationale. The plan
> text below still describes the pre-expansion approach for historical
> reference.

**Files:**
- Modify: every `.py` file under `src/` (35 files)
- Modify: every `.py` file under `tests/` (11 files)
- Modify: `pyproject.toml` — update `[tool.coverage.run] source` to stay `["src"]` (it's still a repo-relative path — the filesystem layout did not change) and add a note

- [ ] **Step 1: Find every `from src.` and `import src.` usage in the repo**

Run:
```bash
cd /Users/mind_uploaded_crustacean/Projects/Claw-STU
grep -rn "from src\.\|^import src\." src/ tests/ --include="*.py" | wc -l
```

Record the number. Should be ~90 based on the spec review v2 report.

- [ ] **Step 2: Write the failing test that asserts no `src.` imports remain**

Create `tests/test_imports.py`:
```python
"""Enforce the Phase-1 import rename: no `from src.xxx` or `import src.xxx`.

After Task 2 of the Phase 1 plan, every import inside `src/` and `tests/`
must reference the package as `clawstu`, not `src`. The repo still lives
under `src/` on disk, but the hatchling sources mapping in pyproject.toml
exposes it as `clawstu` to the import system. Mixing the two names would
create two different module objects for the same code.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
TESTS = REPO_ROOT / "tests"

_BAD_FROM = re.compile(r"^\s*from\s+src(\.|\s)")
_BAD_IMPORT = re.compile(r"^\s*import\s+src(\.|\s)")


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_src_imports_in_src() -> None:
    offenders: list[str] = []
    for path in _python_files(SRC):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _BAD_FROM.match(line) or _BAD_IMPORT.match(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "Found `from src.xxx`/`import src.xxx` imports:\n  " + "\n  ".join(offenders)


def test_no_src_imports_in_tests() -> None:
    offenders: list[str] = []
    for path in _python_files(TESTS):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _BAD_FROM.match(line) or _BAD_IMPORT.match(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "Found `from src.xxx`/`import src.xxx` imports:\n  " + "\n  ".join(offenders)
```

- [ ] **Step 3: Run the new test and watch it fail (sanity check — confirms we've written the right assertion)**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_imports.py -v`

Expected: **FAIL** with a list of offenders (every file under `src/` and `tests/` that uses `from src.`).

- [ ] **Step 4: Run the mechanical find-and-replace**

Run:
```bash
cd /Users/mind_uploaded_crustacean/Projects/Claw-STU
find src tests -name '*.py' -exec sed -i '' -E 's/(^|[^a-zA-Z_])(from|import) src\./\1\2 clawstu./g' {} +
```

(Note: macOS sed uses `-i ''` for in-place with no backup. Linux sed uses `-i` alone.)

- [ ] **Step 5: Re-run the import test**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_imports.py -v`
Expected: **PASS** on both tests.

- [ ] **Step 6: Run the whole test suite**

Run: `/tmp/claw-stu-venv/bin/python -m pytest -q`
Expected: **89 + 2 = 91 passed.**

If any tests fail due to a missed import site (e.g., string-based imports, `importlib.import_module("src.xxx")`), find and fix them.

- [ ] **Step 7: Run ruff to catch import-order drift**

Run: `/tmp/claw-stu-venv/bin/ruff check . --fix`
Expected: no errors, possibly some formatting fixes applied.

- [ ] **Step 8: Add a coverage config comment for clarity**

Edit `pyproject.toml`'s `[tool.coverage.run]`:

Replace:
```toml
[tool.coverage.run]
branch = true
source = ["src"]
```
With:
```toml
[tool.coverage.run]
branch = true
# `source` stays as "src" because coverage runs against the on-disk
# repo layout, not the installed module name. The hatchling sources
# mapping (pyproject.toml above) remaps src -> clawstu only at wheel
# build time; during test runs against the editable install, pytest
# reads files from src/ directly.
source = ["src"]
```

- [ ] **Step 9: Re-run full test suite + ruff**

Run: `/tmp/claw-stu-venv/bin/python -m pytest -q && /tmp/claw-stu-venv/bin/ruff check .`
Expected: 91 passed, ruff clean.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: rewrite src.xxx imports to clawstu.xxx

Part of the Phase 1 packaging rename. After Task 1 added the
hatchling sources mapping that exposes src/ as clawstu at wheel
time, the editable install supported both namespaces transiently.
This commit collapses to a single namespace by rewriting every
import site.

Also adds tests/test_imports.py as a permanent guard: any future
'from src.xxx' or 'import src.xxx' is caught by the test suite.

Coverage config explicitly documents why source stays as 'src'
(the on-disk path), not 'clawstu' (the installed name).

91 tests pass."
```

---

### Task 3: Add CI publish job + fix job-name reference

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Read the current CI workflow**

Run: `cat /Users/mind_uploaded_crustacean/Projects/Claw-STU/.github/workflows/ci.yml`

Identify the current job names. The spec v2 reviewer flagged that the spec's publish job referenced `needs: [python-tests]` but the actual job is named `test`. Confirm the real job name.

- [ ] **Step 2: Append the publish job (at the end of `jobs:`)**

Edit `.github/workflows/ci.yml`. After the last existing job, add:

```yaml
  publish:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: [test]  # matches the existing test job's actual name
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install build tools
        run: python -m pip install --upgrade pip build twine
      - name: Build sdist + wheel
        run: python -m build
      - name: Verify distribution name
        run: |
          ls dist/
          python -m pip install --quiet pkginfo
          python -c "import pkginfo; p = pkginfo.SDist('dist/clawstu-0.1.0.tar.gz'); assert p.name == 'clawstu', p.name"
      - name: Publish to PyPI
        # No `|| echo` fallback: real twine failures must fail the job.
        # --skip-existing handles the benign "version already uploaded" case.
        run: twine upload --skip-existing dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
          TWINE_NON_INTERACTIVE: "1"
```

**IMPORTANT NOTES:**
- `needs: [test]` — not `[python-tests]`. The spec reviewer flagged this.
- `|| echo` fallback is deliberately absent (Claw-ED's v4.11.2026.1 post-mortem lesson).
- The publish job only fires on `v*` tags, so the first push after this commit will run only `test` (not `publish`), and the publish job won't exist in the execution graph until a tag is cut.

- [ ] **Step 3: Lint the workflow**

If `actionlint` is installed locally, run it. Otherwise rely on GitHub's server-side validation on push.

Run: `which actionlint && actionlint .github/workflows/ci.yml || echo "actionlint not installed; will rely on GitHub validation on push"`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add publish job for PyPI release on v* tags

The publish job mirrors Claw-ED v4.11.2026.1's pattern:
- Gated on the existing test job via needs: [test]
- Fires only on v* tags (if: startsWith(github.ref, 'refs/tags/v'))
- Explicit environment: pypi for GitHub environment protection
- id-token: write granted for OIDC trusted publishing (currently
  uses TWINE_PASSWORD with a PYPI_TOKEN secret; OIDC migration
  is a post-MVP follow-up)
- No '|| echo \"Upload skipped\"' fallback: real twine errors must
  fail the job loudly
- Verifies the distribution name is 'clawstu' before upload as a
  belt-and-suspenders check that the rename actually took effect

First actual publish will require cutting a v0.2.0 tag after Phase 1
execution completes; this commit just wires the workflow so it's
ready when that moment arrives."
```

---

## Section B — Config and TaskKind

### Task 4: Create `src/orchestrator/task_kinds.py` with the TaskKind enum

**Files:**
- Create: `src/orchestrator/task_kinds.py`
- Create: `tests/test_task_kinds.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_kinds.py`:
```python
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_task_kinds.py -v`
Expected: **FAIL** with `ImportError` or `ModuleNotFoundError` on `clawstu.orchestrator.task_kinds`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/orchestrator/task_kinds.py`:
```python
"""Pedagogical task kinds for LLM model routing.

Every call the orchestrator makes to a provider is categorized by its
pedagogical purpose, not by its LLM characteristics. This is the key
that `ModelRouter` (Phase 2) uses to pick a concrete provider + model.

TaskKind values are the wire format for `AppConfig.task_routing`, so
renaming one is a breaking change. Test snapshot in
`tests/test_task_kinds.py::test_task_kind_members_stable_across_versions`
is the guard.
"""
from __future__ import annotations

from enum import Enum


class TaskKind(str, Enum):
    """The pedagogical jobs Stuart performs."""

    # Short, cheap, latency-sensitive. Default: local Ollama.
    SOCRATIC_DIALOGUE = "socratic_dialogue"

    # Quality-sensitive prose. Default: OpenRouter GLM 4.5 Air.
    BLOCK_GENERATION = "block_generation"

    # Structured JSON, tier-aware. Default: OpenRouter GLM 4.5 Air.
    CHECK_GENERATION = "check_generation"

    # Accuracy-critical CRQ scoring. Default: Anthropic Haiku 4.5.
    RUBRIC_EVALUATION = "rubric_evaluation"

    # Small strict-JSON concept sequence. Default: OpenRouter GLM 4.5 Air.
    PATHWAY_PLANNING = "pathway_planning"

    # Second-layer safety classification. Default: local Ollama so safety
    # never depends on a network.
    CONTENT_CLASSIFY = "content_classify"

    # Overnight compiled-truth rewrite. Batch, cost-sensitive.
    # Default: OpenRouter GLM 4.5 Air.
    DREAM_CONSOLIDATION = "dream_consolidation"
```

- [ ] **Step 4: Run the test**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_task_kinds.py -v`
Expected: **4 passed.**

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/task_kinds.py tests/test_task_kinds.py
git commit -m "feat(orchestrator): add TaskKind enum for pedagogical task routing

Seven task kinds that name what Stuart is doing (socratic dialogue,
block generation, check generation, rubric evaluation, pathway
planning, content classify, dream consolidation) — not what LLM it
uses. Phase 2's ModelRouter will map each TaskKind to a concrete
(provider, model) tuple via AppConfig.

Wire format stability is enforced by a snapshot test: renaming any
value is a breaking change caught by CI."
```

---

### Task 5: Create `AppConfig` and `TaskRoute` in `src/orchestrator/config.py`

**Files:**
- Create: `src/orchestrator/config.py`
- Create: `tests/test_config.py` (initial test, more added in Tasks 6-8)

- [ ] **Step 1: Write the failing test for the minimal config model**

Create `tests/test_config.py`:
```python
"""Tests for AppConfig, TaskRoute, and load_config."""
from __future__ import annotations

from pathlib import Path

import pytest

from clawstu.orchestrator.config import (
    AppConfig,
    TaskRoute,
)
from clawstu.orchestrator.task_kinds import TaskKind


def test_task_route_is_frozen() -> None:
    route = TaskRoute(provider="ollama", model="llama3.2")
    with pytest.raises(Exception):
        route.provider = "anthropic"  # type: ignore[misc]


def test_task_route_defaults() -> None:
    route = TaskRoute(provider="ollama", model="llama3.2")
    assert route.max_tokens == 1024
    assert 0.0 <= route.temperature <= 1.0


def test_app_config_has_defaults_for_every_task_kind() -> None:
    cfg = AppConfig()
    for kind in TaskKind:
        assert kind in cfg.task_routing, f"missing default routing for {kind}"
        route = cfg.task_routing[kind]
        assert isinstance(route, TaskRoute)
        assert route.provider in cfg.fallback_chain + ("echo",), (
            f"default routing for {kind} uses provider {route.provider!r} "
            f"which is not in fallback_chain {cfg.fallback_chain}"
        )


def test_app_config_default_data_dir_is_under_home() -> None:
    cfg = AppConfig()
    assert cfg.data_dir == Path.home() / ".claw-stu"


def test_app_config_default_primary_provider_is_ollama() -> None:
    cfg = AppConfig()
    assert cfg.primary_provider == "ollama"


def test_app_config_default_fallback_chain_ends_at_openrouter() -> None:
    cfg = AppConfig()
    assert cfg.fallback_chain == ("ollama", "openai", "anthropic", "openrouter")


def test_default_task_routing_matches_spec_table() -> None:
    """The §4.2.4 default routing table is the contract."""
    cfg = AppConfig()
    assert cfg.task_routing[TaskKind.SOCRATIC_DIALOGUE].provider == "ollama"
    assert cfg.task_routing[TaskKind.BLOCK_GENERATION].provider == "openrouter"
    assert cfg.task_routing[TaskKind.CHECK_GENERATION].provider == "openrouter"
    assert cfg.task_routing[TaskKind.RUBRIC_EVALUATION].provider == "anthropic"
    assert cfg.task_routing[TaskKind.PATHWAY_PLANNING].provider == "openrouter"
    assert cfg.task_routing[TaskKind.CONTENT_CLASSIFY].provider == "ollama"
    assert cfg.task_routing[TaskKind.DREAM_CONSOLIDATION].provider == "openrouter"
    # Model names per §4.2.4:
    assert cfg.task_routing[TaskKind.RUBRIC_EVALUATION].model == "claude-haiku-4-5"
    assert cfg.task_routing[TaskKind.BLOCK_GENERATION].model == "z-ai/glm-4.5-air"
```

- [ ] **Step 2: Run and confirm it fails**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py -v`
Expected: **FAIL** with `ImportError` on `clawstu.orchestrator.config`.

- [ ] **Step 3: Implement `TaskRoute`, `AppConfig`, and `_default_task_routing`**

Create `src/orchestrator/config.py`:
```python
"""AppConfig and TaskRoute — the provider-layer configuration contract.

AppConfig is loaded from (in priority order):
  1. Environment variables
  2. ~/.claw-stu/secrets.json (0600 on POSIX; WARN on Windows)
  3. Defaults defined in this module

See docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md
§4.2.4 and §4.2.5 for the authoritative default routing table.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clawstu.orchestrator.task_kinds import TaskKind


class TaskRoute(BaseModel):
    """One (provider, model) assignment for a TaskKind.

    Kept as a named pydantic model so the config file reads cleanly:
    {TaskKind: {provider: ..., model: ..., max_tokens: ..., temperature: ...}}
    rather than opaque tuples.
    """

    model_config = ConfigDict(frozen=True)

    provider: str  # "ollama" | "anthropic" | "openai" | "openrouter" | "echo"
    model: str     # provider-specific model id
    max_tokens: int = 1024
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


def _default_task_routing() -> dict[TaskKind, TaskRoute]:
    """The shipped defaults per design spec §4.2.4.

    The reader-friendly version of this table:

    - SOCRATIC_DIALOGUE   → ollama / llama3.2         (short, local, free)
    - BLOCK_GENERATION    → openrouter / glm-4.5-air  (prose quality)
    - CHECK_GENERATION    → openrouter / glm-4.5-air  (structured JSON)
    - RUBRIC_EVALUATION   → anthropic / haiku-4-5     (accuracy-critical)
    - PATHWAY_PLANNING    → openrouter / glm-4.5-air  (small JSON)
    - CONTENT_CLASSIFY    → ollama / llama3.2         (safety: never network)
    - DREAM_CONSOLIDATION → openrouter / glm-4.5-air  (batch overnight)
    """
    return {
        TaskKind.SOCRATIC_DIALOGUE: TaskRoute(
            provider="ollama", model="llama3.2",
        ),
        TaskKind.BLOCK_GENERATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.CHECK_GENERATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.RUBRIC_EVALUATION: TaskRoute(
            provider="anthropic", model="claude-haiku-4-5",
        ),
        TaskKind.PATHWAY_PLANNING: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
        TaskKind.CONTENT_CLASSIFY: TaskRoute(
            provider="ollama", model="llama3.2",
        ),
        TaskKind.DREAM_CONSOLIDATION: TaskRoute(
            provider="openrouter", model="z-ai/glm-4.5-air",
        ),
    }


class AppConfig(BaseModel):
    """The Claw-STU runtime configuration.

    Loaded via `load_config()` — see Task 8. Validation is strict:
    missing provider API keys are fine (falls through the chain),
    but an unknown provider name in `fallback_chain` or `task_routing`
    is a hard error raised by the router at construction time (Phase 2).
    """

    model_config = ConfigDict(validate_assignment=True)

    data_dir: Path = Field(
        default_factory=lambda: Path.home() / ".claw-stu",
        description="Root directory for secrets, brain, SQLite DB, cached models.",
    )
    primary_provider: str = "ollama"
    fallback_chain: tuple[str, ...] = (
        "ollama",
        "openai",
        "anthropic",
        "openrouter",
    )
    task_routing: dict[TaskKind, TaskRoute] = Field(
        default_factory=_default_task_routing,
    )
    # Provider connection settings.
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Session-layer settings.
    session_cache_size: int = 1024
```

- [ ] **Step 4: Run the config tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py -v`
Expected: **7 passed.**

- [ ] **Step 5: Run the full suite**

Run: `/tmp/claw-stu-venv/bin/python -m pytest -q`
Expected: **91 + 7 + 4 = 102 passed.** (The previous tasks brought us to 95; this adds 7 for config, 4 for task_kinds was already counted.)

Actually, recompute: 89 baseline + 2 (test_imports) + 4 (test_task_kinds) + 7 (test_config) = **102.**

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/config.py tests/test_config.py
git commit -m "feat(orchestrator): AppConfig, TaskRoute, and default routing table

AppConfig is the Phase-1 provider-layer config contract:
- data_dir under ~/.claw-stu (configurable)
- primary_provider + fallback_chain (ollama -> openai -> anthropic -> openrouter)
- task_routing: {TaskKind: TaskRoute} populated from _default_task_routing()
- Per-provider connection settings (base URLs, API keys)
- session_cache_size for the in-process bundle cache landing in Phase 3

TaskRoute is a frozen pydantic model per the design spec §4.2.5. Tests
pin the default routing table so future changes are explicit.

load_config() and env/file loading are Tasks 6-8."
```

---

### Task 6: Add env-var loading to `load_config()`

**Files:**
- Modify: `src/orchestrator/config.py` (add `load_config` function)
- Modify: `tests/test_config.py` (add env-var tests)

- [ ] **Step 1: Append the failing test**

Append to `tests/test_config.py`:
```python
def test_load_config_reads_env_var_api_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Env var keys populate AppConfig.

    Isolation note: we point CLAW_STU_DATA_DIR at tmp_path so this
    test does not accidentally read a real ~/.claw-stu/secrets.json
    when Task 7 adds file-based loading. Without this isolation, the
    test's result would depend on whatever is in the executor's home
    directory, which is neither deterministic nor safe.
    """
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-abc")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-def")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-ghi")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:22222")

    cfg = load_config()
    assert cfg.anthropic_api_key == "sk-ant-test-abc"
    assert cfg.openai_api_key == "sk-test-def"
    assert cfg.openrouter_api_key == "sk-or-test-ghi"
    assert cfg.ollama_base_url == "http://localhost:22222"


def test_load_config_falls_back_to_defaults_without_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
        "OLLAMA_BASE_URL",
        "CLAW_STU_DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    cfg = load_config()
    assert cfg.anthropic_api_key is None
    assert cfg.openai_api_key is None
    assert cfg.openrouter_api_key is None
    assert cfg.data_dir == tmp_path


def test_load_config_respects_claw_stu_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path / "custom"))
    cfg = load_config()
    assert cfg.data_dir == tmp_path / "custom"
```

- [ ] **Step 2: Run and confirm it fails**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py::test_load_config_reads_env_var_api_keys -v`
Expected: **FAIL** with `ImportError: cannot import name 'load_config'`.

- [ ] **Step 3: Implement `load_config` (env-var layer only; file loading is Task 7)**

Append to `src/orchestrator/config.py`:
```python
import os


def load_config() -> AppConfig:
    """Load configuration from env -> file -> defaults (in priority order).

    Env var names:
      CLAW_STU_DATA_DIR            -> data_dir
      OLLAMA_BASE_URL              -> ollama_base_url
      OLLAMA_API_KEY               -> ollama_api_key
      ANTHROPIC_API_KEY            -> anthropic_api_key
      ANTHROPIC_BASE_URL           -> anthropic_base_url
      OPENAI_API_KEY               -> openai_api_key
      OPENAI_BASE_URL              -> openai_base_url
      OPENROUTER_API_KEY           -> openrouter_api_key
      OPENROUTER_BASE_URL          -> openrouter_base_url
      STU_PRIMARY_PROVIDER         -> primary_provider

    File support lands in Task 7.
    """
    overrides: dict[str, object] = {}
    _apply_env_overrides(overrides)
    return AppConfig(**overrides)


def _apply_env_overrides(overrides: dict[str, object]) -> None:
    env_map: dict[str, str] = {
        "OLLAMA_BASE_URL": "ollama_base_url",
        "OLLAMA_API_KEY": "ollama_api_key",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "ANTHROPIC_BASE_URL": "anthropic_base_url",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_BASE_URL": "openai_base_url",
        "OPENROUTER_API_KEY": "openrouter_api_key",
        "OPENROUTER_BASE_URL": "openrouter_base_url",
        "STU_PRIMARY_PROVIDER": "primary_provider",
    }
    for env_name, field_name in env_map.items():
        value = os.environ.get(env_name)
        if value is not None:
            overrides[field_name] = value

    data_dir = os.environ.get("CLAW_STU_DATA_DIR")
    if data_dir:
        overrides["data_dir"] = Path(data_dir)
```

- [ ] **Step 4: Run the new tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py -v`
Expected: **10 passed** (7 original + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/config.py tests/test_config.py
git commit -m "feat(orchestrator): load_config reads env var overrides

Env var names map to AppConfig fields one-to-one:
  CLAW_STU_DATA_DIR            -> data_dir
  OLLAMA_BASE_URL / _API_KEY   -> ollama_base_url / ollama_api_key
  ANTHROPIC_API_KEY / _BASE_URL-> anthropic_api_key / anthropic_base_url
  OPENAI_API_KEY / _BASE_URL   -> openai_api_key / openai_base_url
  OPENROUTER_API_KEY / _BASE_URL -> openrouter_api_key / openrouter_base_url
  STU_PRIMARY_PROVIDER         -> primary_provider

Missing env vars are fine — load_config falls back to defaults.

File-based secrets.json loading lands in Task 7."
```

---

### Task 7: Add `~/.claw-stu/secrets.json` loading with 0600 check

**Files:**
- Modify: `src/orchestrator/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:
```python
import json
import os
import sys


def test_load_config_reads_secrets_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    for key in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps({
        "anthropic_api_key": "sk-ant-from-file",
        "openai_api_key": "sk-openai-from-file",
    }))
    if os.name != "nt":
        secrets_path.chmod(0o600)

    cfg = load_config()
    assert cfg.anthropic_api_key == "sk-ant-from-file"
    assert cfg.openai_api_key == "sk-openai-from-file"


def test_env_overrides_secrets_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps({
        "anthropic_api_key": "sk-ant-from-file",
    }))
    if os.name != "nt":
        secrets_path.chmod(0o600)

    cfg = load_config()
    # Env wins.
    assert cfg.anthropic_api_key == "sk-ant-from-env"


def test_load_config_tolerates_missing_secrets_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    for key in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    # No secrets.json created.
    cfg = load_config()
    assert cfg.anthropic_api_key is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms only")
def test_load_config_warns_on_non_0600_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text(json.dumps({"anthropic_api_key": "sk-ant-whatever"}))
    secrets_path.chmod(0o644)  # too open

    import logging
    with caplog.at_level(logging.WARNING, logger="clawstu.orchestrator.config"):
        cfg = load_config()

    assert cfg.anthropic_api_key == "sk-ant-whatever"
    assert any("0600" in record.message for record in caplog.records), (
        f"expected a 0600 warning; got: {[r.message for r in caplog.records]}"
    )


def test_load_config_rejects_malformed_secrets_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import load_config

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))
    secrets_path = tmp_path / "secrets.json"
    secrets_path.write_text("{not valid json")
    if os.name != "nt":
        secrets_path.chmod(0o600)

    with pytest.raises(ValueError, match="secrets.json"):
        load_config()
```

- [ ] **Step 2: Run and confirm all 5 new tests fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py -v -k "secrets or env_overrides"`
Expected: the 5 new tests **FAIL**.

- [ ] **Step 3: Implement file loading in `config.py`**

Add at the top of `config.py` alongside the existing `import os`:
```python
import json
import logging
import stat
import sys

logger = logging.getLogger(__name__)
```

Replace the current `load_config()` with:
```python
def load_config() -> AppConfig:
    """Load configuration from env > file > defaults (priority order).

    1. Start with defaults from AppConfig's field defaults.
    2. Overlay values from ~/.claw-stu/secrets.json if it exists.
    3. Overlay env var values (highest priority).
    4. Construct AppConfig and return.

    Rationale for env-over-file: a developer setting ANTHROPIC_API_KEY
    in their shell should always win over whatever is in the file,
    even if they forget to clear it. File-over-env would produce
    surprising results.
    """
    overrides: dict[str, object] = {}
    _apply_file_overrides(overrides)
    _apply_env_overrides(overrides)
    return AppConfig(**overrides)


def _apply_file_overrides(overrides: dict[str, object]) -> None:
    data_dir_env = os.environ.get("CLAW_STU_DATA_DIR")
    data_dir = Path(data_dir_env) if data_dir_env else Path.home() / ".claw-stu"
    secrets_path = data_dir / "secrets.json"
    if not secrets_path.exists():
        logger.debug("no secrets.json at %s", secrets_path)
        return
    _check_secrets_permissions(secrets_path)
    try:
        payload = json.loads(secrets_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"secrets.json at {secrets_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"secrets.json at {secrets_path} must be a JSON object, "
            f"got {type(payload).__name__}"
        )
    for key, value in payload.items():
        overrides[key] = value


def _check_secrets_permissions(secrets_path: Path) -> None:
    """WARN if secrets.json is not 0600 on POSIX. No-op on Windows.

    A hard fail would lock users out. A WARN gives them a chance to fix
    the permissions without downtime.
    """
    if os.name == "nt":
        logger.debug(
            "Windows detected; skipping POSIX permission check on %s. "
            "Treat ~/.claw-stu/ as sensitive and protect it via NTFS ACLs "
            "or a user-only profile location.",
            secrets_path,
        )
        return
    try:
        mode = secrets_path.stat().st_mode
    except OSError as exc:
        logger.warning("could not stat %s: %s", secrets_path, exc)
        return
    file_mode = stat.S_IMODE(mode)
    if file_mode != 0o600:
        logger.warning(
            "secrets.json at %s has permissions %o; "
            "recommended is 0600 (run `chmod 600 %s`)",
            secrets_path,
            file_mode,
            secrets_path,
        )
```

- [ ] **Step 4: Run the config tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py -v`
Expected: **15 passed** (10 previous + 5 new).

- [ ] **Step 5: Full suite + lint**

Run: `/tmp/claw-stu-venv/bin/python -m pytest -q && /tmp/claw-stu-venv/bin/ruff check .`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/config.py tests/test_config.py
git commit -m "feat(orchestrator): load_config reads secrets.json with 0600 check

Adds ~/.claw-stu/secrets.json as a config source. Priority is:
  env vars > secrets.json > AppConfig field defaults.

A missing file is fine (DEBUG log, no raise). A malformed JSON file
raises ValueError with the path embedded. A file whose permissions
are not 0600 on POSIX triggers a WARN log — we don't hard-fail
because that would lock users out while they fix the perms.

Windows skips the perms check with a DEBUG log pointing at NTFS
ACLs as the appropriate protection mechanism (per spec v2 §4.2.5
N7 fix)."
```

---

### Task 8: Ensure `~/.claw-stu/` exists with 0700 on first use

**Files:**
- Modify: `src/orchestrator/config.py` (add `ensure_data_dir`)
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:
```python
def test_ensure_data_dir_creates_with_correct_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import AppConfig, ensure_data_dir

    target = tmp_path / "fresh"
    assert not target.exists()

    cfg = AppConfig(data_dir=target)
    ensure_data_dir(cfg)

    assert target.exists()
    assert target.is_dir()
    if os.name != "nt":
        file_mode = stat.S_IMODE(target.stat().st_mode)
        assert file_mode == 0o700, f"expected 0700, got {file_mode:o}"


def test_ensure_data_dir_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from clawstu.orchestrator.config import AppConfig, ensure_data_dir

    cfg = AppConfig(data_dir=tmp_path / "already-there")
    ensure_data_dir(cfg)
    ensure_data_dir(cfg)  # second call must not raise
    assert cfg.data_dir.exists()
```

Also add `import stat` at the top of `test_config.py` if not already present.

- [ ] **Step 2: Run and confirm fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py -v -k ensure_data_dir`
Expected: FAIL on import of `ensure_data_dir`.

- [ ] **Step 3: Implement**

Append to `src/orchestrator/config.py`:
```python
def ensure_data_dir(cfg: AppConfig) -> None:
    """Create the data directory if it does not exist. 0700 on POSIX.

    Idempotent: second call is a no-op. Never silently overrides an
    existing directory's permissions — we only set the mode when we
    create the directory ourselves.
    """
    if cfg.data_dir.exists():
        return
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            cfg.data_dir.chmod(0o700)
        except OSError as exc:
            logger.warning("could not chmod %s to 0700: %s", cfg.data_dir, exc)
```

- [ ] **Step 4: Run tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_config.py -v`
Expected: **17 passed.**

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/config.py tests/test_config.py
git commit -m "feat(orchestrator): ensure_data_dir creates ~/.claw-stu/ with 0700

Idempotent directory creation. On POSIX, sets 0700 after mkdir so the
directory is user-only from the moment it exists. On Windows, skips
the chmod (NTFS ACLs are the appropriate protection per §4.2.5).

Only applies the mode when we're the one creating the directory —
an existing directory's permissions are left alone. This avoids
the case where a user deliberately set wider perms (e.g., for a
shared-family-machine deployment) and we silently override."
```

---

## Section C — Four LLM providers

### Task 9: `OllamaProvider` — scaffolding + happy path

**Files:**
- Create: `src/orchestrator/provider_ollama.py`
- Create: `tests/test_provider_ollama.py`

- [ ] **Step 1: Write the failing happy-path test**

Create `tests/test_provider_ollama.py`:
```python
"""OllamaProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import json

import httpx
import pytest

from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def _make_provider(transport: httpx.MockTransport) -> OllamaProvider:
    client = httpx.Client(transport=transport)
    return OllamaProvider(
        base_url="http://localhost:11434",
        api_key=None,
        client=client,
    )


def test_ollama_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "message": {"role": "assistant", "content": "Hi there."},
                "done": True,
                "total_duration": 123456,
                "eval_count": 42,
                "prompt_eval_count": 17,
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.3,
        model="llama3.2",
    )

    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.provider == "ollama"
    assert response.model == "llama3.2"
    assert response.finish_reason == "stop"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://localhost:11434/api/chat"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "llama3.2"
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0.3
    assert body["options"]["num_predict"] == 256
    assert body["messages"][0] == {"role": "system", "content": "You are Stuart."}
    assert body["messages"][1] == {"role": "user", "content": "Hello?"}
```

- [ ] **Step 2: Run and confirm fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_ollama.py -v`
Expected: FAIL on ImportError.

- [ ] **Step 3: Implement the provider**

Create `src/orchestrator/provider_ollama.py`:
```python
"""Ollama provider — local + cloud via the chat completions API.

Implements the existing sync LLMProvider protocol from providers.py.
Phase 2 flips this to async as part of the wider async migration.

Endpoint: POST {base_url}/api/chat
Docs: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion

HEARTBEAT §3 compliance: `complete()` stays under ~50 lines by
extracting `_build_payload`, `_post`, and `_parse_body` helpers.
Each helper has one job.
"""
from __future__ import annotations

from typing import Any

import httpx

from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


class OllamaProvider:
    """LLMProvider for local or cloud Ollama instances."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str = "llama3.2",
    ) -> LLMResponse:
        """POST to /api/chat and return the parsed response."""
        payload = self._build_payload(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = self._post(payload)
        return self._parse_body(body, model=model)

    def _build_payload(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, str]] = [
            {"role": "system", "content": system}
        ]
        for msg in messages:
            wire_messages.append({"role": msg.role, "content": msg.content})
        return {
            "model": model,
            "messages": wire_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the payload and return the parsed JSON body.

        Raises ProviderError on network failure, non-2xx status, or
        non-JSON body. The body dict is returned unvalidated; the
        caller is responsible for shape validation.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            http_response = self._client.post(
                f"{self._base_url}/api/chat",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"ollama returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            return http_response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise ProviderError(
                f"ollama returned non-JSON body: {exc}"
            ) from exc

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        message = body.get("message") or {}
        text = message.get("content", "")
        if not isinstance(text, str):
            raise ProviderError(
                f"ollama response message.content is not a string: "
                f"{type(text).__name__}"
            )
        return LLMResponse(
            text=text,
            provider=self.name,
            model=str(body.get("model", model)),
            finish_reason="stop",
            metadata={
                "eval_count": str(body.get("eval_count", "")),
                "prompt_eval_count": str(body.get("prompt_eval_count", "")),
            },
        )
```

**Line counts** after extraction: `complete()` is 17 lines, `_build_payload` is 22, `_post` is 22, `_parse_body` is 17. All under the HEARTBEAT 50-line cap.

- [ ] **Step 4: Run the happy-path test**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_ollama.py::test_ollama_happy_path -v`
Expected: **PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/provider_ollama.py tests/test_provider_ollama.py
git commit -m "feat(orchestrator): add OllamaProvider with happy-path coverage

Synchronous httpx.Client-based wrapper around Ollama's /api/chat
endpoint. Implements the existing LLMProvider protocol from
providers.py. Phase 2 migrates this (and the protocol) to async.

Injects the system prompt as a system-role message followed by the
caller's messages. Non-200 responses raise ProviderError with the
status + first 200 chars of the body. Connection errors raise
ProviderError chained to the original httpx exception.

Test uses httpx.MockTransport — no real network. Covers request
shape (URL, method, body, headers, options) and response parsing."
```

---

### Task 10: `OllamaProvider` — error paths

**Files:**
- Modify: `tests/test_provider_ollama.py`

- [ ] **Step 1: Append error-path tests**

Append to `tests/test_provider_ollama.py`:
```python
def test_ollama_500_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_connection_error_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="ollama request failed"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_non_json_body_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="non-JSON"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_missing_content_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": 123}})

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="not a string"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_ollama_with_api_key_sets_authorization_header() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"message": {"content": "ok"}, "model": "llama3.2"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OllamaProvider(
        base_url="http://localhost:11434",
        api_key="ollama-cloud-token",
        client=client,
    )
    provider.complete(
        system="sys",
        messages=[LLMMessage(role="user", content="hi")],
    )
    assert captured["authorization"] == "Bearer ollama-cloud-token"
```

- [ ] **Step 2: Run them**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_ollama.py -v`
Expected: **6 passed** (1 happy + 5 error paths).

- [ ] **Step 3: Commit**

```bash
git add tests/test_provider_ollama.py
git commit -m "test(ollama): cover error paths and API-key authorization

- 500 status -> ProviderError with HTTP code
- connect error -> ProviderError chained from httpx.ConnectError
- non-JSON body -> ProviderError
- message.content that isn't a string -> ProviderError
- api_key set -> Authorization: Bearer <key> on the outgoing request

Six Ollama provider tests total. All deterministic, no network."
```

---

### Task 11: `AnthropicProvider` — scaffolding + happy + errors

**Files:**
- Create: `src/orchestrator/provider_anthropic.py`
- Create: `tests/test_provider_anthropic.py`

- [ ] **Step 1: Write the failing happy-path test**

Create `tests/test_provider_anthropic.py`:
```python
"""AnthropicProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import json

import httpx
import pytest

from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def _make_provider(
    transport: httpx.MockTransport,
    api_key: str = "sk-ant-test",
) -> AnthropicProvider:
    client = httpx.Client(transport=transport)
    return AnthropicProvider(
        api_key=api_key,
        base_url="https://api.anthropic.com",
        client=client,
    )


def test_anthropic_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["x-api-key"] = request.headers.get("x-api-key")
        captured["anthropic-version"] = request.headers.get("anthropic-version")
        return httpx.Response(
            200,
            json={
                "id": "msg_abc",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there."}],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.2,
        model="claude-haiku-4-5",
    )
    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.provider == "anthropic"
    assert response.model == "claude-haiku-4-5"
    assert response.finish_reason == "end_turn"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["x-api-key"] == "sk-ant-test"
    # Anthropic API version header is required.
    assert captured["anthropic-version"]
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 256
    assert body["system"] == "You are Stuart."
    assert body["messages"][0] == {"role": "user", "content": "Hello?"}


def test_anthropic_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        AnthropicProvider(api_key=None)  # type: ignore[arg-type]


def test_anthropic_401_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"type":"error","error":{"type":"authentication_error"}}')
    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 401"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_anthropic_extracts_first_text_block() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
            },
        )
    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="sys",
        messages=[LLMMessage(role="user", content="hi")],
    )
    # Claw-STU expects a single concatenated text response. Anthropic may
    # emit multiple text blocks — we join them with a newline.
    assert response.text == "first\nsecond"


def test_anthropic_empty_content_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg",
                "content": [],
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
            },
        )
    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no text"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
```

- [ ] **Step 2: Run and confirm fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_anthropic.py -v`
Expected: FAIL on ImportError.

- [ ] **Step 3: Implement `AnthropicProvider`**

Create `src/orchestrator/provider_anthropic.py`:
```python
"""Anthropic Claude provider via the Messages API.

Endpoint: POST https://api.anthropic.com/v1/messages
Docs: https://docs.anthropic.com/en/api/messages

HEARTBEAT §3 compliance: same helper-extraction pattern as
OllamaProvider. `complete()` stays under 50 lines.
"""
from __future__ import annotations

from typing import Any

import httpx

from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)

_ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("AnthropicProvider requires an api_key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str = "claude-haiku-4-5",
    ) -> LLMResponse:
        payload = self._build_payload(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = self._post(payload)
        return self._parse_body(body, model=model)

    def _build_payload(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        return {
            "model": model,
            "system": system,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
        }
        try:
            http_response = self._client.post(
                f"{self._base_url}/v1/messages",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"anthropic request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"anthropic returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            return http_response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise ProviderError(
                f"anthropic returned non-JSON body: {exc}"
            ) from exc

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        text_blocks: list[str] = []
        for block in body.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                block_text = block.get("text")
                if isinstance(block_text, str):
                    text_blocks.append(block_text)
        if not text_blocks:
            raise ProviderError(
                "anthropic response has no text blocks in content"
            )
        usage = body.get("usage", {}) or {}
        return LLMResponse(
            text="\n".join(text_blocks),
            provider=self.name,
            model=str(body.get("model", model)),
            finish_reason=str(body.get("stop_reason", "stop")),
            metadata={
                "input_tokens": str(usage.get("input_tokens", "")),
                "output_tokens": str(usage.get("output_tokens", "")),
            },
        )
```

**Line counts**: `complete()` 16 lines, `_build_payload` 17, `_post` 24, `_parse_body` 20. All under cap.

- [ ] **Step 4: Run the tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_anthropic.py -v`
Expected: **5 passed.**

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/provider_anthropic.py tests/test_provider_anthropic.py
git commit -m "feat(orchestrator): add AnthropicProvider with happy-path + errors

Sync httpx.Client wrapper around POST /v1/messages. Headers:
x-api-key + anthropic-version. System prompt goes in the 'system'
field (Anthropic convention), user messages in the 'messages' list.

Response handling:
- Text is extracted from content[].type=='text' blocks; multiple
  blocks are joined with '\\n'
- Empty content array -> ProviderError
- Non-200 -> ProviderError with HTTP code + body prefix
- Non-JSON body -> ProviderError
- Constructing with api_key=None -> ValueError at init time (fail fast)

5 tests, all via httpx.MockTransport. No real network."
```

---

### Task 12: `OpenAIProvider` — scaffolding + happy + errors

**Files:**
- Create: `src/orchestrator/provider_openai.py`
- Create: `tests/test_provider_openai.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_provider_openai.py`:
```python
"""OpenAIProvider — httpx.MockTransport-based contract tests."""
from __future__ import annotations

import json

import httpx
import pytest

from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def _make_provider(
    transport: httpx.MockTransport,
    api_key: str = "sk-test",
) -> OpenAIProvider:
    return OpenAIProvider(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        client=httpx.Client(transport=transport),
    )


def test_openai_happy_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-abc",
                "object": "chat.completion",
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hi there.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 3,
                },
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.2,
        model="gpt-4o-mini",
    )
    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.provider == "openai"
    assert response.finish_reason == "stop"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-test"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"][0] == {"role": "system", "content": "You are Stuart."}
    assert body["messages"][1] == {"role": "user", "content": "Hello?"}
    assert body["max_tokens"] == 256
    assert body["temperature"] == 0.2


def test_openai_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        OpenAIProvider(api_key=None)  # type: ignore[arg-type]


def test_openai_401_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "invalid api key"}}
        )
    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 401"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_openai_empty_choices_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl",
                "choices": [],
                "model": "gpt-4o-mini",
            },
        )
    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no choices"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
```

- [ ] **Step 2: Run and confirm fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_openai.py -v`
Expected: FAIL on ImportError.

- [ ] **Step 3: Implement**

Create `src/orchestrator/provider_openai.py`:
```python
"""OpenAI provider via the Chat Completions API.

Endpoint: POST https://api.openai.com/v1/chat/completions
Docs: https://platform.openai.com/docs/api-reference/chat

HEARTBEAT §3 compliance: same helper-extraction pattern as the
other providers. `complete()` stays under 50 lines.
"""
from __future__ import annotations

from typing import Any

import httpx

from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIProvider requires an api_key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str = "gpt-4o-mini",
    ) -> LLMResponse:
        payload = self._build_payload(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = self._post(payload)
        return self._parse_body(body, model=model)

    def _build_payload(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, str]] = [
            {"role": "system", "content": system}
        ]
        for msg in messages:
            wire_messages.append({"role": msg.role, "content": msg.content})
        return {
            "model": model,
            "messages": wire_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        try:
            http_response = self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"openai returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            return http_response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise ProviderError(
                f"openai returned non-JSON body: {exc}"
            ) from exc

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError("openai response has no choices")
        first = choices[0]
        message = first.get("message") or {}
        text = message.get("content", "")
        if not isinstance(text, str):
            raise ProviderError(
                f"openai choice.message.content is not a string: "
                f"{type(text).__name__}"
            )
        usage = body.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=str(body.get("model", model)),
            finish_reason=str(first.get("finish_reason", "stop")),
            metadata={
                "prompt_tokens": str(usage.get("prompt_tokens", "")),
                "completion_tokens": str(usage.get("completion_tokens", "")),
            },
        )
```

**Line counts**: `complete()` 17 lines, `_build_payload` 22, `_post` 22, `_parse_body` 24. All under cap.

- [ ] **Step 4: Run tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_openai.py -v`
Expected: **4 passed.**

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/provider_openai.py tests/test_provider_openai.py
git commit -m "feat(orchestrator): add OpenAIProvider with happy-path + errors

Sync httpx.Client wrapper around POST /v1/chat/completions.
Authorization: Bearer <api_key>. System prompt goes as a
{role: system} message at the head of the messages array (OpenAI
convention, different from Anthropic's separate system field).

Response handling:
- First choice's message.content is the text
- Empty choices array -> ProviderError
- Non-string content -> ProviderError
- 4xx/5xx -> ProviderError with HTTP code + body prefix
- api_key=None at init -> ValueError

4 tests via httpx.MockTransport."
```

---

### Task 13: `OpenRouterProvider` — scaffolding + happy + errors

**Files:**
- Create: `src/orchestrator/provider_openrouter.py`
- Create: `tests/test_provider_openrouter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_provider_openrouter.py`:
```python
"""OpenRouterProvider — httpx.MockTransport-based contract tests.

OpenRouter is API-compatible with OpenAI's chat completions format
but with a few extra headers and the ability to route to many
upstream models (GLM, Mistral, Kimi, etc.).
"""
from __future__ import annotations

import json

import httpx
import pytest

from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


def _make_provider(
    transport: httpx.MockTransport,
    api_key: str = "sk-or-test",
) -> OpenRouterProvider:
    return OpenRouterProvider(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        client=httpx.Client(transport=transport),
    )


def test_openrouter_happy_path_glm() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["authorization"] = request.headers.get("authorization")
        captured["http-referer"] = request.headers.get("http-referer")
        captured["x-title"] = request.headers.get("x-title")
        return httpx.Response(
            200,
            json={
                "id": "gen-xyz",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hi there.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "model": "z-ai/glm-4.5-air",
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                },
            },
        )

    provider = _make_provider(httpx.MockTransport(handler))
    response = provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.2,
        model="z-ai/glm-4.5-air",
    )
    assert isinstance(response, LLMResponse)
    assert response.text == "Hi there."
    assert response.provider == "openrouter"
    assert response.model == "z-ai/glm-4.5-air"
    assert response.finish_reason == "stop"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-or-test"
    # OpenRouter asks for these headers for attribution / leaderboard.
    assert captured["http-referer"]
    assert captured["x-title"]
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "z-ai/glm-4.5-air"
    assert body["messages"][0] == {"role": "system", "content": "You are Stuart."}
    assert body["messages"][1] == {"role": "user", "content": "Hello?"}


def test_openrouter_missing_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key"):
        OpenRouterProvider(api_key=None)  # type: ignore[arg-type]


def test_openrouter_402_quota_exhausted() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            json={"error": {"message": "insufficient credits"}},
        )
    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="HTTP 402"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )


def test_openrouter_empty_choices_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "gen", "choices": [], "model": "z-ai/glm-4.5-air"},
        )
    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="no choices"):
        provider.complete(
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )
```

- [ ] **Step 2: Run and confirm fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_openrouter.py -v`
Expected: FAIL on ImportError.

- [ ] **Step 3: Implement**

Create `src/orchestrator/provider_openrouter.py`:
```python
"""OpenRouter provider — aggregator for GLM, Mistral, Kimi, and many more.

OpenRouter is API-compatible with OpenAI's chat completions format, so
the wire shape is the same as OpenAIProvider. It adds two attribution
headers (HTTP-Referer, X-Title) that OpenRouter uses for its public
leaderboard; these are documented as recommended-not-required.

Endpoint: POST https://openrouter.ai/api/v1/chat/completions
Docs: https://openrouter.ai/docs

HEARTBEAT §3 compliance: same helper-extraction pattern as the
other providers. `complete()` stays under 50 lines.
"""
from __future__ import annotations

from typing import Any

import httpx

from clawstu.orchestrator.providers import (
    LLMMessage,
    LLMResponse,
    ProviderError,
)


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        referer: str = "https://github.com/SirhanMacx/Claw-STU",
        x_title: str = "Claw-STU",
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouterProvider requires an api_key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)
        self._referer = referer
        self._x_title = x_title

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str = "z-ai/glm-4.5-air",
    ) -> LLMResponse:
        payload = self._build_payload(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body = self._post(payload)
        return self._parse_body(body, model=model)

    def _build_payload(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, str]] = [
            {"role": "system", "content": system}
        ]
        for msg in messages:
            wire_messages.append({"role": msg.role, "content": msg.content})
        return {
            "model": model,
            "messages": wire_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": self._referer,
            "X-Title": self._x_title,
        }
        try:
            http_response = self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"openrouter request failed: {exc}") from exc
        if http_response.status_code >= 400:
            raise ProviderError(
                f"openrouter returned HTTP {http_response.status_code}: "
                f"{http_response.text[:200]}"
            )
        try:
            return http_response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise ProviderError(
                f"openrouter returned non-JSON body: {exc}"
            ) from exc

    def _parse_body(self, body: dict[str, Any], *, model: str) -> LLMResponse:
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError("openrouter response has no choices")
        first = choices[0]
        message = first.get("message") or {}
        text = message.get("content", "")
        if not isinstance(text, str):
            raise ProviderError(
                f"openrouter choice.message.content is not a string: "
                f"{type(text).__name__}"
            )
        usage = body.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=str(body.get("model", model)),
            finish_reason=str(first.get("finish_reason", "stop")),
            metadata={
                "prompt_tokens": str(usage.get("prompt_tokens", "")),
                "completion_tokens": str(usage.get("completion_tokens", "")),
            },
        )
```

**Line counts**: `complete()` 17 lines, `_build_payload` 22, `_post` 24, `_parse_body` 24. All under cap.

- [ ] **Step 4: Run tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_openrouter.py -v`
Expected: **4 passed.**

- [ ] **Step 5: Full suite check**

Run: `/tmp/claw-stu-venv/bin/python -m pytest -q`
Expected: **89 + 2 + 4 + 17 + 6 + 5 + 4 + 4 = 131 passed.**

(Tally: 89 baseline, +2 test_imports, +4 test_task_kinds, +17 test_config across Tasks 5-8, +6 ollama, +5 anthropic, +4 openai, +4 openrouter.)

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/provider_openrouter.py tests/test_provider_openrouter.py
git commit -m "feat(orchestrator): add OpenRouterProvider with happy-path + errors

Sync httpx.Client wrapper around POST /api/v1/chat/completions.
OpenRouter is API-compatible with OpenAI's chat completions format,
with two extra headers for attribution:
- HTTP-Referer (default: the Claw-STU repo URL)
- X-Title (default: 'Claw-STU')

Both default to sensible values but are constructor-settable so
downstream forks / deployments can override.

Error handling mirrors OpenAIProvider:
- 402 quota exhausted -> ProviderError with HTTP code
- Empty choices -> ProviderError
- Non-string content -> ProviderError
- api_key=None -> ValueError at init

4 tests via httpx.MockTransport. Test count: 131 total."
```

---

### Task 14: Export new symbols from `src/orchestrator/__init__.py`

**Files:**
- Modify: `src/orchestrator/__init__.py`

- [ ] **Step 1: Read current __init__.py**

Run: `cat /Users/mind_uploaded_crustacean/Projects/Claw-STU/src/orchestrator/__init__.py`

- [ ] **Step 2: Add exports**

Append to `src/orchestrator/__init__.py`:
```python
from clawstu.orchestrator.config import (
    AppConfig,
    TaskRoute,
    ensure_data_dir,
    load_config,
)
from clawstu.orchestrator.provider_anthropic import AnthropicProvider
from clawstu.orchestrator.provider_ollama import OllamaProvider
from clawstu.orchestrator.provider_openai import OpenAIProvider
from clawstu.orchestrator.provider_openrouter import OpenRouterProvider
from clawstu.orchestrator.task_kinds import TaskKind

__all__ = [
    *__all__ if "__all__" in dir() else [],  # preserve any existing exports
    "AnthropicProvider",
    "AppConfig",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "TaskKind",
    "TaskRoute",
    "ensure_data_dir",
    "load_config",
]
```

**IMPORTANT:** if the existing `__init__.py` already has `__all__`, merge by hand — don't use the `dir()` trick (it doesn't work at module import time). Simpler: if `__all__` exists, append to it explicitly:

```python
__all__ = list(
    set(__all__)  # existing
    | {
        "AnthropicProvider",
        "AppConfig",
        "OllamaProvider",
        "OpenAIProvider",
        "OpenRouterProvider",
        "TaskKind",
        "TaskRoute",
        "ensure_data_dir",
        "load_config",
    }
)
```

Pick whichever is cleaner given what's already in the file.

- [ ] **Step 3: Verify imports work**

Run:
```bash
/tmp/claw-stu-venv/bin/python -c "from clawstu.orchestrator import AppConfig, TaskKind, OllamaProvider, AnthropicProvider, OpenAIProvider, OpenRouterProvider, load_config, ensure_data_dir, TaskRoute; print('OK')"
```
Expected: `OK`.

- [ ] **Step 4: Run full suite**

Run: `/tmp/claw-stu-venv/bin/python -m pytest -q`
Expected: 131 passed.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/__init__.py
git commit -m "chore(orchestrator): export new Phase 1 symbols from __init__

AppConfig, TaskRoute, TaskKind, load_config, ensure_data_dir, and
the four provider classes are now top-level imports from
clawstu.orchestrator. Downstream code (Phase 2 router, Phase 5
session wiring) imports from this namespace rather than reaching
into individual module files."
```

---

## Section D — CLI entry point

### Task 15: `clawstu` CLI scaffold with `--help`

**Files:**
- Create: `src/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:
```python
"""Tests for the clawstu CLI entry point."""
from __future__ import annotations

from typer.testing import CliRunner

from clawstu.cli import app


runner = CliRunner()


def test_help_mentions_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Every top-level command we register should appear in --help.
    for command in ("serve", "doctor", "scheduler", "profile"):
        assert command in result.stdout, f"--help missing '{command}'"


def test_help_shows_project_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "clawstu" in result.stdout.lower() or "Stuart" in result.stdout


def test_invoking_with_no_args_shows_help() -> None:
    # Typer default: no args + no default command -> shows help (exit 0).
    result = runner.invoke(app, [])
    assert result.exit_code in (0, 2)  # Typer may return 2 for missing command
```

- [ ] **Step 2: Run and confirm fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL on ImportError.

- [ ] **Step 3: Implement the CLI skeleton**

Create `src/cli.py`:
```python
"""clawstu — the Claw-STU console entry point.

Thin wrapper over the HTTP API and the proactive scheduler. No
pedagogical logic lives here; every command calls functions that
already exist in clawstu.api, clawstu.orchestrator, or (Phase 4+)
clawstu.memory / clawstu.scheduler.

Commands:
  clawstu serve                              start the FastAPI app
  clawstu doctor                             self-diagnosis
  clawstu scheduler run-once --task <name>   run a proactive task once
  clawstu profile export <learner_id>        export profile + brain tarball
  clawstu profile import <path>              restore a tarball
"""
from __future__ import annotations

import typer

app = typer.Typer(
    name="clawstu",
    help=(
        "Stuart — a personal learning agent that grows with the "
        "student. Made by a teacher, for learners."
    ),
    no_args_is_help=True,
    add_completion=False,
)

scheduler_app = typer.Typer(help="Proactive-scheduler administration.")
profile_app = typer.Typer(help="Learner profile portability.")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(profile_app, name="profile")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
) -> None:
    """Start the FastAPI app + embedded scheduler.

    Binds to 127.0.0.1 by default (localhost-only). Pass --host 0.0.0.0
    explicitly if you know what you're doing.
    """
    typer.echo(f"clawstu serve: starting uvicorn on {host}:{port}")
    typer.echo(
        "NOTE: Phase 1 serve is a placeholder. Full lifespan with the "
        "embedded scheduler lands in Phase 6."
    )
    # The actual uvicorn.run call lands in Task 18 once we're ready to
    # wire it. Phase 1's serve command exists mainly so `clawstu --help`
    # lists it and packaging tests can discover it.


@app.command()
def doctor() -> None:
    """Self-diagnosis: config load, provider connectivity, SQLite, FTS5."""
    from clawstu.orchestrator.config import load_config

    typer.echo("clawstu doctor — Phase 1 baseline")
    try:
        cfg = load_config()
    except Exception as exc:
        typer.secho(f"  config load: FAIL ({exc})", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho("  config load: ok", fg=typer.colors.GREEN)
    typer.echo(f"    data_dir: {cfg.data_dir}")
    typer.echo(f"    primary_provider: {cfg.primary_provider}")
    typer.echo(f"    fallback_chain: {list(cfg.fallback_chain)}")
    typer.echo("  provider reachability: DEFERRED (Phase 2)")
    typer.echo("  sqlite + FTS5: DEFERRED (Phase 3)")
    typer.echo("  embeddings model: DEFERRED (Phase 4)")


@scheduler_app.command("run-once")
def scheduler_run_once(
    task: str = typer.Option(..., "--task", help="Task name to run."),
) -> None:
    """Run one proactive task immediately (Phase 6)."""
    typer.echo(f"clawstu scheduler run-once --task {task}")
    typer.secho(
        "NOTE: the scheduler + task registry land in Phase 6. "
        "This command is a placeholder in Phase 1.",
        fg=typer.colors.YELLOW,
    )


@profile_app.command("export")
def profile_export(
    learner_id: str = typer.Argument(...),
    out: str = typer.Option(..., "--out", "-o", help="Output tarball path."),
) -> None:
    """Export a learner profile + brain pages as a tarball (Phase 7)."""
    typer.echo(f"clawstu profile export {learner_id} --out {out}")
    typer.secho(
        "NOTE: profile/brain tarball export lands in Phase 7. "
        "This command is a placeholder in Phase 1.",
        fg=typer.colors.YELLOW,
    )


@profile_app.command("import")
def profile_import(path: str = typer.Argument(...)) -> None:
    """Import a previously exported learner tarball (Phase 7)."""
    typer.echo(f"clawstu profile import {path}")
    typer.secho(
        "NOTE: profile import lands in Phase 7. "
        "This command is a placeholder in Phase 1.",
        fg=typer.colors.YELLOW,
    )


def main() -> None:
    """Entry point wired to pyproject.toml's [project.scripts]."""
    app()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_cli.py -v`
Expected: **3 passed.**

- [ ] **Step 5: Verify the installed script works**

Run:
```bash
/tmp/claw-stu-venv/bin/clawstu --help
```
Expected: help text showing `serve`, `doctor`, `scheduler`, `profile`.

Run:
```bash
/tmp/claw-stu-venv/bin/clawstu doctor
```
Expected: `clawstu doctor — Phase 1 baseline` followed by config lines.

- [ ] **Step 6: Commit**

```bash
git add src/cli.py tests/test_cli.py
git commit -m "feat(cli): scaffold clawstu entry point with serve/doctor/scheduler/profile

Typer-based CLI wired to pyproject.toml [project.scripts] as
clawstu = clawstu.cli:main. Four top-level commands:
- serve: placeholder that prints the bind target; real uvicorn.run
  lands in Task 18 when the lifespan is ready
- doctor: calls load_config() and prints config summary; provider
  reachability, SQLite, FTS5, embeddings checks are deferred to
  later phases with explicit DEFERRED lines
- scheduler run-once: Phase 6 placeholder
- profile export/import: Phase 7 placeholders

All placeholder commands print yellow 'NOTE:' lines so operators
know what's stubbed and when to expect the real implementation.

3 tests via typer.testing.CliRunner. Test count: 134 total."
```

---

### Task 16: `test_packaging.py` — metadata integrity test

**Files:**
- Create: `tests/test_packaging.py`

- [ ] **Step 1: Write the test**

Create `tests/test_packaging.py`:
```python
"""Tests that pyproject.toml ships with the right metadata.

These are cheap catch-the-obvious-mistake tests. They don't cover the
wheel build itself — that's what CI's `python -m build` step does.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _load_pyproject() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


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


def test_hatch_sources_mapping_exposes_clawstu() -> None:
    pyproject = _load_pyproject()
    sources = (
        pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["sources"]
    )
    assert sources == {"src": "clawstu"}


def test_console_script_points_at_clawstu_cli_main() -> None:
    pyproject = _load_pyproject()
    scripts = pyproject["project"]["scripts"]
    assert scripts["clawstu"] == "clawstu.cli:main"


def test_requires_python_is_3_11_or_higher() -> None:
    pyproject = _load_pyproject()
    assert pyproject["project"]["requires-python"] == ">=3.11"


def test_dependencies_include_typer_and_httpx() -> None:
    pyproject = _load_pyproject()
    deps = pyproject["project"]["dependencies"]
    dep_names = [d.split(">=")[0].split("<")[0].split("[")[0].strip() for d in deps]
    assert "typer" in dep_names
    assert "httpx" in dep_names
    assert "fastapi" in dep_names
    assert "pydantic" in dep_names


def test_license_is_mit() -> None:
    pyproject = _load_pyproject()
    license_value = pyproject["project"]["license"]
    # setuptools/hatchling accepts either {"file": "LICENSE"} or "MIT"
    if isinstance(license_value, dict):
        assert license_value.get("file") == "LICENSE"
    else:
        assert license_value in ("MIT", "MIT License")
```

- [ ] **Step 2: Run tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_packaging.py -v`
Expected: **7 passed.**

If any fail, fix `pyproject.toml` accordingly and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_packaging.py
git commit -m "test(packaging): assert pyproject.toml ships with correct metadata

Catches the obvious mistakes:
- project name is clawstu (not claw-stu)
- build backend is hatchling.build with hatchling>= in requires
- [tool.hatch.build.targets.wheel.sources] maps src -> clawstu
- [project.scripts] clawstu = clawstu.cli:main (not src.cli:main)
- requires-python is >=3.11
- typer, httpx, fastapi, pydantic are all in base dependencies
- license stays MIT

Cheap fast tests (no wheel build); the actual build is covered by
`python -m build` in the CI publish job."
```

---

## Section E — Wiring `doctor` to a real provider ping (optional network opt-in)

### Task 17: `clawstu doctor` — add stub provider reachability checks gated by `--ping`

**Files:**
- Modify: `src/cli.py` (extend `doctor` command)
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the test that asserts `doctor` without `--ping` never touches the network**

Append to `tests/test_cli.py`:
```python
def test_doctor_without_ping_does_not_make_network_calls(
    monkeypatch, tmp_path,
):
    """doctor is a static config dump by default. --ping is opt-in for
    actual provider round-trips.
    """
    from clawstu.orchestrator import config as cfg_mod
    import httpx

    monkeypatch.setenv("CLAW_STU_DATA_DIR", str(tmp_path))

    def forbidden_request(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError(
            "doctor without --ping must not make network calls; "
            f"attempted: args={args}, kwargs={kwargs}"
        )
    monkeypatch.setattr(httpx.Client, "post", forbidden_request)
    monkeypatch.setattr(httpx.Client, "get", forbidden_request)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0


def test_doctor_has_a_ping_flag_in_help() -> None:
    result = runner.invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--ping" in result.stdout
```

- [ ] **Step 2: Run and confirm fail**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_cli.py -v -k doctor`
Expected: the `--ping` help test FAILs (flag doesn't exist yet).

- [ ] **Step 3: Extend `doctor` with a `--ping` flag (behind a stub until Phase 2's router lands)**

Replace the existing `doctor` function in `src/cli.py` with:
```python
@app.command()
def doctor(
    ping: bool = typer.Option(
        False,
        "--ping",
        help=(
            "Also attempt a round-trip against every configured provider. "
            "Without --ping, doctor is a pure static config dump that "
            "never touches the network."
        ),
    ),
) -> None:
    """Self-diagnosis: config load, provider reachability, SQLite, FTS5."""
    from clawstu.orchestrator.config import load_config

    typer.echo("clawstu doctor — Phase 1 baseline")
    try:
        cfg = load_config()
    except Exception as exc:
        typer.secho(f"  config load: FAIL ({exc})", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho("  config load: ok", fg=typer.colors.GREEN)
    typer.echo(f"    data_dir: {cfg.data_dir}")
    typer.echo(f"    primary_provider: {cfg.primary_provider}")
    typer.echo(f"    fallback_chain: {list(cfg.fallback_chain)}")

    if ping:
        typer.echo("  provider reachability:")
        typer.secho(
            "    DEFERRED (Phase 2 wires the router + real connectivity checks)",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.echo("  provider reachability: skipped (pass --ping to try)")

    typer.echo("  sqlite + FTS5: DEFERRED (Phase 3)")
    typer.echo("  embeddings model: DEFERRED (Phase 4)")
```

- [ ] **Step 4: Run the CLI tests**

Run: `/tmp/claw-stu-venv/bin/python -m pytest tests/test_cli.py -v`
Expected: **5 passed** (3 previous + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/cli.py tests/test_cli.py
git commit -m "feat(cli): doctor --ping flag (reachability check is deferred to Phase 2)

Without --ping, doctor is a pure static config dump: load AppConfig,
print data_dir + primary_provider + fallback_chain, mark the rest as
DEFERRED. Guarantees zero network calls by default — enforced by a
test that monkeypatches httpx.Client.post to raise if called.

With --ping, doctor prints 'DEFERRED (Phase 2 wires the router +
real connectivity checks)' today. Phase 2 will implement the
actual round-trip. The flag exists now so Phase 2 is an internal
change to the doctor function body rather than a CLI signature
change."
```

---

## Section F — Final verification and push

### Task 18: Full regression run, ruff + mypy clean, commit checkpoint

**Files:** none modified

- [ ] **Step 1: Run the full test suite with coverage**

Run:
```bash
cd /Users/mind_uploaded_crustacean/Projects/Claw-STU
/tmp/claw-stu-venv/bin/python -m pytest --cov=src --cov-report=term
```

Expected:
- **143 tests passing** — 89 baseline + 54 new. Verified math:
  `89 + 2 + 4 + 17 + 6 + 5 + 4 + 4 + 5 + 7 = 143`. If you see 141
  or 142, figure out which test is missing before continuing —
  silently running a smaller suite hides regressions.
- **Coverage ≥ 80%** (baseline is 85%)
- Runtime < 2 seconds

Record the actual count in your scratchpad. If you see 143 → you're
good. If you see anything else → figure out why before proceeding.

- [ ] **Step 2: Run ruff**

Run: `/tmp/claw-stu-venv/bin/ruff check .`
Expected: `All checks passed!`

If ruff complains, `ruff check --fix .` + rerun.

- [ ] **Step 3: Run mypy on the new files specifically**

Run:
```bash
/tmp/claw-stu-venv/bin/mypy \
  src/orchestrator/task_kinds.py \
  src/orchestrator/config.py \
  src/orchestrator/provider_ollama.py \
  src/orchestrator/provider_anthropic.py \
  src/orchestrator/provider_openai.py \
  src/orchestrator/provider_openrouter.py \
  src/cli.py
```
Expected: no errors.

If mypy flags issues in new files, fix them. If it flags issues in files we didn't touch (e.g., pre-existing drift from `src.` → `clawstu.` imports), those are out of scope for Phase 1 — note them in a follow-up issue.

- [ ] **Step 4: Verify import hierarchy is still clean (spot check)**

Run:
```bash
grep -rn "from src\." src/ tests/ --include="*.py" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 5: Spot-check the installed CLI**

Run:
```bash
/tmp/claw-stu-venv/bin/clawstu --help
/tmp/claw-stu-venv/bin/clawstu doctor
/tmp/claw-stu-venv/bin/clawstu serve --help
/tmp/claw-stu-venv/bin/clawstu scheduler run-once --task dream_cycle
/tmp/claw-stu-venv/bin/clawstu profile export test-learner --out /tmp/test.tar.gz
```
Each should exit with code 0 and print expected output.

- [ ] **Step 6: Final summary commit (empty) to mark the Phase 1 boundary**

```bash
git commit --allow-empty -m "chore: Phase 1 complete — providers + config + CLI + packaging

Cumulative changes since the Phase 1 start:
- pyproject.toml: hatchling build backend, clawstu package name,
  src->clawstu wheel sources mapping, [project.scripts] entry,
  typer in base deps
- All src.xxx imports rewritten to clawstu.xxx (enforced by
  tests/test_imports.py)
- CI publish job wired on v* tags, gated on existing 'test' job
- src/orchestrator/task_kinds.py: TaskKind enum (7 pedagogical jobs)
- src/orchestrator/config.py: AppConfig, TaskRoute,
  _default_task_routing, load_config (env + file layers),
  ensure_data_dir
- src/orchestrator/provider_ollama.py: sync httpx wrapper for
  Ollama /api/chat
- src/orchestrator/provider_anthropic.py: sync httpx wrapper for
  Anthropic /v1/messages
- src/orchestrator/provider_openai.py: sync httpx wrapper for
  OpenAI /v1/chat/completions
- src/orchestrator/provider_openrouter.py: sync httpx wrapper for
  OpenRouter (OpenAI-compatible + HTTP-Referer / X-Title headers)
- src/cli.py: clawstu entry point with serve/doctor/scheduler
  run-once/profile export/profile import (serve + scheduler +
  profile are Phase-later placeholders; doctor does a static
  config dump with --ping opt-in)

Provider protocol remains sync in Phase 1. Phase 2 migrates the
whole stack to async as part of the wider router + live-content
relocation pass.

Test count: 141 passing, coverage 85%+. Ruff clean. mypy clean on
new files. CI green on push (to be verified)."
```

- [ ] **Step 7: Push to origin**

```bash
git push origin main
```

- [ ] **Step 8: Verify CI goes green**

Run: `sleep 45 && gh run list --limit 1`
Expected: `completed	success	chore: Phase 1 complete ...` on `main`.

If CI fails, fix the failure as a new task and re-commit. Do NOT claim Phase 1 done until CI is green.

---

## Post-phase checklist

- [ ] All tasks have their checkboxes checked
- [ ] `pytest -q` passes in under 2 seconds
- [ ] Coverage is ≥ 80% (ideally higher than the 85% Phase-0 baseline)
- [ ] `ruff check .` is clean
- [ ] `mypy` is clean on new files
- [ ] `clawstu --help` runs from the installed editable
- [ ] `clawstu doctor` prints a static config summary without any network calls
- [ ] `grep -rn "from src\." src/ tests/` returns nothing
- [ ] CI is green on the latest `main` commit
- [ ] Phase 1 commit boundary marker (Task 18 Step 6) is on `main`
- [ ] `docs/superpowers/plans/2026-04-11-phase-1-packaging-providers-config-cli.md` (this file) is checked in and visible to future plan readers

## Known deferrals (documented for Phase 2 plan)

- **Provider protocol is still sync in Phase 1.** Phase 2's first task is to flip `LLMProvider.complete` to `async def`, update `EchoProvider`, and rewrite every `_client.post` → `await self._client.post` inside the four provider files. All four provider bodies are written to minimize the delta: every HTTP call is a single `post` invocation with no sync-only idioms.
- **`ModelRouter` does not exist yet.** Phase 2 adds `src/orchestrator/router.py` with the routing logic and flips `ReasoningChain` / `LiveContentGenerator` to take a router instead of a provider.
- **`clawstu serve` does not actually start uvicorn.** Phase 6 wires the lifespan (with the scheduler embedded) and this command becomes a real `uvicorn.run(clawstu.api.main:app, host=..., port=...)`.
- **`clawstu scheduler run-once`** is a Phase 6 placeholder.
- **`clawstu profile export / import`** are Phase 7 placeholders — they require a tarball format that bundles profile JSON + brain pages, which means Phase 4's brain store has to exist first.
- **`clawstu doctor --ping` connectivity check** is a Phase 2 placeholder.
- **PyPI publish has not run.** The CI workflow is wired and will fire on `v*` tags, but no tag is pushed in Phase 1 — the first tagged release happens after Phase 7 ships a user-visible feature set worth releasing.

## References

- Design spec: `docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md` v2 (commit `4d877f5`+)
- SOUL.md, HEARTBEAT.md — non-negotiable
- Claw-ED for packaging reference: `/Users/mind_uploaded_crustacean/Projects/Claw-ED-v0920/pyproject.toml`, `.github/workflows/ci.yml`
- Spec reviewer v2 report (minor issues captured inline above as fixes)
