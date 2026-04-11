---
title: "Claw-STU: Providers, Memory, Proactive Agent — Design Spec"
date: 2026-04-11
status: proposed
author: Claw-STU team
related:
  - ../../../SOUL.md
  - ../../../HEARTBEAT.md
  - ../../../Handoff.md
  - ../../../README.md
---

# Claw-STU: Providers, Memory, Proactive Agent

## 0. Context

Claw-STU is a personal learning agent (persona name: **Stuart**) that serves the
learner directly, independent of any institution. It is the student-facing
counterpart to Claw-ED (the teacher-facing agent). Where Claw-ED asks *"how does
this teacher teach?"*, Claw-STU asks *"how does this student learn?"* and adapts
continuously.

The project's non-negotiables are written in `SOUL.md` and `HEARTBEAT.md` and
are not revisited here. Every design decision in this document must be
consistent with both files. In particular:

- **Stuart is a cognitive tool**, not a friend, therapist, peer, or authority
  figure. This is not tunable.
- **ZPD calibration** is the instructional loop. Every adaptive decision is
  grounded in the learner profile.
- **Re-teach must use a different modality than the one that failed.** This is
  the first test that must pass, and it already does
  (`tests/test_foundational_reteach.py`).
- **Import hierarchy is strictly layered.** Lower layers never import from
  higher layers.
- **No swallowed exceptions, no functions over ~50 lines, tests land with
  code, no PII in logs.**

This document extends (does not replace) those contracts.

## 1. Current state (2026-04-11)

The repository already ships a working deterministic MVP:

- **Learner profile engine** — `src/profile/` has `AgeBracket`, `Domain`,
  `Modality`, `ComplexityTier`, `EventKind`, `ObservationEvent`,
  `ModalityOutcome`, `ZPDEstimate`, `LearnerProfile`, `Observer`,
  `ZPDCalibrator`, JSON round-trip export/import.
- **Session loop** — `src/engagement/session.py` runs the full lifecycle
  (onboard → calibrate → teach → check → adapt → close) deterministically. The
  reteach-on-failure modality-rotation invariant is enforced in
  `ModalityRotator.rotate_after_failure` and covered by
  `test_foundational_reteach.py` (two test functions, both green).
- **Assessment** — `src/assessment/` generates calibration items, evaluates
  responses (including CRQ rubrics), and produces feedback.
- **Safety** — `src/safety/` ships `ContentFilter` (age-bracket blocklist),
  `EscalationHandler` (self-harm / abuse / acute distress patterns with
  988/741741/Childhelp resource packet), and `BoundaryEnforcer` (outbound
  sycophancy/emotional-claim detector). Every generated string must pass both
  the content filter and the outbound boundary enforcer before it reaches the
  student.
- **Orchestrator scaffolding** — `src/orchestrator/providers.py` defines the
  `LLMProvider` protocol and a deterministic `EchoProvider`.
  `src/orchestrator/prompts.py` registers versioned prompt templates quoting
  SOUL.md. `src/orchestrator/chain.py` wraps a provider with outbound boundary
  enforcement.
- **Live content generator** — `src/curriculum/live_generator.py` (393 lines)
  can produce pathway + block + check for any topic. Parses strict JSON.
  Routes every generated string through a safety gate. Has offline fallbacks
  triggered by `isinstance(provider, EchoProvider)` so the module is testable
  without a network.
- **FastAPI surface** — `POST /sessions`, calibration-answer, finish-calibration,
  next, check-answer, close. Plus a profile router and an admin router. In-
  memory session store at `src/api/state.py`.
- **Test suite** — 73 tests passing in 0.16s. `mypy --strict`-style typing
  throughout. 80% coverage floor enforced by `pyproject.toml`.

The pieces that **do not yet exist** and that this design spec covers:

1. **Real LLM providers** (only `EchoProvider` is concrete today).
2. **Task-level model routing** (every call site hard-codes `EchoProvider`).
3. **`AppConfig`** with env + file loading, data directory, secrets layout.
4. **Live content wired into the session loop** (`LiveContentGenerator` exists
   but `SessionRunner` uses the deterministic `ContentSelector` only, so
   free-text topics don't reach the API).
5. **Crisis wiring** — `EscalationHandler` is defined but **no code path calls
   it** on inbound student text. This is a current HEARTBEAT invariant
   violation: today, a student posting "I want to die" to
   `/sessions/{id}/calibration-answer` would be scored as incorrect and
   re-taught. This spec closes that gap.
6. **Memory system** — no brain store, no knowledge graph, no wiki, no
   embeddings-backed retrieval, no cross-session learning.
7. **Persistence** — `src/api/state.py` is in-memory. Nothing survives a
   restart.
8. **Proactive scheduler** — no background work. Stuart is purely
   request/response today.
9. **Warm-start session resume** — no way to pick up where you left off.

## 2. Goals and non-goals

### Goals

G1. **Real LLM providers.** Claw-STU can make requests to Ollama (local +
    cloud), Anthropic, OpenAI, and OpenRouter (where GLM 5.1 lives) as concrete
    `LLMProvider` implementations.

G2. **Task-level routing.** A `TaskKind` enum names the pedagogical jobs
    (socratic dialogue, block generation, check generation, rubric evaluation,
    pathway planning, content classification). A `ModelRouter` maps each
    `TaskKind` to a configured provider + model, resolved from `AppConfig`.
    Routing is a config change, not a code change.

G3. **Configuration and storage.** Env vars first, then
    `~/.claw-stu/secrets.json` (0600), then defaults. A `~/.claw-stu/` data
    directory (0700) holds secrets, the brain, cached models, and the SQLite
    database.

G4. **Live topics end-to-end.** A learner can start a session on any free-text
    topic (e.g., "The Haitian Revolution", "the water cycle"). The session
    loop uses `LiveContentGenerator` for pathway + blocks + checks when a topic
    is supplied, and retains the deterministic path when it is not. The 73
    existing tests stay green.

G5. **Crisis wiring closed.** Every route that accepts student text runs
    `InboundSafetyGate` before any evaluator or orchestrator call. On crisis
    detection, the session moves to a new `CRISIS_PAUSE` phase, returns the
    crisis-resource message, and refuses to advance the teach loop until
    explicitly resumed.

G6. **Memory system.** A `src/memory/` package gives Stuart a brain: per-learner
    markdown pages with the compiled-truth-plus-timeline pattern, hybrid
    keyword+vector search using ONNX MiniLM embeddings (core dependency, not an
    optional extra), a knowledge graph of concept relationships, and
    per-learner concept wikis that answer the SOUL.md §6 transparency question
    ("why did you show me this?").

G7. **Proactive scheduler.** A `src/scheduler/` package backed by APScheduler
    runs inside the FastAPI lifespan (one process, one lifecycle). Five initial
    tasks: `dream_cycle`, `prepare_next_session`, `spaced_review`,
    `refresh_zpd`, `prune_stale`. Every task is idempotent, logs structured
    telemetry with no PII, and reports token cost per run.

G8. **Warm-start session resume.** `POST /learners/{id}/resume` consumes a
    `NextSessionArtifact` pre-generated by the scheduler and returns a block in
    under 200ms with no LLM call in the hot path.

G9. **Persistence.** A `src/persistence/` package wraps SQLite (WAL mode) with a
    schema for learners, sessions, observation events, ZPD estimates, modality
    outcomes, next-session artifacts, knowledge graph triples, misconception
    tallies, and scheduler runs. Brain pages live on disk as markdown under
    `~/.claw-stu/brain/`.

G10. **All HEARTBEAT invariants enforced.** Import hierarchy remains strict
    (`safety → profile → memory → assessment / curriculum / engagement →
    orchestrator → api`, with `persistence` as a sibling of `memory` that
    lower layers may use). No swallowed exceptions, no functions over 50 lines,
    every new module ships with tests, `mypy --strict` clean, `ruff check`
    clean, 80% coverage floor, no PII in logs.

### Non-goals (explicitly out of scope for this pass)

N1. **Frontend.** No React, no web UI, no mobile app. FastAPI + JSON is the
    full user-visible surface. A thin frontend can land as a follow-up.

N2. **Guardian dashboard.** The Handoff.md vision lists a guardian dashboard
    as post-MVP. This spec does not ship one. The API surface it would consume
    (`GET /admin/scheduler`, `GET /learners/{id}/queue`,
    `GET /learners/{id}/wiki/{concept}`) does land, so a dashboard can be
    wired later without backend changes.

N3. **Games, simulations, video integration.** Post-MVP per Handoff.md.

N4. **Multi-subject expansion.** The seed library stays US History only.
    Live-topic sessions can cover anything, but the deterministic fallback
    does not grow new subjects in this pass.

N5. **Claw-ED ↔ Claw-STU handoff.** Post-MVP per Handoff.md. Profiles are
    not shared between the two projects in this pass.

N6. **Serverless deployment.** The scheduler lives inside the FastAPI
    lifespan, which requires a long-running process (uvicorn, Docker, or a
    VPS). Vercel / Cloudflare Workers / Lambda are out of scope. A follow-up
    can extract the scheduler to `src/scheduler/__main__.py` as a standalone
    daemon if needed.

N7. **LLM-backed crisis classifier.** `EscalationHandler` stays regex-only for
    now. An LLM-backed second layer is documented in `escalation.py` as
    post-MVP and remains so.

N8. **Auth beyond the existing pattern.** No OAuth, no login, no RBAC. The
    student identifies themselves with a `learner_id` and owns their profile.
    Admin routes are gated by an env-var token (same pattern Claw-ED uses for
    its unauth-by-default dev mode).

N9. **I18n / localization.** Prompts, crisis resources (988, 741741,
    Childhelp) are US-English only. Localized resource lists are documented as
    a follow-up in `escalation.py`.

## 3. Principles honored

P1. **Explicit over clever** (HEARTBEAT.md). Where Claw-ED's `llm.py` is a
    1002-line `if/elif` dispatch across providers, Claw-STU gets one file per
    provider, each under ~200 lines, each with one concern.

P2. **Function size discipline** (HEARTBEAT.md). No function over ~50 lines.
    Complex logic is decomposed.

P3. **No swallowed exceptions** (HEARTBEAT.md). Every `except` handles a
    specific exception class or re-raises. The existing
    `src/orchestrator/providers.py::ProviderError` stays loud.

P4. **Tests land with code** (HEARTBEAT.md). Every new module lands with its
    test file in the same commit. The 73 existing tests must remain green
    throughout every phase.

P5. **Observational, not self-reported** (Handoff.md). No new profile fields
    come from forms. Every profile mutation is derived from an
    `ObservationEvent` processed by the `Observer`.

P6. **Stuart is not a tutor** (SOUL.md). The word "tutor" does not appear in
    any new code comment, prompt template, or user-visible string. Stuart is
    a cognitive tool. Voice and behavior scale to age bracket, never to
    personality.

P7. **Transparency** (SOUL.md §6). Every adaptive decision Stuart makes is
    traceable back to the learner profile and the brain. The wiki endpoint
    is the user-visible proof of this.

P8. **No PII in logs** (HEARTBEAT.md). Learner IDs are hashed before logging.
    Raw student utterances never appear in log output.

P9. **Safety is foundational, not a feature flag** (Handoff.md). Two filters,
    one each direction, neither optional. `InboundSafetyGate` before
    orchestrator. `BoundaryEnforcer` + `ContentFilter` on every outbound
    string.

## 4. Architecture

### 4.1 Revised import hierarchy

```
                         safety
                            │
                            ▼
                         profile
                            │
                            ▼
                         memory ──────────── persistence
                            │                     ▲
                            ▼                     │
             assessment   curriculum   engagement │
                 │            │            │      │
                 └────────────┼────────────┘      │
                              ▼                   │
                         orchestrator             │
                              │                   │
                              ▼                   │
                             api ─────────────────┘
                              │
                              ▼
                         scheduler  (uses api.state, lives in lifespan)
```

`persistence` is a sibling utility that `memory`, `assessment`, `curriculum`,
`engagement`, `orchestrator`, `api`, and `scheduler` may all depend on, but
which depends on nothing else inside `src/`. It has no pedagogical content;
it is a SQLite access layer.

`memory` depends only on `safety`, `profile`, and `persistence`. It does not
import from `assessment`, `curriculum`, `engagement`, `orchestrator`, or `api`.

`scheduler` depends on `orchestrator` (for the router), `memory`, `persistence`,
and `engagement`. It lives one level below `api` because `api` starts the
scheduler inside its lifespan, but the scheduler never reaches back into
`api` — it works against `persistence` and `memory` directly.

### 4.2 Orchestrator: providers + router + config

#### 4.2.1 Files

```
src/orchestrator/
├── providers.py            # (existing) Protocol + EchoProvider
├── provider_ollama.py      # NEW
├── provider_anthropic.py   # NEW
├── provider_openai.py      # NEW
├── provider_openrouter.py  # NEW (GLM 5.1 lives here)
├── router.py               # NEW — TaskKind enum + ModelRouter
├── config.py               # NEW — AppConfig + env/file loader
├── prompts.py              # (existing)
└── chain.py                # MODIFIED — takes router, not provider
```

Each provider file is roughly 150-200 lines. Each one implements the existing
`LLMProvider` protocol (`name: str`, `complete(system, messages, max_tokens,
temperature) -> LLMResponse`). Each one raises `ProviderError` on failure.
Each one uses `httpx.AsyncClient` with `timeout=30.0`, retries are handled by
`ModelRouter`, not the provider itself.

#### 4.2.2 `TaskKind`

```python
class TaskKind(str, Enum):
    SOCRATIC_DIALOGUE    = "socratic_dialogue"    # short, cheap, latency-sensitive
    BLOCK_GENERATION     = "block_generation"     # quality-sensitive, slower
    CHECK_GENERATION     = "check_generation"     # structured JSON
    RUBRIC_EVALUATION    = "rubric_evaluation"    # accuracy-critical CRQ scoring
    PATHWAY_PLANNING     = "pathway_planning"     # strict JSON, small
    CONTENT_CLASSIFY     = "content_classify"     # second-layer safety, cheap, local preferred
    DREAM_CONSOLIDATION  = "dream_consolidation"  # overnight compiled-truth rewrite
```

#### 4.2.3 `ModelRouter`

Stateless. Holds `{TaskKind → provider_name → model_name}` resolved at
construction time from `AppConfig`. Only public method:

```python
class ModelRouter:
    def for_task(self, kind: TaskKind) -> tuple[LLMProvider, str]:
        """Return the provider and model to use for this task.

        Respects a fallback chain: if the primary provider for a task is
        unreachable or misconfigured, falls through to the next provider in
        AppConfig.fallback_chain, ending at EchoProvider.
        """
```

`ReasoningChain.__init__` changes from `provider: LLMProvider` to
`router: ModelRouter`. `LiveContentGenerator.__init__` makes the same change.
Call sites that currently pass an `EchoProvider` instance use a tiny helper
`router_for_testing(provider: LLMProvider) -> ModelRouter` to wrap it — one
line per test.

#### 4.2.4 Default task routing (shipped in `config.py` defaults)

| Task | Default provider | Default model | Rationale |
|---|---|---|---|
| `SOCRATIC_DIALOGUE` | `ollama` (local) | `llama3.2` | Short, latency-sensitive; local = instant + free |
| `BLOCK_GENERATION` | `openrouter` | `z-ai/glm-4.5-air` | Cheap + strong prose |
| `CHECK_GENERATION` | `openrouter` | `z-ai/glm-4.5-air` | Same |
| `RUBRIC_EVALUATION` | `anthropic` | `claude-3-5-haiku-20241022` | Accuracy-critical; cheapest Claude |
| `PATHWAY_PLANNING` | `openrouter` | `z-ai/glm-4.5-air` | Small JSON, cheap |
| `CONTENT_CLASSIFY` | `ollama` (local) | `llama3.2` | Safety should never depend on a network |
| `DREAM_CONSOLIDATION` | `openrouter` | `z-ai/glm-4.5-air` | Batch overnight; cost matters |

Any user without a given API key gets the next provider in
`fallback_chain: ["ollama", "openai", "anthropic", "openrouter"]`, ending at
`EchoProvider` as the last-resort fallback so the session loop never
hard-crashes on provider outage.

#### 4.2.5 `AppConfig`

```python
class AppConfig(BaseModel):
    data_dir: Path = Path.home() / ".claw-stu"
    primary_provider: str = "ollama"
    fallback_chain: tuple[str, ...] = ("ollama", "openai", "anthropic", "openrouter")
    task_routing: dict[TaskKind, TaskRoute] = Field(default_factory=_default_task_routing)
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # ... etc
```

Loaded via:
```python
def load_config() -> AppConfig:
    """Env vars first, then ~/.claw-stu/secrets.json (0600), then defaults."""
```

`load_config()` does not raise if `~/.claw-stu/secrets.json` is missing —
it logs a debug message and continues with env + defaults. If the file exists
with the wrong permissions (not 0600), it logs a WARN and proceeds (because a
hard fail would lock users out; a WARN gives them a chance to fix it).

### 4.3 Memory: brain + knowledge graph + wiki

#### 4.3.1 Files

```
src/memory/
├── __init__.py
├── store.py              # BrainStore — CRUD + atomic writes
├── search.py             # hybrid_search — keyword + vector + RRF
├── embeddings.py         # ONNX MiniLM wrapper (core dep)
├── context.py            # build_learner_context()
├── writer.py             # write_session_to_memory()
├── dream.py              # dream cycle body (called by scheduler task)
├── capture.py            # capture_source() — student-shared materials
├── knowledge_graph.py    # KG triples — SQLite via persistence
├── wiki.py               # generate_concept_wiki()
└── pages/
    ├── __init__.py
    ├── base.py           # BrainPage base + YAML frontmatter render/parse
    ├── learner.py
    ├── concept.py
    ├── session.py
    ├── source.py
    ├── misconception.py
    └── topic.py
```

#### 4.3.2 Brain pages

Each page type is a small pydantic model with a markdown renderer. All pages
share the two-section structure:

```markdown
---
kind: learner
learner_id: hashed
updated_at: 2026-04-11T14:23:00Z
schema_version: 1
---

# Compiled Truth

(Stuart's current best understanding of this student / concept / session.
Rewritten on update. This is what gets pulled into LLM context.)

# Timeline

- 2026-04-11T14:20:00Z — calibration_answer — correct — tier=meeting
- 2026-04-11T14:21:30Z — check_for_understanding — incorrect — tier=meeting
- ...
```

`BrainPage.render()` produces the markdown string. `BrainPage.parse(text)` is
the inverse. `BrainStore` writes atomically via temp-file-and-rename (same
pattern Claw-ED uses for its brain pages).

Page types:
- **`LearnerPage`** — who this student is, how they learn, strengths,
  pacing, modality preferences.
- **`ConceptPage`** — what Stuart knows about this concept (HAPP framing,
  tied sources, known misconceptions) plus this student's state (tier, samples,
  last-seen).
- **`SessionPage`** — one-page history of a completed session.
- **`SourcePage`** — a primary source with title, attribution, HAPP fields,
  age-bracket tag, and the concepts it belongs to.
- **`MisconceptionPage`** — a specific wrong-answer pattern, cross-linked to
  the concepts it affects and the sessions where it showed up.
- **`TopicPage`** — a cluster of related concepts. E.g., "Reform Movements"
  groups abolition, suffrage, labor, temperance.

#### 4.3.3 Embeddings

ONNX MiniLM (specifically `sentence-transformers/all-MiniLM-L6-v2`) is a
**core dependency**, not an optional extra. `onnxruntime` ships in
`pyproject.toml`'s base `dependencies`. The model file (~90MB) is downloaded
on first server startup into `~/.claw-stu/models/` and cached. First-run
bootstrap runs in a background thread at server startup; `search.py`
degrades to keyword-only for the first N seconds while the download
completes, logging progress via structured events.

`embeddings.py` exposes:
```python
class Embeddings:
    def __init__(self, model_dir: Path) -> None: ...
    def is_ready(self) -> bool: ...
    def encode(self, text: str) -> np.ndarray: ...  # shape (384,)
    def encode_batch(self, texts: list[str]) -> np.ndarray: ...  # shape (N, 384)
```

#### 4.3.4 Hybrid search

`search.py::hybrid_search(query, top_k)` returns pages ranked by Reciprocal
Rank Fusion of:
1. **Keyword search** over page text (SQLite FTS5 over a materialized index).
2. **Vector search** over page-level embeddings (cosine similarity against
   the embeddings table).

RRF constant `k=60` matches Claw-ED's pattern. If embeddings aren't ready
yet (first-run download), vector search returns empty and RRF degenerates
to keyword-only.

#### 4.3.5 Context assembly

```python
def build_learner_context(
    *,
    learner_id: str,
    concept: str,
    topic: str | None = None,
    max_chars: int = 3000,
) -> LearnerContext:
    """Return the page bundle to inject into a provider call.

    Pulls (in order of priority, bounded by max_chars):
    - LearnerPage compiled-truth — always
    - ConceptPage compiled-truth for the target concept — always
    - Related ConceptPages via KG prerequisite_for (depth 1)
    - Last 3 SessionPages for this learner
    - MisconceptionPages flagged on this concept
    - SourcePages tagged to this concept, filtered by age bracket
    """
```

The returned `LearnerContext` is rendered into the system prompt alongside
`SOUL_CORE` by `ReasoningChain` before every provider call.

#### 4.3.6 Write path

`writer.py::write_session_to_memory(profile, session, brain_store)` runs on
every session close and:

1. Creates a `SessionPage` for the session.
2. Updates the `LearnerPage` compiled truth (reading the observer's
   accumulated signals).
3. For each concept the session touched: updates the `ConceptPage` with the
   student's new state.
4. For each wrong answer tied to a concept: creates or increments a
   `MisconceptionPage`.
5. Writes KG triples: `(concept, taught_in, session_id)`, `(session_id,
   includes, concept)`.

#### 4.3.7 Dream cycle

`dream.py::dream_cycle(learner_id, router, brain_store, persistence)` runs
overnight via the scheduler:

1. For each `BrainPage` touched since the last dream cycle run:
   - Rewrite the Compiled Truth section from the Timeline, using
     `router.for_task(TaskKind.DREAM_CONSOLIDATION)`.
   - Compare to existing compiled truth. If the diff is meaningful (length
     change > 10% OR a new concept is mentioned), save the rewritten page.
   - Otherwise: no-op, skip (idempotency).
2. Detect concept gaps: concepts in the learner's recent pathway whose KG
   prerequisites haven't been taught. Push those to the learner's
   review queue via `persistence`.
3. Re-index embeddings for any page whose compiled-truth changed.
4. Log a structured report: pages rewritten, pages skipped, gap count,
   token cost, duration.

#### 4.3.8 Per-learner concept wiki

`wiki.py::generate_concept_wiki(learner_id, concept) -> str` returns a
markdown document showing:

- What Stuart knows about the concept (from `ConceptPage` compiled truth).
- What *this student* knows about the concept (from their ConceptPage state
  + session references).
- Recent sessions where this student worked on the concept (with links).
- Open misconceptions (with the specific wrong-answer patterns).
- Tied primary sources (filtered to the student's age bracket).

This IS the answer to "why did you show me this?" — it's the user-visible
manifestation of the SOUL.md §6 transparency invariant.

### 4.4 Live content wiring

#### 4.4.1 `OnboardRequest` grows a `topic` field

```python
class OnboardRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=128)
    age: int = Field(ge=5, le=120)
    domain: Domain
    topic: str | None = Field(default=None, max_length=200)  # NEW
```

#### 4.4.2 `SessionRunner` branches on `topic`

```python
def onboard(
    self,
    *,
    learner_id: str,
    age: int,
    domain: Domain,
    topic: str | None = None,
) -> tuple[LearnerProfile, Session]:
    ...
```

- If `topic is None`: existing deterministic path
  (`PathwayPlanner.plan(domain, profile)` + `ContentSelector.select(...)` from
  the seed library + seed library checks).
- If `topic is not None`: live path
  (`LiveContentGenerator.generate_pathway(topic, age_bracket)` +
  `LiveContentGenerator.generate_block(...)` +
  `LiveContentGenerator.generate_check(...)`).

`SessionRunner.__init__` gains a new optional parameter
`live_content: LiveContentGenerator | None = None`. Defaults to None so the 73
existing tests don't need to touch it. When `topic is not None` and
`live_content is None`, the session raises an explicit
`LiveContentUnavailableError` rather than silently falling back.

#### 4.4.3 Context-aware live generation

Every call into `LiveContentGenerator` is preceded by a
`build_learner_context(learner_id, concept)` call so the brain's compiled
truth about this learner is injected into the system prompt. This closes the
loop: the second time a student asks about the Haitian Revolution, Stuart
knows what they already understood from last week.

#### 4.4.4 Tests

`tests/test_session_flow.py` grows a `TestLiveTopicPath` class with three
tests:
- Topic = "Haitian Revolution" → full onboard + calibrate + teach + check
  cycle succeeds via `EchoProvider` offline stubs.
- Topic = "Water cycle" → same.
- Topic = "Mitosis" → same.

All run under 1s, no network.

### 4.5 Crisis wiring

#### 4.5.1 `src/safety/gate.py` — the choke point

```python
class InboundDecision:
    @staticmethod
    def allow() -> InboundDecision: ...
    @staticmethod
    def crisis(detection: CrisisDetection) -> InboundDecision: ...
    @staticmethod
    def boundary(violation: BoundaryViolation) -> InboundDecision: ...

class InboundSafetyGate:
    def __init__(
        self,
        escalation: EscalationHandler,
        boundaries: BoundaryEnforcer,
    ) -> None: ...

    def scan(self, text: str) -> InboundDecision:
        """Scan student-provided text. Returns the decision."""
```

#### 4.5.2 Wired into every student-text entry point

- `POST /sessions/{id}/calibration-answer`
- `POST /sessions/{id}/check-answer`
- `POST /sessions/{id}/socratic` (new free-form dialogue route)
- `POST /learners/{id}/capture` (new student-shared source route)

Each handler runs `gate.scan(request.response)` (or equivalent field) before
any other logic. On CRISIS, it:
1. Does NOT call the evaluator or the orchestrator.
2. Sets `session.phase = SessionPhase.CRISIS_PAUSE`.
3. Returns HTTP 200 with body `{"crisis": true, "resources": "..."}` where
   `resources` comes from `EscalationHandler.resources(detection)`.
4. Logs a structured event: `{event: "crisis_detected", kind, session_id,
   learner_id_hash}` — no raw text, no PII.

On BOUNDARY: returns HTTP 400 with a generic refusal message, logs the
violation kind (no raw text).

#### 4.5.3 New session phase

```python
class SessionPhase(str, Enum):
    ONBOARDING    = "onboarding"
    CALIBRATING   = "calibrating"
    TEACHING      = "teaching"
    CHECKING      = "checking"
    CRISIS_PAUSE  = "crisis_pause"  # NEW
    CLOSING       = "closing"
    CLOSED        = "closed"
```

`SessionRunner.next_directive` returns a directive with only the crisis
message (no block, no check) when phase is `CRISIS_PAUSE`. The session can
be closed normally; resuming requires an explicit admin action.

#### 4.5.4 Tests

Six new tests in `test_safety.py`:
- `test_crisis_utterance_halts_calibration`
- `test_crisis_utterance_halts_check`
- `test_crisis_utterance_halts_socratic`
- `test_crisis_paused_session_refuses_next_directive`
- `test_boundary_violation_logs_and_refuses`
- `test_non_crisis_text_passes_through` (regression)

Plus `test_inbound_safety_gate.py` as a standalone unit test file.

### 4.6 Persistence

#### 4.6.1 Files

```
src/persistence/
├── __init__.py
├── schema.py       # CREATE TABLE statements
├── store.py        # PersistentStore — typed CRUD wrappers
├── migrations.py   # Minimal migration runner
└── connection.py   # SQLite connection factory + WAL + pragmas
```

#### 4.6.2 Schema

```sql
CREATE TABLE learners (
    learner_id TEXT PRIMARY KEY,
    age_bracket TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES learners(learner_id),
    domain TEXT NOT NULL,
    topic TEXT,
    phase TEXT NOT NULL,
    pathway_json TEXT,
    started_at TEXT NOT NULL,
    closed_at TEXT,
    crisis_paused INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE observation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id TEXT NOT NULL,
    session_id TEXT,
    kind TEXT NOT NULL,
    domain TEXT NOT NULL,
    modality TEXT,
    tier TEXT,
    correct INTEGER,
    latency_seconds REAL,
    concept TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE zpd_estimates (
    learner_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    tier TEXT NOT NULL,
    confidence REAL NOT NULL,
    samples INTEGER NOT NULL,
    last_updated TEXT NOT NULL,
    PRIMARY KEY (learner_id, domain)
);

CREATE TABLE modality_outcomes (
    learner_id TEXT NOT NULL,
    modality TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    successes INTEGER NOT NULL,
    total_latency REAL NOT NULL,
    PRIMARY KEY (learner_id, modality)
);

CREATE TABLE next_session_artifacts (
    learner_id TEXT PRIMARY KEY,
    pathway_json TEXT NOT NULL,
    first_block_json TEXT NOT NULL,
    first_check_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE knowledge_graph_triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_session TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_kg_subject ON knowledge_graph_triples(subject);
CREATE INDEX idx_kg_object ON knowledge_graph_triples(object);

CREATE TABLE misconception_tally (
    learner_id TEXT NOT NULL,
    concept TEXT NOT NULL,
    count INTEGER NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (learner_id, concept)
);

CREATE TABLE scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    learner_id_hash TEXT,
    outcome TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    token_cost_input INTEGER NOT NULL DEFAULT 0,
    token_cost_output INTEGER NOT NULL DEFAULT 0,
    run_at TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE page_embeddings (
    page_key TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE page_text_index USING fts5(page_key, text);
```

All `TEXT` timestamps are ISO-8601 UTC. WAL mode enabled via connection
pragma. Foreign keys enabled via `PRAGMA foreign_keys = ON`.

#### 4.6.3 `PersistentStore`

One small typed wrapper per entity (`LearnerStore`, `SessionStore`,
`EventStore`, `ArtifactStore`, `KGStore`, `MisconceptionStore`,
`SchedulerRunStore`). No ORM. Each method takes pydantic models in and
returns pydantic models out. Raw SQL is kept in `schema.py` and
`store.py`; nothing outside `persistence` writes SQL directly.

#### 4.6.4 Interaction with `src/api/state.py`

`api/state.py` keeps the same public interface (`AppState.put`,
`AppState.get`, `AppState.drop`) but delegates to `PersistentStore` by default.
A test-only `InMemoryStore` matches the same interface and is wired via a
pytest fixture so existing tests keep running without touching SQLite.

### 4.7 Scheduler

#### 4.7.1 Files

```
src/scheduler/
├── __init__.py
├── runner.py             # SchedulerRunner — APScheduler wrapper
├── registry.py           # TaskRegistry + TaskSpec
├── context.py            # ProactiveContext
└── tasks/
    ├── __init__.py
    ├── dream_cycle.py
    ├── prepare_next_session.py
    ├── spaced_review.py
    ├── refresh_zpd.py
    └── prune_stale.py
```

#### 4.7.2 `TaskSpec`

```python
class TaskSpec(BaseModel):
    name: str
    cron: str            # "30 2 * * *" — local time
    enabled: bool = True
    description: str
    run_fn: Callable[[ProactiveContext, str], Awaitable[TaskReport]]
```

#### 4.7.3 `ProactiveContext`

```python
@dataclass
class ProactiveContext:
    router: ModelRouter
    brain_store: BrainStore
    persistence: PersistentStore
    logger: StructuredLogger
```

Passed to every task. Tasks never construct their own providers or stores
— they get them from the context. This makes tests trivial: the test fixture
constructs a `ProactiveContext` with an in-memory brain and a
`router_for_testing(EchoProvider())` and runs any task end-to-end in
milliseconds.

#### 4.7.4 `TaskReport`

```python
class TaskReport(BaseModel):
    task_name: str
    learner_id_hash: str | None  # None for global tasks like prune_stale
    outcome: Literal["success", "skipped_current", "failed"]
    duration_ms: int
    token_cost: TokenCost = Field(default_factory=TokenCost)
    error_message: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
```

Every report is persisted via `SchedulerRunStore.record(report)`. The admin
endpoint reads these back for the transparency view.

#### 4.7.5 Five initial tasks

| Task | Schedule | TaskKind | Notes |
|---|---|---|---|
| `dream_cycle` | `30 2 * * *` | `DREAM_CONSOLIDATION` | Idempotent: skip if no page touched since last run |
| `prepare_next_session` | `15 3 * * *` | `BLOCK_GENERATION`, `CHECK_GENERATION` | Idempotent: skip if artifact exists |
| `spaced_review` | `45 3 * * *` | none | Pure Python, logic-only |
| `refresh_zpd` | `0 4 * * *` | none | Recomputes ZPD from full event history |
| `prune_stale` | `0 5 * * 0` | none | Closes sessions idle > 30d |

All tasks run in a loop over `learners_with_recent_activity` (defined as
`last_active_at > now - 14 days`). A learner who doesn't use Stuart for two
weeks costs zero.

#### 4.7.6 Lifecycle

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = SchedulerRunner(registry=default_registry(), context=build_context())
    await scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        await scheduler.stop()
```

One process, one lifecycle. Scheduler starts when uvicorn starts and stops
cleanly when uvicorn stops.

### 4.8 Warm-start

#### 4.8.1 `SessionRunner.warm_start`

```python
def warm_start(
    self,
    *,
    learner_id: str,
    persistence: PersistentStore,
) -> tuple[LearnerProfile, Session]:
    """Resume a learner from a pre-generated NextSessionArtifact.

    1. Load LearnerProfile from persistence.
    2. Load the most recent NextSessionArtifact for this learner.
    3. Construct a Session pre-loaded with the pathway, first block,
       first check, and phase=TEACHING.
    4. Mark the artifact consumed.
    5. Return (profile, session).

    Raises `NoArtifactError` if no unconsumed artifact exists. Callers
    should fall back to `onboard()` with cached age + domain.
    """
```

#### 4.8.2 API route

`POST /learners/{learner_id}/resume` — opens the app, returns the first block
immediately with no LLM call in the hot path.

Response:
```json
{
  "session_id": "...",
  "phase": "teaching",
  "block": {...},
  "warm_start": true
}
```

If no artifact exists, returns HTTP 409 with a body telling the client to use
`POST /sessions` (normal onboard) instead.

### 4.9 Admin and learner-facing endpoints

#### 4.9.1 New routes in `src/api/admin.py`

`GET /admin/scheduler` — returns:
```json
{
  "tasks": [
    {
      "name": "dream_cycle",
      "cron": "30 2 * * *",
      "enabled": true,
      "last_run": { "outcome": "success", "duration_ms": 4230, "run_at": "..." },
      "next_fire": "2026-04-12T02:30:00-04:00",
      "failure_count_24h": 0
    },
    ...
  ],
  "process_started_at": "...",
  "uptime_seconds": 12345
}
```

#### 4.9.2 New `src/api/learners.py`

- `GET /learners/{id}/wiki/{concept}` — per-student concept wiki (markdown).
- `POST /learners/{id}/resume` — warm-start.
- `GET /learners/{id}/queue` — what the scheduler has queued for this learner
  (pending reviews, pre-generated artifacts, flagged gap concepts).
- `POST /learners/{id}/capture` — student shares a primary source URL or text;
  the handler runs `InboundSafetyGate` first, then `capture.capture_source()`,
  then returns the new `SourcePage` ID.

All four routes gate on `_require_learner_auth(learner_id)` — same env-var
token pattern Claw-ED uses for its dev mode. Multi-learner auth is a
post-MVP concern per N8.

## 5. Implementation phases

Seven phases, each leaves the tree green, each commits independently. Every
phase ends with `pytest --strict-markers -ra` green, `ruff check` clean,
`mypy --strict` clean, and the `test_foundational_reteach.py` suite unchanged.

### Phase 1 — Config + providers (no routing yet)

**Files added (~900 lines):**
- `src/orchestrator/config.py`
- `src/orchestrator/provider_ollama.py`
- `src/orchestrator/provider_anthropic.py`
- `src/orchestrator/provider_openai.py`
- `src/orchestrator/provider_openrouter.py`
- `tests/test_config.py`
- `tests/test_provider_ollama.py`
- `tests/test_provider_anthropic.py`
- `tests/test_provider_openai.py`
- `tests/test_provider_openrouter.py`

**Dependencies added to `pyproject.toml`:**
- `anthropic>=0.25`
- `openai>=1.20`
- `apscheduler>=3.10`
- `onnxruntime>=1.20`
- `numpy>=1.26`

**Success gate:** All provider tests green via `httpx.MockTransport`. No
wiring into the rest of the app yet.

### Phase 2 — Router + chain refactor

**Files added (~400 lines):**
- `src/orchestrator/router.py`
- `tests/test_router.py`

**Files modified:**
- `src/orchestrator/chain.py` — takes `router` instead of `provider`.
- `src/curriculum/live_generator.py` — takes `router` instead of `provider`.
- `tests/conftest.py` — add `router_for_testing(provider)` helper.
- All test files that construct `ReasoningChain` or `LiveContentGenerator` —
  wrap with helper.

**Success gate:** 73 existing tests still green. `test_router.py` covers
the fallback chain.

### Phase 3 — Persistence

**Files added (~500 lines):**
- `src/persistence/__init__.py`
- `src/persistence/schema.py`
- `src/persistence/connection.py`
- `src/persistence/store.py`
- `src/persistence/migrations.py`
- `tests/test_persistence.py`

**Files modified:**
- `src/api/state.py` — `AppState` delegates to `PersistentStore` (with
  `InMemoryStore` test-only fixture).
- `tests/conftest.py` — add `sqlite_in_memory` fixture.

**Success gate:** All existing tests still green against either
`InMemoryStore` or `sqlite_in_memory`. `test_persistence.py` round-trips
every entity.

### Phase 4 — Memory

**Files added (~1400 lines):**
- All of `src/memory/`
- `tests/test_memory_store.py`
- `tests/test_memory_search.py`
- `tests/test_memory_embeddings.py`
- `tests/test_memory_context.py`
- `tests/test_memory_writer.py`
- `tests/test_memory_dream.py`
- `tests/test_memory_wiki.py`

**Success gate:** all memory tests green. Embeddings bootstrap runs in a
background thread (test uses a pre-cached dummy model). Dream cycle is
invoked as a pure function with an `EchoProvider`-backed router and
produces deterministic compiled-truth rewrites.

### Phase 5 — Live content + crisis wiring + session-memory integration

**Files added (~500 lines):**
- `src/safety/gate.py`
- `tests/test_inbound_safety_gate.py`

**Files modified:**
- `src/engagement/session.py` — topic parameter, `live_content` optional dep,
  `CRISIS_PAUSE` phase, memory write-on-close, `warm_start()` stub.
- `src/api/session.py` — gate wired on every student-text route,
  `CRISIS_PAUSE` handling, topic field, new `POST /sessions/{id}/socratic`.
- `tests/test_safety.py` — 6 new crisis-wiring tests.
- `tests/test_session_flow.py` — new `TestLiveTopicPath` class.

**Success gate:** 73 existing tests green, `test_foundational_reteach.py`
green, 6 new crisis tests green, live-topic tests green (offline via
`EchoProvider`).

### Phase 6 — Scheduler + proactive tasks

**Files added (~700 lines):**
- All of `src/scheduler/`
- `tests/test_scheduler_registry.py`
- `tests/test_scheduler_tasks.py`

**Files modified:**
- `src/api/main.py` — `lifespan` starts + stops scheduler.
- `src/api/admin.py` — `GET /admin/scheduler`.

**Success gate:** Each task is proven idempotent (running twice = running
once). Dream cycle produces a diff report. `prepare_next_session` creates a
`NextSessionArtifact`. All tests run in under 2 seconds total.

### Phase 7 — Warm-start + learner-facing endpoints

**Files added (~400 lines):**
- `src/api/learners.py`
- `tests/test_warm_start.py`

**Files modified:**
- `src/engagement/session.py` — complete `warm_start()` implementation.
- `tests/test_api.py` — learner-route tests.

**Success gate:** A full E2E test: onboard → close → scheduler runs
`prepare_next_session` manually → `POST /learners/{id}/resume` returns a
block in under 50ms with no provider call in the hot path.

**Total: ~4800 new lines, ~33 new files, ~10 modified files.**

## 6. Testing strategy

Three layers:

1. **Unit tests** — per module, deterministic, `EchoProvider`-backed,
   in-memory stores, `tmp_path` brains, fast. Target: full suite under 2
   seconds.

2. **Integration (offline)** — `test_session_flow.py` runs the full loop
   end-to-end with the router wired to `EchoProvider`. Includes memory writes,
   reads, and dream-cycle idempotency.

3. **Provider contract tests** — `httpx.MockTransport` validates each
   provider's request shape and response parsing without a real network.
   `pytest -m live` opt-in marker runs the same tests against real endpoints
   (gated on API keys being set in env) — not part of default `pytest`.

**Invariants with explicit regression tests:**

- `test_foundational_reteach.py` — stays green throughout every phase.
- `test_inbound_safety_gate.py` — asserts every student-text route goes
  through the gate before any evaluator or orchestrator call (via
  `unittest.mock.patch` of the gate).
- `test_memory_writer.py` — asserts session-close produces exactly one
  `SessionPage`, one updated `LearnerPage`, and one updated `ConceptPage` per
  concept touched. No more, no less.
- `test_scheduler_tasks.py` — each task is idempotent: two runs == one run.
- `test_router.py` — fallback chain: Ollama → OpenAI → Anthropic →
  OpenRouter → Echo, with simulated provider outages.
- Prompt template snapshot tests — catch silent prompt drift.

## 7. Success criteria

The pass is done when **all** of these are true:

1. **Tests** — all existing tests still pass, ~80 new tests pass, full
   suite runs under 2 seconds on `pytest` (no API keys, no network).

2. **Lint + type** — `ruff check` clean, `mypy --strict` clean, 80%+
   coverage on every new file.

3. **E2E live topic** — fresh learner completes a full session against real
   providers: `POST /sessions {topic: "The Haitian Revolution", age: 15}` →
   3 calibration questions → 1 teach block → 1 check → 1 reteach-in-a-
   different-modality → close. Session page appears in the brain.
   `GET /learners/{id}/wiki/haitian_revolution` returns a populated compiled
   truth + citations.

4. **Warm-start** — scheduler runs `prepare_next_session`, then the next
   morning `POST /learners/{id}/resume` returns a block in under 200ms with
   no provider call in the hot path.

5. **Crisis regression** — a self-harm utterance posted to any student-text
   route returns `{"crisis": true, "resources": "..."}` with
   `CRISIS_PAUSE` phase, **without** touching the evaluator or orchestrator.
   Verified by `unittest.mock.patch` assertions.

6. **Token cost** — per active learner per night stays under $0.005 at
   default routing, logged via `SchedulerRunStore` and observable at
   `GET /admin/scheduler`.

7. **HEARTBEAT invariants** — `safety → profile → memory → assessment /
   curriculum / engagement → orchestrator → api` hierarchy preserved, no
   function over 50 lines, no swallowed exceptions, no PII in logs.

## 8. Risks and mitigations

**R1. ONNX MiniLM bootstrap slow on cold install.** 90MB download on first
server start. Mitigation: background thread with progress logging;
`hybrid_search` degrades to keyword-only while the download completes;
tests use a fixture that pre-places a tiny dummy model file.

**R2. OpenRouter GLM 5.1 model deprecation.** OpenRouter periodically
rotates model names. Mitigation: `provider_openrouter.py` takes the model
name from config, never hardcodes it. A single edit to
`~/.claw-stu/secrets.json` swaps models.

**R3. SQLite write contention** between scheduler and API. Mitigation:
WAL mode enabled, scheduler uses a separate connection with a
retry-on-`SQLITE_BUSY` loop. Pattern proven in Claw-ED.

**R4. FastAPI lifespan on serverless.** The embedded scheduler requires a
long-running process. Mitigation: documented as non-goal (N6). A follow-up
can extract `src/scheduler/__main__.py` as a standalone daemon.

**R5. Prompt drift despite snapshot tests.** Snapshot tests catch text
changes but not behavioral drift under the same text. Mitigation: the dream
cycle logs a structured "rewrite diff size" metric so an operator can see if
Stuart's compiled-truth rewrites start changing shape over time.

**R6. Token cost runaway if active learner count grows.** A bug in
`learners_with_recent_activity` could cause the scheduler to run dream cycle
on thousands of dormant learners. Mitigation: hard ceiling of 500
learners-per-task-run by default, configurable. Exceeding the ceiling logs
ERROR and pages the operator.

**R7. Crisis false negatives.** The regex-only escalation scanner will miss
paraphrased or obfuscated distress signals. Mitigation: documented as a
known limitation; the LLM-backed classifier (post-MVP) is designed to layer
on top of the existing patterns, not replace them. The existing patterns
stay as the baseline.

**R8. Memory growth per learner.** A long-term user might accumulate
hundreds of session pages. Mitigation: `prune_stale` task + an explicit
archival path where pages older than 180 days are compressed into a
`LearnerArchivePage` summary. Archival is post-MVP but the schema leaves
room for it.

**R9. Breaking change to `ReasoningChain` and `LiveContentGenerator`
constructors.** Changing from `provider` to `router` is a breaking change
for any external caller. Mitigation: blast radius is contained (only
internal code constructs these). A `router_for_testing(provider)` helper
keeps existing tests one-line.

## 9. Open questions

None that block implementation. Every decision in this document has been
made in the brainstorming phase and signed off. If new questions surface
during Phase 1-7 implementation, they go into a follow-up spec, not into
this one.

## 10. Acceptance

This design is considered accepted once:

1. Jon reviews this document and signs off on the shape, scope, and phases.
2. The spec-document-reviewer agent passes without blocking issues.
3. The `writing-plans` skill produces a concrete phased implementation plan
   derived from this spec.

---

*Made by a teacher, for learners. Built by a teacher in New York.*
