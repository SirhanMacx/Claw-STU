# Features

A detailed breakdown of what Claw-STU does and doesn't do.

## Status legend

- ✅ **Shipped** — in the current `main` branch, tests green
- 🟡 **In progress** — in the current implementation pass, partially landed
- 🔵 **Planned** — designed in the roadmap, not yet started
- ⬜ **Deferred** — explicitly post-MVP (see `ROADMAP.md`)
- ❌ **Non-goal** — not planned. Ever. (See `ROADMAP.md` "Explicitly deferred")

---

## Core learning loop

| Feature | Status | Notes |
|---|---|---|
| Deterministic session runner (onboard → calibrate → teach → check → adapt → close) | ✅ | `src/engagement/session.py` |
| Reteach-different-modality invariant | ✅ | `tests/test_foundational_reteach.py` |
| Seven instructional modalities | ✅ | text reading, primary source, Socratic dialogue, interactive scenario, visual/spatial, worked example, inquiry/project |
| Three complexity tiers | ✅ | approaching / meeting / exceeding, per-domain |
| CRQ-style assessment with rubric scoring | ✅ | `src/assessment/evaluator.py` |
| Multiple choice assessment (fallback for recall) | ✅ | Used sparingly per SOUL.md preference for CRQ |
| Seed library of US History learning blocks | ✅ | 4 blocks on Declaration of Independence purpose, across modalities and tiers |
| Free-text topic support (any subject, not just seeded ones) | 🟡 | `LiveContentGenerator` exists; wiring into session loop is Phase 5 |
| Live-generated learning blocks, checks, and pathways | 🟡 | `src/curriculum/live_generator.py`; moves to `src/orchestrator/live_content.py` in Phase 2 |
| Warm-start session resume | 🔵 | Phase 7 — `POST /learners/{id}/resume`, <200ms |

---

## Learner profile

| Feature | Status | Notes |
|---|---|---|
| Observational profile (never self-reported) | ✅ | `src/profile/model.py` |
| Per-domain ZPD estimates | ✅ | `src/profile/zpd.py` — cold start defaults, step up on cruising, step down on grinding |
| Modality outcome tracking | ✅ | Running success rate and mean latency per modality |
| Misconception tally | ✅ | Concept-scoped counter, grows on wrong answers, shrinks as understanding improves |
| Age bracket (not exact age) | ✅ | Early elementary → adult, for content gating + voice calibration |
| JSON round-trip export/import | ✅ | `src/profile/export.py` with atomic writes |
| CLI `clawstu profile export / import` with brain pages | 🔵 | Phase 7 |
| Lifelong portability (profile grows from childhood → adulthood) | ⬜ | v1.0.0 |

---

## Memory and knowledge

| Feature | Status | Notes |
|---|---|---|
| Brain store: learner, concept, session, source, misconception, topic pages | 🔵 | Phase 4 |
| Compiled truth + timeline page structure | 🔵 | Phase 4 — compiled truth is pulled into LLM context; timeline feeds dream cycle |
| Hybrid keyword + vector search with RRF | 🔵 | Phase 4 |
| ONNX MiniLM embeddings as a core dependency | 🔵 | Phase 4 — built in, not an optional extra |
| Knowledge graph of concept relationships | 🔵 | Phase 4 — prerequisite_for, builds_on, taught_in |
| Per-learner concept wiki endpoint | 🔵 | Phase 7 — `GET /learners/{id}/wiki/{concept}` |
| Capture student-shared primary sources | 🔵 | Phase 7 — `POST /learners/{id}/capture` |
| Cross-session memory consolidation | 🔵 | Phase 6 — overnight dream cycle |

---

## Proactive scheduler

| Feature | Status | Notes |
|---|---|---|
| Scheduler embedded in FastAPI lifespan | 🔵 | Phase 6 — one process, one lifecycle |
| Dream cycle (rewrites compiled truth from timeline) | 🔵 | Phase 6 — nightly 02:30 local |
| Prepare-next-session (pre-generates first block + check) | 🔵 | Phase 6 — nightly 03:15 local, consumed by warm-start |
| Spaced review of shaky concepts | 🔵 | Phase 6 — nightly 03:45 local |
| ZPD refresh from full event history | 🔵 | Phase 6 — nightly 04:00 local |
| Prune-stale session housekeeping | 🔵 | Phase 6 — weekly Sunday 05:00 local |
| Per-task idempotency | 🔵 | Phase 6 — each task skips if state is current |
| Per-task token cost tracking | 🔵 | Phase 6 — `SchedulerRunStore` |
| Admin transparency endpoint | 🔵 | Phase 6 — `GET /admin/scheduler` |
| Learner-queue endpoint | 🔵 | Phase 7 — `GET /learners/{id}/queue` |

---

## Safety

| Feature | Status | Notes |
|---|---|---|
| Age-appropriate content filter (outbound) | ✅ | `src/safety/content_filter.py` — deterministic keyword blocklist with age-bracket extensions |
| Crisis detection on student text (self-harm, abuse, distress) | ✅ | `src/safety/escalation.py` — regex patterns + canned resource packet |
| 988 / 741741 / Childhelp resource packet | ✅ | US-based; localized resources are a post-MVP TODO |
| Outbound boundary enforcer (sycophancy, emotional claims, innate praise) | ✅ | `src/safety/boundaries.py` |
| Inbound safety gate on all student-text entry points | 🔵 | Phase 5 — closes a current HEARTBEAT invariant gap |
| `CRISIS_PAUSE` session phase | 🔵 | Phase 5 — paused session refuses to advance |
| No PII in logs | ✅ | Hashed learner IDs, no raw utterances |
| Crisis events do not write to brain | 🔵 | Phase 5 — intentional PII-retention-minimization |
| LLM-backed crisis classifier (post-MVP second layer) | ⬜ | v0.5.0+ |

---

## LLM providers

| Feature | Status | Notes |
|---|---|---|
| `LLMProvider` protocol | ✅ | `src/orchestrator/providers.py` |
| Deterministic `EchoProvider` | ✅ | Offline fallback, test backbone, last-resort in fallback chain |
| Ollama (local + cloud) | 🔵 | Phase 1 — async httpx wrapper |
| Anthropic Claude | 🔵 | Phase 1 — Haiku 4.5 as rubric-eval default |
| OpenAI | 🔵 | Phase 1 |
| OpenRouter (GLM 4.5 Air as block-gen default) | 🔵 | Phase 1 |
| Task-level model routing | 🔵 | Phase 2 — `TaskKind` enum + `ModelRouter` |
| Fallback chain ending at `EchoProvider` | 🔵 | Phase 2 — Ollama → OpenAI → Anthropic → OpenRouter → Echo |
| Per-task cost logging | 🔵 | Phase 6 — via `SchedulerRunStore` |

---

## Orchestration

| Feature | Status | Notes |
|---|---|---|
| Versioned `PromptLibrary` with SOUL.md-quoting core template | ✅ | `src/orchestrator/prompts.py` |
| `ReasoningChain` with outbound boundary enforcement | ✅ | `src/orchestrator/chain.py` |
| Live content generator for pathway, block, check | 🟡 | `src/curriculum/live_generator.py` — not yet wired into session loop; moves to `src/orchestrator/live_content.py` in Phase 2 |
| Per-learner context assembly (from brain) | 🔵 | Phase 4 — `build_learner_context()` |
| Snapshot tests for prompt templates | 🔵 | Phase 2 — catches silent prompt drift |

---

## API surface

| Feature | Status | Notes |
|---|---|---|
| `POST /sessions` (onboard) | ✅ | |
| `GET /sessions/{id}` | ✅ | |
| `POST /sessions/{id}/calibration-answer` | ✅ | |
| `POST /sessions/{id}/finish-calibration` | ✅ | |
| `POST /sessions/{id}/next` | ✅ | |
| `POST /sessions/{id}/check-answer` | ✅ | |
| `POST /sessions/{id}/close` | ✅ | |
| `POST /sessions/{id}/socratic` (free-form dialogue) | 🔵 | Phase 5 |
| `POST /learners/{id}/resume` (warm-start) | 🔵 | Phase 7 |
| `GET /learners/{id}/wiki/{concept}` | 🔵 | Phase 7 |
| `GET /learners/{id}/queue` | 🔵 | Phase 7 |
| `POST /learners/{id}/capture` | 🔵 | Phase 7 |
| `GET /admin/scheduler` | 🔵 | Phase 6 |
| `GET /health` | ✅ | HEARTBEAT-backed status |
| Profile + admin routers | ✅ | |
| OpenAPI `/docs` interactive | ✅ | FastAPI default |

---

## Persistence

| Feature | Status | Notes |
|---|---|---|
| In-memory `AppState` with thread-safe CRUD | ✅ | `src/api/state.py` |
| SQLite persistence (WAL mode) | 🔵 | Phase 3 |
| In-process identity cache over SQLite | 🔵 | Phase 3 — preserves mutation-in-place semantics |
| `~/.claw-stu/` data directory with 0700 perms | 🔵 | Phase 1 |
| `~/.claw-stu/secrets.json` with 0600 perms | 🔵 | Phase 1 |
| Atomic writes via temp-file-and-rename | ✅ | Used for profile export |
| Windows permissions handling (WARN + no-op) | 🔵 | Phase 1 |

---

## Distribution

| Feature | Status | Notes |
|---|---|---|
| `pip install clawstu` on PyPI | 🔵 | Phase 1 |
| Hatchling build backend | 🔵 | Phase 1 — replaces setuptools |
| `clawstu serve / scheduler / profile / doctor` CLI | 🔵 | Phase 1 |
| GitHub Actions CI (test + lint + type) | ✅ | `.github/workflows/ci.yml` |
| GitHub Actions PyPI publish job on `v*` tags | 🔵 | Phase 1 — gated on tests passing |
| Optional one-line installer script | ⬜ | Post-MVP — `curl | bash` pattern |
| Docker image | ⬜ | Post-MVP |
| Offline-install bundle for no-internet deployments | ⬜ | v0.9.0 |

---

## Frontend

| Feature | Status | Notes |
|---|---|---|
| Any frontend at all | ⬜ | v0.3.0 — React + Tailwind, mobile-first |
| Guardian dashboard | ⬜ | v0.4.0 — read-only compiled-truth summary |
| Native mobile app | ❌ | Explicitly deferred |

---

## What Claw-STU explicitly will NEVER do

- **Voice-based "friend" interface that simulates emotional intimacy.** Stuart
  is a tool. Warm, honest, useful — but not a friend, peer, or authority
  figure. Voice may arrive as an accessibility feature one day; it will not
  arrive as a social one.
- **Telemetry, ads, behavioral tracking for third parties.** No. Not for any
  revenue model. Not for any growth metric.
- **Multi-tenant hosted SaaS as the primary deployment path.** Claw-STU is a
  tool you run on your own machine (or your family's, or your classroom's).
  A hosted offering may exist as a convenience one day; the core project
  will always be self-hostable.
- **A cryptocurrency, NFT, or "Learn-to-Earn" tokenomics layer.** No.
- **Crisis counseling.** If a student expresses distress, Stuart surfaces
  human resources (988, Crisis Text Line, Childhelp, trusted adult) and
  steps completely out of the teach role. Stuart does not attempt to
  counsel, de-escalate, or intervene. This is a hard SOUL.md constraint.
- **A "good / bad / struggling" student label.** The learner profile
  describes current state per-domain so Stuart can adapt. It is not a
  diagnosis, a classification, or a gradebook.
- **Data sharing with any institution (school, district, state) without
  explicit learner and guardian consent.** The learner profile is owned by
  the learner. Portable, exportable, deletable. Period.

---

*Every kid deserves a Stuart. Made by a teacher in New York.*
