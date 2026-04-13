# Changelog

All notable changes to Claw-STU will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses date-based versioning (e.g. `4.12.2026`)
following the Claw-ED naming convention.

## v4.13.2026.0 — 2026-04-13

### Added — Stuart v5: Full Ed Parity
- **Agent loop** (`clawstu/agent/`) — tool-use agent loop with max 10 iterations, approval policy (max 3 generations/turn), composable system prompt with learner context
- **9 generation tools** — worksheet, game, visual, simulation, animation, slides, study guide, practice test, flashcards — each reads learner profile (ZPD, age, modality) and generates at the right level
- **4 export tools** — PDF (WeasyPrint), DOCX (python-docx), standalone HTML, flashcards (CSV/Anki)
- **4 retrieval tools** — web search (DuckDuckGo, age-filtered), teacher materials (shared KB bridge), brain search, source fetch
- **4 memory tools** — read profile, search brain, write notes, read misconceptions
- **Tool auto-discovery** — `ToolRegistry` discovers all `BaseTool` subclasses from `agent/tools/`
- **7 new CLI commands** — `generate`, `export`, `search`, `practice`, `flashcards`, `game`, `ingest`
- **5 new Telegram commands** — `/game`, `/practice`, `/flashcards`, `/study`, `/export`
- **Shared KB bridge** — `SHARED_KB_PATH` env var lets Stuart query Ed's ingested curriculum
- **Architecture spec** — `docs/superpowers/specs/2026-04-13-stuart-v5-parity-design.md`

### Changed
- Auth default changed from `dev` to `generate` — fresh installs are never wide-open
- Health endpoint strips verbose error details from public response
- HEARTBEAT CI workflow added (function size + exception swallow checks)
- Full HEARTBEAT compliance: 14 functions decomposed, 11 annotated as single-responsibility
- Exception audit: 0 bare `except Exception: pass` remaining

### Fixed
- 2 mypy strict errors from decomposition (topic type, ask return)

## v4.12.2026.1 — 2026-04-12

### Security
- Added CORS middleware with `CLAW_STU_CORS_ORIGINS` env var and Chrome extension support
- Added in-memory per-IP rate limiting on all session-lifecycle endpoints
- Hardened auth from optional dev-mode to production-default with three modes: enforce, generate, dev
- Dockerfile now runs as non-root user `clawstu`
- Docker Compose binds to localhost only (127.0.0.1:8000)
- Added explicit secrets patterns to .gitignore (secrets.json, api_token, .credentials.json)

### Fixed
- Fixed 15 stale `src/` path references in CONTRIBUTING.md (now all `clawstu/`)

### Changed
- Adopted 4-segment version scheme (MAJOR.MINOR.YEAR.PATCH) matching Claw-ED
- Added Docker build + smoke test job to CI pipeline
- Publish job now requires Docker build to pass

## [Unreleased]

### Planned — Phase 1 (Providers, memory, proactive agent)

See `docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md`
for the full design spec. Seven-phase implementation plan:

- **Phase 1** — Packaging rename (`claw-stu` → `clawstu`), config, and four
  network providers (Ollama, Anthropic, OpenAI, OpenRouter). Console entry
  point `clawstu`. Hatchling build backend.
- **Phase 2** — Router + async migration + live-content relocation
  (`src/curriculum/live_generator.py` → `src/orchestrator/live_content.py`).
- **Phase 3** — SQLite persistence with WAL mode.
- **Phase 4** — Memory system: brain store, ONNX MiniLM embeddings (core
  dep), hybrid keyword+vector search with RRF, knowledge graph,
  per-learner concept wiki.
- **Phase 5** — Live content wired into session loop + crisis wiring via
  `InboundSafetyGate` at every student-text entry point + session-memory
  integration.
- **Phase 6** — Proactive scheduler inside FastAPI lifespan. Five initial
  tasks: `dream_cycle`, `prepare_next_session`, `spaced_review`,
  `refresh_zpd`, `prune_stale`.
- **Phase 7** — Warm-start session resume + learner-facing endpoints
  (`/learners/{id}/wiki/{concept}`, `/resume`, `/queue`, `/capture`).

## [0.1.0] — 2026-04-11

The pre-alpha bootstrap. Ships a working deterministic MVP that runs the
full session loop end-to-end with zero network dependency, plus the
scaffolding for the LLM-backed path that lands in later phases.

### Added

**Identity and contracts:**
- `SOUL.md` — Stuart's identity, voice, and behavioral constraints.
  Non-negotiable.
- `HEARTBEAT.md` — runtime health and self-monitoring contract. Global
  invariants (no swallowed exceptions, strict import hierarchy, 50-line
  function cap) and domain-specific invariants (SOUL, profile, session,
  safety).
- `Handoff.md` — the full vision document. Pedagogical philosophy, MVP
  scope, open-source commitment, post-MVP roadmap.

**Learner profile engine (`src/profile/`):**
- `AgeBracket` with `from_age()` mapping (early elementary → adult).
- `Domain` enum (US History, Global History, Civics, ELA, Science, Math,
  Other). Placeholder for future subjects.
- `Modality` enum (text reading, primary source, Socratic dialogue,
  interactive scenario, visual/spatial, worked example, inquiry/project).
- `ComplexityTier` enum (approaching / meeting / exceeding) with
  `stepped_up` / `stepped_down` transitions.
- `ObservationEvent` — the atomic unit of profile state. Every profile
  mutation traces back to one of these.
- `LearnerProfile` with modality outcomes, per-domain ZPD estimates,
  misconception tally, and JSON round-trip via `to_dict` / `from_dict`.
- `Observer` — the only component that writes to a profile. Stateless,
  auditable.
- `ZPDCalibrator` — recommends complexity tier and modality. Cold-start
  defaults, step-up on cruising, step-down on grinding. Excludes a
  failed modality on re-teach.
- `export_to_json` / `import_from_json` / `write_profile` / `read_profile`
  for portability. Atomic writes via temp-file-and-rename.

**Assessment (`src/assessment/`):**
- `AssessmentItem` with type, prompt, concept, tier, modality, rubric,
  choices, canonical answer.
- `QuestionGenerator` with a deterministic seed library for calibration.
  No LLM calls — calibration is always offline-deterministic.
- `Evaluator` for multiple-choice, short-answer, CRQ, and source-analysis
  items. Rubric-based scoring for constructed responses.
- `EvaluationResult` with correctness, score, and rubric feedback.
- CRQ (Constructed Response Question) handling and formative-feedback
  generation.

**Curriculum (`src/curriculum/`):**
- `LearningBlock` data model.
- `ContentSelector` with a seed library of 4 US History blocks covering
  the Declaration of Independence's purpose across multiple modalities
  (Socratic, primary source, visual/spatial, worked example).
- `Pathway` and `PathwayPlanner` for deterministic concept sequences.
- `Topic` model for free-text student-provided topics (used by the
  not-yet-wired live content generator).
- `LiveContentGenerator` — LLM-backed generator for pathway, block, and
  check. Parses strict JSON, runs every generated string through a
  safety gate, has offline stubs that activate when the provider is
  `EchoProvider`. Not yet wired into the session loop; that's Phase 5.

**Engagement (`src/engagement/`):**
- `Session` and `SessionPhase` (onboarding, calibrating, teaching,
  checking, closing, closed).
- `SessionDirective` and `TeachBlockResult` as the runner's return types.
- `SessionRunner` with the full lifecycle: `onboard`, `calibration_items`,
  `record_calibration_answer`, `finish_calibration`, `next_directive`,
  `select_check`, `record_check`, `close`. Deterministic, LLM-free.
- `ModalityRotator` — thin wrapper around `ZPDCalibrator.recommend_modality`
  that enforces the project's foundational rule: on a failed check, the
  re-teach MUST use a different modality than the one that failed.
- `EngagementSignals` — rolling per-session state (consecutive correct,
  consecutive incorrect, mean latency) used to detect cruising vs
  frustrated.

**Safety (`src/safety/`):**
- `ContentFilter` — age-bracket-aware keyword blocklist. Universal list
  (graphic violence, explicit sexual, self-harm instructions) plus
  per-bracket extensions. Deterministic, not LLM-backed.
- `EscalationHandler` — regex patterns for self-harm, abuse disclosure,
  and acute distress. Canned crisis-resource message with 988, Crisis
  Text Line (741741), Childhelp (1-800-422-4453). Stuart steps out of
  the teach role entirely on detection.
- `BoundaryEnforcer` — outbound sycophancy and emotional-claim detector.
  Strips "I'm proud of you", "great question!", "I'm worried", etc.,
  before they reach the student.

**Orchestrator scaffolding (`src/orchestrator/`):**
- `LLMProvider` protocol and `LLMMessage` / `LLMResponse` data shapes.
- `EchoProvider` — deterministic, offline. Used in tests and as the
  last-resort fallback so the session loop never hard-crashes.
- `PromptTemplate` and `PromptLibrary` — versioned templates with a
  hardcoded `SOUL_CORE` that quotes SOUL.md (not loaded at runtime
  from disk, to prevent prompt drift via file edits).
- `ReasoningChain` — wraps a provider with outbound boundary enforcement.

**FastAPI surface (`src/api/`):**
- `POST /sessions` — onboard and start a session.
- `GET /sessions/{id}` — current session state.
- `POST /sessions/{id}/calibration-answer` — submit a calibration answer.
- `POST /sessions/{id}/finish-calibration` — transition to teaching.
- `POST /sessions/{id}/next` — request the next teach/check directive.
- `POST /sessions/{id}/check-answer` — submit a check-for-understanding.
- `POST /sessions/{id}/close` — close the session.
- `GET /health` — HEARTBEAT-backed health.
- Profile and admin routers.
- In-memory `AppState` with thread-safe `put` / `get` / `drop`.

**Tests (`tests/`):**
- 89 tests passing offline in under 1 second.
- `test_foundational_reteach.py` — the two-function test that enforces
  the foundational invariant: a failed check re-teaches in a different
  modality than the one that failed. This test must stay green forever.
- `test_profile_model.py`, `test_zpd.py` — profile and ZPD calibration.
- `test_assessment.py` — question generation and evaluation.
- `test_session_flow.py` — end-to-end session lifecycle.
- `test_safety.py` — content filter, escalation, boundary enforcer.
- `test_orchestrator.py` — providers, chain, prompt library.
- `test_api.py` — FastAPI route contract.
- `test_topic.py` — free-text topic validation and slug normalization.

**Tooling:**
- `pyproject.toml` with Python 3.11+, ruff, mypy `--strict`, pytest
  asyncio-auto mode, 80% coverage floor, `filterwarnings = error`.
- GitHub Actions CI on every push and PR: Python 3.11 and 3.12 matrix,
  ruff, pytest with coverage.

### Changed

- Nothing — this is the bootstrap.

### Fixed

- Nothing — this is the bootstrap.

### Security

- Crisis escalation is foundational from day zero. Self-harm, abuse
  disclosure, and acute distress patterns are detected via deterministic
  regex (LLM-backed second layer is post-MVP). On detection, Stuart
  surfaces human resources and does not counsel. This is called out in
  `SOUL.md` §5 as a hard constraint.
- Age-appropriate content filter applied on every outbound string.
- No PII in logs. Learner IDs are hashed before any structured logging.
- Brain pages (once Phase 4 lands) are stored under a hashed subdirectory
  so the on-disk layout doesn't leak learner IDs.

---

[Unreleased]: https://github.com/SirhanMacx/Claw-STU/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SirhanMacx/Claw-STU/releases/tag/v0.1.0
