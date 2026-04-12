# Features

A detailed breakdown of what Claw-STU ships today.

## Status legend

- **Shipped** -- in the current `main` branch, tests green
- **Planned** -- designed in the roadmap, not yet started
- **Deferred** -- explicitly post-MVP (see `ROADMAP.md`)
- **Non-goal** -- not planned. Ever. (See `ROADMAP.md` "Explicitly deferred")

---

## Core learning loop

| Feature | Status | Notes |
|---|---|---|
| Deterministic session runner (onboard, calibrate, teach, check, adapt, close) | Shipped | `engagement/session.py` |
| Reteach-different-modality invariant | Shipped | `tests/test_foundational_reteach.py` |
| Seven instructional modalities | Shipped | text reading, primary source, Socratic dialogue, interactive scenario, visual/spatial, worked example, inquiry/project |
| Three complexity tiers | Shipped | approaching / meeting / exceeding, per-domain |
| CRQ-style assessment with rubric scoring | Shipped | `assessment/evaluator.py` |
| Multiple choice assessment (fallback for recall) | Shipped | Used sparingly per SOUL.md preference for CRQ |
| Live-generated learning blocks, checks, and pathways | Shipped | `orchestrator/live_content.py` |
| Free-text topic support (any subject) | Shipped | `LiveContentGenerator` wired into session loop |
| Warm-start session resume | Shipped | `clawstu resume <learner_id>` via pre-generated artifacts |

---

## Learner profile

| Feature | Status | Notes |
|---|---|---|
| Observational profile (never self-reported) | Shipped | `profile/model.py` |
| Per-domain ZPD estimates | Shipped | `profile/zpd.py` -- cold start defaults, step up on cruising, step down on grinding |
| Modality outcome tracking | Shipped | Running success rate and mean latency per modality |
| Misconception tally | Shipped | Concept-scoped counter, grows on wrong answers, shrinks on success |
| Age bracket (not exact age) | Shipped | Early elementary through adult, for content gating + voice calibration |
| JSON round-trip export/import | Shipped | `profile/export.py` with atomic writes |
| CLI `clawstu profile export / import` with brain pages | Shipped | `cli_companions.py` |
| Lifelong portability (profile grows from childhood to adulthood) | Deferred | v1.0.0 |

---

## Memory and knowledge

| Feature | Status | Notes |
|---|---|---|
| Brain store: learner, concept, session, source, misconception, topic pages | Shipped | `memory/store.py` + `memory/pages/` |
| Compiled truth + timeline page structure | Shipped | Compiled truth pulled into LLM context; timeline feeds dream cycle |
| Hybrid keyword + vector search with RRF | Shipped | `memory/search.py` |
| ONNX MiniLM embeddings as a core dependency | Shipped | `memory/embeddings.py` -- built in, not optional |
| Knowledge graph of concept relationships | Shipped | `memory/knowledge_graph.py` -- prerequisite_for, builds_on, taught_in |
| Per-learner concept wiki | Shipped | `clawstu wiki <concept>` + `memory/wiki.py` |
| Capture student-shared primary sources | Shipped | `memory/capture.py` |
| Cross-session memory consolidation | Shipped | Overnight dream cycle via scheduler |
| Per-learner context assembly | Shipped | `memory/context.py` -- `build_learner_context()` |

---

## Proactive scheduler

| Feature | Status | Notes |
|---|---|---|
| Scheduler embedded in FastAPI lifespan | Shipped | `scheduler/runner.py` -- one process, one lifecycle |
| Dream cycle (rewrites compiled truth from timeline) | Shipped | Nightly task via `scheduler/tasks/dream_cycle.py` |
| Prepare-next-session (pre-generates first block + check) | Shipped | `scheduler/tasks/prepare_next_session.py` |
| Spaced review of shaky concepts | Shipped | `scheduler/tasks/spaced_review.py` |
| ZPD refresh from full event history | Shipped | `scheduler/tasks/refresh_zpd.py` |
| Prune-stale session housekeeping | Shipped | `scheduler/tasks/prune_stale.py` |
| Per-task idempotency | Shipped | Each task skips if state is current |
| Task registry with cron specs | Shipped | `scheduler/registry.py` |
| Admin scheduler endpoint | Shipped | `api/admin.py` -- `GET /admin/scheduler` |

---

## Safety

| Feature | Status | Notes |
|---|---|---|
| Age-appropriate content filter (outbound) | Shipped | `safety/content_filter.py` -- deterministic keyword blocklist with age-bracket extensions |
| Crisis detection on student text (self-harm, abuse, distress) | Shipped | `safety/escalation.py` -- regex patterns + canned resource packet |
| 988 / 741741 / Childhelp resource packet | Shipped | US-based; localized resources are a post-MVP TODO |
| Outbound boundary enforcer (sycophancy, emotional claims, innate praise) | Shipped | `safety/boundaries.py` |
| Inbound safety gate on all student-text entry points | Shipped | `safety/gate.py` |
| `CRISIS_PAUSE` session phase | Shipped | Paused session refuses to advance |
| No PII in logs | Shipped | Hashed learner IDs, no raw utterances |

---

## LLM providers

| Feature | Status | Notes |
|---|---|---|
| `LLMProvider` protocol | Shipped | `orchestrator/providers.py` |
| Deterministic `EchoProvider` | Shipped | Offline fallback, test backbone, fallback-chain floor |
| Ollama (local + cloud) | Shipped | `orchestrator/provider_ollama.py` -- async httpx wrapper |
| Anthropic Claude | Shipped | `orchestrator/provider_anthropic.py` |
| OpenAI | Shipped | `orchestrator/provider_openai.py` |
| OpenRouter | Shipped | `orchestrator/provider_openrouter.py` |
| Task-level model routing | Shipped | `orchestrator/router.py` -- `TaskKind` enum + `ModelRouter` |
| Fallback chain ending at EchoProvider | Shipped | Ollama, OpenAI, Anthropic, OpenRouter, Echo |

---

## Orchestration

| Feature | Status | Notes |
|---|---|---|
| Versioned `PromptLibrary` with SOUL.md-quoting core template | Shipped | `orchestrator/prompts.py` |
| `ReasoningChain` with outbound boundary enforcement | Shipped | `orchestrator/chain.py` |
| Live content generator for pathway, block, check | Shipped | `orchestrator/live_content.py` |
| Per-learner context assembly (from brain) | Shipped | `memory/context.py` |

---

## CLI

| Feature | Status | Notes |
|---|---|---|
| `clawstu learn` -- interactive adaptive session | Shipped | `cli_chat.py` |
| `clawstu resume` -- warm-start from pre-generated artifact | Shipped | `cli_chat.py` |
| `clawstu wiki` -- per-student concept wiki | Shipped | `cli_companions.py` |
| `clawstu progress` -- learner dashboard | Shipped | `cli_companions.py` |
| `clawstu history` -- past sessions | Shipped | `cli_companions.py` |
| `clawstu review` -- spaced review due list | Shipped | `cli_companions.py` |
| `clawstu ask` -- one-shot Socratic question | Shipped | `cli_companions.py` |
| `clawstu setup` -- interactive provider wizard | Shipped | `setup_wizard.py` |
| `clawstu serve` -- FastAPI app + scheduler | Shipped | `cli.py` |
| `clawstu doctor` -- self-diagnosis | Shipped | `cli.py` |
| `clawstu scheduler run-once` -- run a proactive task | Shipped | `cli.py` |
| `clawstu profile export / import` -- portable tarballs | Shipped | `cli_companions.py` |

---

## API surface

| Feature | Status | Notes |
|---|---|---|
| `POST /sessions` (onboard) | Shipped | |
| `GET /sessions/{id}` | Shipped | |
| `POST /sessions/{id}/calibration-answer` | Shipped | |
| `POST /sessions/{id}/finish-calibration` | Shipped | |
| `POST /sessions/{id}/next` | Shipped | |
| `POST /sessions/{id}/check-answer` | Shipped | |
| `POST /sessions/{id}/close` | Shipped | |
| `GET /learners` | Shipped | |
| `GET /learners/{id}` | Shipped | |
| `GET /learners/{id}/wiki/{concept}` | Shipped | |
| `GET /learners/{id}/sessions` | Shipped | |
| `GET /learners/{id}/review` | Shipped | |
| `GET /health` | Shipped | HEARTBEAT-backed status |
| `GET /admin/scheduler` | Shipped | |
| OpenAPI `/docs` interactive | Shipped | FastAPI default |

---

## Persistence

| Feature | Status | Notes |
|---|---|---|
| SQLite persistence (WAL mode) | Shipped | `persistence/store.py` |
| Schema migrations | Shipped | `persistence/migrations.py` |
| In-memory persistent store for CLI | Shipped | `cli_state.py` -- JSON snapshot on disk |
| `~/.claw-stu/` data directory | Shipped | Configurable via `CLAW_STU_DATA_DIR` |
| `~/.claw-stu/secrets.json` with restricted perms | Shipped | `orchestrator/config.py` |
| Atomic writes via temp-file-and-rename | Shipped | Used for profile export |

---

## Distribution

| Feature | Status | Notes |
|---|---|---|
| `pip install clawstu` on PyPI | Shipped | v0.2.0 |
| Hatchling build backend | Shipped | `pyproject.toml` |
| GitHub Actions CI (test + lint + type) | Shipped | `.github/workflows/ci.yml` |
| Web UI landing page | Shipped | `docs/index.html` |
| Docker image | Deferred | Post-MVP |

---

## Frontend

| Feature | Status | Notes |
|---|---|---|
| Web UI served from FastAPI | Shipped | `api/static/index.html` |
| Guardian dashboard | Deferred | v0.4.0 -- read-only compiled-truth summary |
| Native mobile app | Non-goal | Explicitly deferred |

---

## What Claw-STU explicitly will NEVER do

- **Voice-based "friend" interface that simulates emotional intimacy.** Stuart
  is a tool. Warm, honest, useful -- but not a friend, peer, or authority
  figure.
- **Telemetry, ads, behavioral tracking for third parties.** No.
- **Multi-tenant hosted SaaS as the primary deployment path.** Claw-STU is a
  tool you run on your own machine.
- **A cryptocurrency, NFT, or "Learn-to-Earn" tokenomics layer.** No.
- **Crisis counseling.** If a student expresses distress, Stuart surfaces
  human resources and steps out of the teach role immediately.
- **A "good / bad / struggling" student label.** The learner profile
  describes current state per-domain so Stuart can adapt. It is not a
  diagnosis or a gradebook.
- **Data sharing with any institution without explicit learner and guardian
  consent.** The learner profile is owned by the learner.

---

*Every kid deserves a Stuart. Made by a teacher in New York.*
