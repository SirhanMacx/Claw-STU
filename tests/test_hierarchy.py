"""Import DAG guard — enforces spec §4.1 layering across clawstu/.

Every import statement inside `clawstu/` is parsed via ast.parse and
checked against the authoritative layer dependency table below. A
violation in ANY file (existing or future) fails this test, catching
layer leaks at commit time.

Layer dependency table (authoritative for Phase 2 and beyond):

    Layer           Allowed import targets
    profile         stdlib, pydantic
    safety          stdlib, pydantic, profile
    memory          stdlib, pydantic, safety, profile
    curriculum      stdlib, pydantic, safety, profile, memory
    assessment      stdlib, pydantic, safety, profile, memory
    engagement      stdlib, pydantic, safety, profile, memory,
                    curriculum, assessment
    orchestrator    stdlib, pydantic, safety, profile, memory,
                    curriculum, assessment
    persistence     stdlib, pydantic, profile, engagement
    api             any of the above
    scheduler       stdlib, pydantic, profile, orchestrator, memory,
                    persistence, engagement

`cli` is an `api`-like top layer and may import from everything.

Deviations from spec §4.1 prose:

1. `safety` is allowed to import from `profile`. Rationale: the
   content filter in `clawstu/safety/content_filter.py` needs the
   `AgeBracket` enum from `clawstu.profile.model` as dict keys in
   its `_BRACKET_BLOCKLIST` table. Age-appropriate content filtering
   is inherently age-aware, and `AgeBracket` is a profile concept.
   The spec's "safety is the lowest layer" prose was aspirational;
   in practice, profile must be below safety for this to work.
   `profile` is then the true lowest layer with zero clawstu deps.

2. `orchestrator` is allowed to import from `assessment`. Rationale:
   `live_content.py` (moved from curriculum in Task 10) returns
   `AssessmentItem` from `generate_check`, so it needs the enum +
   class from `clawstu.assessment.generator`. Spec §4.1 point 7
   reads "orchestrator imports from safety, profile, memory,
   curriculum" without literally listing assessment — the prose
   wording is incomplete.

3. `scheduler` is allowed to import from `profile`. Rationale: the
   Phase 6 tasks (`refresh_zpd`, `spaced_review`) need `EventKind`
   for filtering observation events and `ZPDCalibrator` for the
   nightly recompute. Both are profile-layer types and every layer
   scheduler already transitively imports (memory, engagement,
   persistence, orchestrator) already depends on profile. Adding
   profile to scheduler's direct-import set doesn't widen the DAG.

All three deviations should be folded back into a future spec erratum.
This table is the source of truth for Phase 2+.
"""
from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterable

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CLAWSTU = _REPO_ROOT / "clawstu"

# Layer -> set of allowed layer targets.
_ALLOWED: dict[str, frozenset[str]] = {
    "profile": frozenset(),
    "safety": frozenset({"profile"}),
    "memory": frozenset({"safety", "profile"}),
    "curriculum": frozenset({"safety", "profile", "memory"}),
    "assessment": frozenset({"safety", "profile", "memory"}),
    "engagement": frozenset(
        {"safety", "profile", "memory", "curriculum", "assessment"}
    ),
    "orchestrator": frozenset(
        {"safety", "profile", "memory", "curriculum", "assessment"}
    ),
    "persistence": frozenset({"profile", "engagement"}),
    "api": frozenset(
        {
            "safety",
            "profile",
            "memory",
            "curriculum",
            "assessment",
            "engagement",
            "orchestrator",
            "persistence",
        }
    ),
    "scheduler": frozenset(
        {"orchestrator", "memory", "persistence", "engagement", "profile"}
    ),
    # cli is effectively api-layer (top); allow everything.
    "_cli": frozenset(
        {
            "safety",
            "profile",
            "memory",
            "curriculum",
            "assessment",
            "engagement",
            "orchestrator",
            "persistence",
            "api",
            "scheduler",
        }
    ),
}


def _layer_of(relpath: pathlib.Path) -> str:
    """Given a path relative to clawstu/, return its layer name.

    clawstu/orchestrator/config.py -> "orchestrator"
    clawstu/cli.py                 -> "_cli"
    clawstu/__init__.py            -> "__init__" (skipped — not in _ALLOWED)
    """
    parts = relpath.parts
    if parts[0] == "cli.py":
        return "_cli"
    if len(parts) < 2:
        return parts[0].replace(".py", "")
    return parts[0]


def _iter_clawstu_imports(tree: ast.AST) -> Iterable[str]:
    """Yield target layers imported from this AST.

    Returns the first-level package segment after `clawstu.` for each
    `from clawstu.X import ...` or `import clawstu.X` statement. Yields
    an empty string for bare `import clawstu` / `from clawstu import ...`.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("clawstu.") or mod == "clawstu":
                rest = mod[len("clawstu.") :] if mod != "clawstu" else ""
                yield rest.split(".")[0] if rest else ""
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("clawstu.") or alias.name == "clawstu":
                    rest = (
                        alias.name[len("clawstu.") :]
                        if alias.name != "clawstu"
                        else ""
                    )
                    yield rest.split(".")[0] if rest else ""


def test_every_clawstu_import_respects_the_layering_dag() -> None:
    """For every .py under clawstu/, check its imports against _ALLOWED."""
    violations: list[str] = []
    for py_file in _CLAWSTU.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(_CLAWSTU)
        source_layer = _layer_of(rel)
        if source_layer not in _ALLOWED:
            # Unknown layer — skip (e.g., top-level __init__.py).
            continue
        allowed = _ALLOWED[source_layer]
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for target in _iter_clawstu_imports(tree):
            if not target:
                continue
            if target == source_layer:
                continue  # intra-layer imports are always fine
            if target not in allowed:
                violations.append(
                    f"{rel}: '{source_layer}' cannot import "
                    f"'clawstu.{target}' "
                    f"(allowed: {sorted(allowed)})"
                )
    assert not violations, (
        "Layering violations detected:\n  " + "\n  ".join(violations)
    )


def test_layer_dag_is_acyclic() -> None:
    """Sanity check the table itself has no cycles."""

    def _reaches(start: str, target: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if start in seen:
            return False
        seen.add(start)
        for next_layer in _ALLOWED.get(start, frozenset()):
            if next_layer == target:
                return True
            if _reaches(next_layer, target, seen):
                return True
        return False

    for layer in _ALLOWED:
        assert not _reaches(layer, layer), f"cycle detected at layer {layer}"
