# Contributing to Claw-STU

Thanks for your interest in making Claw-STU better. Whether you're a
teacher with ideas, a developer who wants to add features, a learning
scientist with pedagogical expertise, or someone who found a bug — we'd
love your help.

Claw-STU is pre-alpha. The shape of the project will change. That's
normal. Don't wait for things to feel settled to contribute — early
feedback is more valuable than polished code.

---

## Table of Contents

- [Before you contribute: SOUL.md and HEARTBEAT.md](#before-you-contribute)
- [Getting Started](#getting-started)
- [How to Add a New Modality](#how-to-add-a-new-modality)
- [How to Add a New Concept to the Seed Library](#how-to-add-a-new-concept-to-the-seed-library)
- [How to Add a New LLM Provider](#how-to-add-a-new-llm-provider)
- [Code Style Guide](#code-style-guide)
- [Pull Request Checklist](#pull-request-checklist)
- [Crisis Safety](#crisis-safety)
- [Good First Issues](#good-first-issues)
- [Questions?](#questions)

---

## Before you contribute

Two files define the non-negotiable shape of Claw-STU. Read them before
you write any code:

1. **[`SOUL.md`](SOUL.md)** — Stuart's identity and behavioral constraints.
   This file is the source of truth for *who Stuart is*. Stuart is a
   cognitive tool, not a friend, therapist, peer, or authority figure.
   Stuart does not simulate emotions. Stuart does not claim to care.
   Stuart surfaces human resources on crisis signal and steps out of the
   teach loop. Any PR that violates SOUL.md is rejected regardless of
   how clever the code is.
2. **[`HEARTBEAT.md`](HEARTBEAT.md)** — operational invariants and the
   runtime health contract. No swallowed exceptions. No functions over
   ~50 lines. Strict import hierarchy. Tests land with code. No PII in
   logs. Explicit types at module boundaries.

If your change would require loosening either file, that's a conversation
in an issue before a PR.

---

## Getting Started

1. **Fork and clone** the repo:
   ```bash
   git clone https://github.com/SirhanMacx/Claw-STU.git
   cd Claw-STU
   ```

2. **Install in development mode** (requires Python 3.11+):
   ```bash
   pip install -e ".[dev]"
   ```

3. **Run the test suite** to make sure everything works:
   ```bash
   pytest
   ```
   The whole suite runs offline via the deterministic `EchoProvider`.
   No API keys, no network. Target runtime: under 2 seconds.

4. **Run the linter** and **type checker**:
   ```bash
   ruff check .
   mypy clawstu/
   ```

5. **Read the foundational test**:
   ```bash
   cat tests/test_foundational_reteach.py
   ```
   This is the non-negotiable regression test: a failed check must
   re-teach in a different modality than the one that failed. Any PR
   that breaks this test is rejected.

6. **Create a branch** for your work:
   ```bash
   git checkout -b my-feature
   ```

---

## How to Add a New Modality

Modalities live in `clawstu/profile/model.py` as a `Modality` enum value.
Stuart rotates through modalities based on observed engagement — the
student never picks from a menu. Adding a new modality means:

1. **Add the enum value** in `clawstu/profile/model.py::Modality`. Pick a
   snake_case value. The order matters only for display; the rotator
   treats all modalities as equal candidates.
2. **Update `clawstu/curriculum/content.py`** to add at least one
   `LearningBlock` at each `ComplexityTier` (approaching, meeting,
   exceeding) for the new modality. Without seed content the
   `ContentSelector.select()` falls back to whatever is available, which
   defeats the purpose.
3. **Add a test** in `tests/test_session_flow.py` that onboards a
   learner and confirms the new modality can be reached via the session
   loop. At minimum: construct a profile where the new modality has the
   highest success rate and assert that `ModalityRotator.initial()`
   returns it.
4. **Run the foundational test**:
   ```bash
   pytest tests/test_foundational_reteach.py
   ```
   It iterates over every `Modality` value and verifies the
   reteach-different-modality invariant. If it stays green, the new
   modality is safe to add.

---

## How to Add a New Concept to the Seed Library

The seed library in `clawstu/curriculum/content.py` covers the deterministic
fallback path for offline / no-LLM-key use. It is intentionally small
and intentionally explicit — every block is human-reviewed.

To add a concept:

1. **Write a `LearningBlock`** for at least two modalities at `MEETING`
   tier. More is better. Include real primary source text where
   appropriate; do not paraphrase from memory. Cite via `source_ids`.
2. **Write an `AssessmentItem`** at each tier you want checked. Use
   `AssessmentType.CRQ` for constructed-response items with a
   rubric. Avoid `MULTIPLE_CHOICE` unless the concept is purely
   recall — SOUL.md prefers CRQs.
3. **Add the concept to `PathwayPlanner`** if it should appear in a
   default pathway. Optional; concepts that are only referenced by
   other blocks don't need to be on a pathway.
4. **Test** that the concept can be selected by the session runner.

---

## How to Add a New LLM Provider

The `LLMProvider` protocol lives in `clawstu/orchestrator/providers.py`.
A new provider is:

1. **A new file** `clawstu/orchestrator/provider_<name>.py` implementing the
   protocol with a single async `complete()` method that calls
   `httpx.AsyncClient` and returns an `LLMResponse`.
2. **`httpx.MockTransport`-based tests** in
   `tests/test_provider_<name>.py`. No real network calls. Every
   provider test case validates the request shape (URL, headers, body)
   and the response parsing. Error paths (4xx, 5xx, timeout) are
   tested with mocked transports that raise the right exceptions.
3. **A new entry in the `ModelRouter` fallback chain** and
   `AppConfig.task_routing` if the provider should be the default for
   any task.
4. **A `pyproject.toml` update** if the provider requires a new
   dependency. Declare with an upper bound (`<major+1`).

Do not swallow exceptions. Every provider error should raise
`ProviderError` with the upstream cause attached via `from exc`.

---

## Code Style Guide

Enforced automatically. CI will catch most of this; you can catch it
earlier with `ruff check --fix` and `mypy clawstu/`.

- **Python 3.11+ features.** `str | None`, `list[Foo]`, `@dataclass`, `match`.
- **Type annotations on every public function.** `mypy --strict` is
  enforced in CI. Private helpers can skip if obvious.
- **No `Any` without a comment explaining why.** Prefer concrete types
  or `object`.
- **Docstrings on every public module and class.** Pedagogical context
  goes in the module docstring. "Why does this file exist" is more
  valuable than "what does this function do" — the code says what.
- **No functions over ~50 lines.** Break complex logic into composable
  units. This is a HEARTBEAT invariant.
- **No bare `except:`.** No `except Exception: pass`. Every `except`
  handles a specific exception class or re-raises.
- **No PII in logs.** `learner_id` must be hashed before being logged.
  Raw student utterances never appear in log output.
- **Pydantic models for public data shapes.** `frozen=True` unless
  there's a reason to mutate.
- **Imports follow the hierarchy.** `safety → profile → memory →
  assessment / curriculum / engagement → orchestrator → api`. Lower
  layers never import from higher layers. `tests/test_hierarchy.py`
  (Phase 2) enforces this via AST walk.

---

## Pull Request Checklist

Before opening a PR, confirm:

- [ ] `pytest` is green locally (all existing tests plus your new ones)
- [ ] `ruff check .` is clean
- [ ] `mypy clawstu/` is clean
- [ ] Coverage is at or above 80% on new files
- [ ] `tests/test_foundational_reteach.py` is green
- [ ] No new `except Exception: pass` (use `grep -rn "except.*pass"
      clawstu/` before commit)
- [ ] No new function over ~50 lines (use `ruff` or manual check)
- [ ] No raw student text or `learner_id` in any log statement
- [ ] CHANGELOG.md has an `[Unreleased]` entry describing the change
- [ ] Docstrings on every new public function and class
- [ ] If you're adding a new safety or pedagogical invariant, you've
      added it to `HEARTBEAT.md` and added a test that enforces it
- [ ] If you're touching SOUL.md, you've flagged it in the PR description
      and requested human review specifically on the SOUL.md change

---

## Crisis Safety

This project serves minors. Crisis handling is not a feature — it is a
foundational invariant.

If you touch any code under `clawstu/safety/`, `clawstu/api/` (any handler
accepting student text), or `clawstu/orchestrator/chain.py`, you must:

1. **Confirm the inbound safety gate still runs** on every student-text
   entry point. The relevant tests are in `tests/test_safety.py` and
   `tests/test_inbound_safety_gate.py`.
2. **Not degrade the crisis detection regex patterns** in
   `clawstu/safety/escalation.py`. Adding patterns is welcome. Removing
   them requires a written rationale in the PR description.
3. **Not add any code path that returns LLM-generated text to a
   student without the `BoundaryEnforcer` outbound check.**

If you find a crisis false negative (a real distress signal we missed),
**do not** include the triggering text in a public issue. Email
`jon.anthony.maccarello@gmail.com` with subject line "SAFETY: [brief
description]". We treat these as P0.

---

## Versioning

Claw-ED and Claw-STU use date-aligned versioning: `M.DD.YYYY[.patch]`.
The major number is the release month, the minor tracks the day/sprint,
the year anchors the timeline, and the optional patch increments within
a release. This keeps the two projects' versions aligned and makes the
release timeline immediately visible.

---

## Good First Issues

Look for the [`good first issue`](https://github.com/SirhanMacx/Claw-STU/labels/good%20first%20issue)
label on GitHub. These are small, self-contained changes that let you
get familiar with the codebase without needing to understand everything.

Examples of good first issues we'd love help with:
- Expand the seed library with another US History concept
- Add a new CRQ rubric template to `clawstu/assessment/feedback.py`
- Improve a docstring that's hand-wavy
- Add a missing type annotation flagged by `mypy`
- Port a crisis detection pattern from a validated clinical source

---

## Questions?

- [GitHub Issues](https://github.com/SirhanMacx/Claw-STU/issues) — bugs,
  feature requests, design discussions
- [GitHub Discussions](https://github.com/SirhanMacx/Claw-STU/discussions)
  — open-ended questions, show-and-tell, pedagogical debate
- Email: `jon.anthony.maccarello@gmail.com` for anything sensitive

*Thanks for caring about this project. Every kid deserves a Stuart.*
