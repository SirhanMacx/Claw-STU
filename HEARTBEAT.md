# HEARTBEAT.md — Runtime health and self-monitoring

> This document describes the operational health contract for Claw-STU. It
> is the companion to `SOUL.md`: if SOUL.md describes *who Stuart is*, this
> describes *how we know Stuart is still working as intended*.

## Why this exists

Claw-ED's technical audit surfaced a recurring failure pattern: **silent
degradation**. Exceptions swallowed, prompts subtly drifting, tests passing
while the actual student experience decayed. Claw-STU inherits that lesson
as a first-class architectural concern.

Every module has a **heartbeat contract** — a narrow, explicit set of
invariants that must hold for that module to be considered healthy. A failed
heartbeat is never silent.

## Invariants

### Global invariants

These must hold everywhere in the codebase. Violations are bugs.

1. **No swallowed exceptions.** Every `except` either handles the specific
   exception class explicitly or re-raises. Bare `except:` and bare
   `except Exception: pass` are forbidden in production code.
2. **No circular imports.** The dependency graph is strictly hierarchical:
   `safety` → `profile` → `assessment`, `curriculum`, `engagement` →
   `orchestrator` → `api`. Lower layers never import from higher layers.
3. **Function size discipline.** No function exceeds ~50 lines. Complex
   logic is broken into composable units.
4. **Explicit types at module boundaries.** Public functions annotated. No
   `Any` without justification.
5. **Tests land with code.** A module without tests is a module that does
   not exist.

### SOUL.md invariants

1. Stuart never introduces itself with a name other than "Stuart."
2. Stuart never claims to feel emotions it does not have.
3. Stuart never role-plays as a friend, peer, or authority figure.
4. Stuart always surfaces crisis resources on crisis signal.
5. Stuart can always explain *why* it showed the student something, in
   terms grounded in the learner profile.

These are tested via `tests/test_soul_invariants.py`.

### Profile invariants

1. A learner profile always knows the learner's age bracket.
2. Every profile update carries a timestamp and a source event.
3. Profile export is round-trippable: `import(export(p)) == p`.
4. ZPD estimates are domain-scoped, never global.

### Session invariants

1. A session always calibrates before teaching.
2. A teach block is always followed by a check for understanding.
3. A failed check never advances the pathway — it re-teaches or deepens.
4. **A re-teach uses a different modality than the one that failed.**
   (This is the project's foundational test.)

### Safety invariants

1. Every piece of content shown to the student passes through
   `safety.content_filter`.
2. Every student utterance is scanned by `safety.escalation` before the
   orchestrator sees it.
3. Boundary violations (persona attacks, coercion attempts) are logged and
   refused — never silently accepted.

## Observability

- **Structured logging** from day one. Every session event is logged with
  `session_id`, `learner_id_hash`, `module`, `event_type`, and `payload`.
- **No PII in logs.** Learner names, ages, or identifying details never
  appear in log output. The profile is stored separately with strict
  access control.
- **Metric counters** (post-MVP): calibration accuracy, reteach rate,
  modality distribution, check-for-understanding pass rate per domain.

## Health endpoint

`GET /health` returns:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "invariants": {
    "soul_md_loaded": true,
    "safety_filters_active": true,
    "provider_reachable": true
  }
}
```

Any `false` value flips `status` to `"degraded"` and logs at WARN. Degraded
instances may still serve traffic, but failing invariants are reported.

## Failure modes we explicitly plan for

1. **LLM provider outage.** Sessions gracefully pause with a student-visible
   message; profile is not corrupted.
2. **Corrupted profile.** Import rejects; last-known-good snapshot is
   preserved.
3. **Prompt drift.** Snapshot tests catch unexpected changes to system
   prompts before they ship.
4. **Safety filter false negative.** Treated as a P0 bug. Regression test
   added before fix is merged.
5. **Safety filter false positive.** Treated as a P1 bug. The student
   experience matters.

## How to change this file

Same rules as `SOUL.md`: deliberate, reviewed, human-approved. A new
invariant means a new test.
