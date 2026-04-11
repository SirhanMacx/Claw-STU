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

**Resolves B2 from spec review v1.** The current tree has
`src/curriculum/live_generator.py` importing from
`src/orchestrator/providers.py`, which inverts the stated hierarchy
(`curriculum` depending on `orchestrator`). This spec fixes the violation
by **moving `LiveContentGenerator` into `orchestrator/live_content.py`**.
Live content generation IS orchestration — it calls the router, parses
strict JSON, and runs generated text through the safety gate. It belongs
with the other orchestrator primitives, not in `curriculum/`. After the
move, `curriculum/` contains only deterministic content (seed library,
pathway planner, standards, topic, sources) with no network dependency.

The revised hierarchy (arrows = "depends on", so `api → orchestrator`
means `api` imports from `orchestrator`, not the reverse):

```
                         safety
                            ▲
                            │
                         profile
                            ▲
                            │
                         memory ◀──────── persistence
                            ▲                 ▲
                            │                 │
             assessment   curriculum   engagement
                 ▲            ▲            ▲
                 │            │            │
                 └────────────┼────────────┘
                              │
                              ▼  (engagement uses orchestrator
                              │   via the router parameter at runtime)
                         orchestrator ◀──── persistence
                              ▲
                              │
                             api ────────── persistence
                              ▲
                              │
                         scheduler  (owned by api lifespan;
                                     uses orchestrator, memory,
                                     persistence, engagement)
```

**Key rules (each with a test in `tests/test_hierarchy.py`):**

1. `safety` imports only from the standard library and `pydantic`.
2. `profile` imports from `safety` and stdlib/pydantic.
3. `memory` imports from `safety`, `profile`, `persistence`, stdlib, pydantic,
   and `numpy`/`onnxruntime`. It does **not** import from `curriculum`,
   `assessment`, `engagement`, `orchestrator`, `api`, or `scheduler`.
4. `curriculum` imports from `safety`, `profile`, `memory`, stdlib, pydantic.
   It does **not** import from `orchestrator`. (This is the B2 fix: today
   it violates this rule; after the move it won't.)
5. `assessment` imports from `safety`, `profile`, `memory`.
6. `engagement` imports from `safety`, `profile`, `memory`, `curriculum`,
   `assessment`. The `SessionRunner` accepts a `ModelRouter` as an optional
   constructor parameter (typed as `ModelRouter | None`), but the runner
   file **imports `ModelRouter` only inside a `TYPE_CHECKING` block** —
   so the runtime dependency graph does not include orchestrator. This
   is the same pattern Claw-STU already uses for `src/curriculum/
   live_generator.py`'s `MasterContent` import today.
7. `orchestrator` imports from `safety`, `profile`, `memory`, `curriculum`
   (specifically `curriculum.topic` for `Topic`, and `curriculum.content`
   for `LearningBlock` as a return type).
8. `persistence` imports only from stdlib + pydantic. It has no pedagogical
   content; it is a SQLite access layer.
9. `api` imports from everything below.
10. `scheduler` imports from `orchestrator`, `memory`, `persistence`,
    `engagement`. It does **not** import from `api`, but `api` owns the
    scheduler lifecycle via `lifespan`.

The `test_hierarchy.py` test uses `ast.parse` across every `.py` file under
`src/` and asserts that imports respect this DAG. A violation in any new
file is caught before merge. This is the mechanical version of the
HEARTBEAT global invariant #2.

### 4.2 Orchestrator: providers + router + config

#### 4.2.1 Files

```
src/orchestrator/
├── providers.py            # MODIFIED — protocol becomes async, EchoProvider
│                           #   gains async `complete`
├── provider_ollama.py      # NEW
├── provider_anthropic.py   # NEW
├── provider_openai.py      # NEW
├── provider_openrouter.py  # NEW (GLM models live here)
├── router.py               # NEW — TaskKind enum + ModelRouter
├── config.py               # NEW — AppConfig + env/file loader
├── live_content.py         # MOVED from curriculum/live_generator.py
│                           #   (see §4.1 hierarchy fix and §4.4)
├── prompts.py              # (existing)
└── chain.py                # MODIFIED — takes router, not provider;
                            #   becomes async
```

Each provider file is roughly 150-200 lines. Each one implements the
`LLMProvider` protocol with a single async method. Each one raises
`ProviderError` on failure. Each one uses `httpx.AsyncClient` with
`timeout=30.0`. Retries are handled by `ModelRouter`, not the provider
itself.

#### 4.2.1.a Async discipline (resolves B1 from spec review v1)

The existing `src/orchestrator/providers.py` defines `LLMProvider.complete`
as a synchronous method, and `EchoProvider.complete`, `ReasoningChain`,
`LiveContentGenerator._ask_json`, and the FastAPI route handlers are all
sync today. Network-backed providers want `httpx.AsyncClient`, and the
scheduler (§4.7) wants APScheduler's `AsyncIOScheduler`. Mixing sync and
async across the orchestrator boundary is the kind of ambiguity that
produces silent degradation — exactly the failure mode HEARTBEAT calls
out.

**Decision: everything that touches a provider is async. Everything else
stays sync.**

Concretely:

- **Becomes async:**
  - `LLMProvider.complete` (protocol)
  - `EchoProvider.complete`
  - All four network providers
  - `ReasoningChain.run_template`, `ReasoningChain.ask`
  - `LiveContentGenerator.generate_pathway`, `generate_block`, `generate_check`
  - `SessionRunner.onboard`, `SessionRunner.next_directive`,
    `SessionRunner.record_check`, `SessionRunner.warm_start` (anywhere a
    live-content call can happen)
  - Every FastAPI handler in `src/api/session.py` and `src/api/learners.py`
    (changes from `def` to `async def`)
  - Scheduler task `run_fn` signatures (`Callable[..., Awaitable[TaskReport]]`)

- **Stays sync:**
  - `src/safety/` (pure Python, no network)
  - `src/profile/` (pure data transformations)
  - `src/memory/store.py` (local filesystem)
  - `src/memory/embeddings.py` (ONNX runs in-process)
  - `src/persistence/` (sqlite3 is sync in the stdlib; a thread-bridge is
    not worth the complexity for MVP)
  - `src/engagement/modality.py`, `src/engagement/signals.py`
  - `src/curriculum/content.py`, `src/curriculum/pathway.py` (deterministic)

- **Crossing the sync/async boundary:** memory writes from an async session
  close simply call sync functions directly. `asyncio.to_thread` is used
  only when a sync operation is known to block for >50ms (e.g., initial
  ONNX model download). In practice this means exactly one call site:
  `asyncio.to_thread(embeddings.bootstrap)` inside the scheduler startup.

- **Test migration:** `pyproject.toml` already sets
  `asyncio_mode = "auto"`, so tests gain `async def test_*` for free.
  Existing tests that construct `EchoProvider` and call `.complete` synchronously
  need a one-line update: `await provider.complete(...)` inside an `async def`.
  `tests/test_orchestrator.py` is the only production test file that does
  this today (lines 57, 90 from spec review v1); the shim is mechanical.

- **`conftest.py` helper:** a single fixture `async_router_for_testing(provider)`
  wraps an async `EchoProvider` into a `ModelRouter` for any test that needs
  one. Zero per-test boilerplate.

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
| `RUBRIC_EVALUATION` | `anthropic` | `claude-haiku-4-5` | Accuracy-critical; Haiku 4.5 (N1 fix — Haiku 3 is deprecated April 19 2026) |
| `PATHWAY_PLANNING` | `openrouter` | `z-ai/glm-4.5-air` | Small JSON, cheap |
| `CONTENT_CLASSIFY` | `ollama` (local) | `llama3.2` | Safety should never depend on a network |
| `DREAM_CONSOLIDATION` | `openrouter` | `z-ai/glm-4.5-air` | Batch overnight; cost matters |

Any user without a given API key gets the next provider in
`fallback_chain: ["ollama", "openai", "anthropic", "openrouter"]`, ending at
`EchoProvider` as the last-resort fallback so the session loop never
hard-crashes on provider outage.

The §1 intro and the README both need to be updated alongside this spec to
refer to **GLM 4.5 Air** (the current OpenRouter model id) rather than "GLM
5.1". Model names are not semantically pinned — the config loader reads
them from `AppConfig.task_routing` at construction time, so a future switch
is a one-line change in `~/.claw-stu/secrets.json`, exactly per R2.

#### 4.2.5 `AppConfig` and `TaskRoute`

```python
class TaskRoute(BaseModel):
    """One (provider, model) assignment for a TaskKind. Kept as a named
    model so the config file reads cleanly: a dict of
    {TaskKind: {provider: ..., model: ...}} rather than opaque tuples.
    (N3 fix — earlier spec referenced TaskRoute without defining it.)"""
    model_config = ConfigDict(frozen=True)

    provider: str           # "ollama" | "anthropic" | "openai" | "openrouter" | "echo"
    model: str              # provider-specific model id
    max_tokens: int = 1024
    temperature: float = 0.2


class AppConfig(BaseModel):
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".claw-stu")
    primary_provider: str = "ollama"
    fallback_chain: tuple[str, ...] = ("ollama", "openai", "anthropic", "openrouter")
    task_routing: dict[TaskKind, TaskRoute] = Field(default_factory=_default_task_routing)
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    session_cache_size: int = 1024
    embeddings_model_url: str = (
        "https://huggingface.co/sentence-transformers/"
        "all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"
    )
    embeddings_model_sha256: str = ""  # populated at first successful
                                        # download; subsequent starts verify
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

**Windows behavior (N7 fix):** POSIX file permissions are ignored on
Windows. The secrets loader detects Windows via `os.name == "nt"` and
skips the 0600 check with a one-line WARN on first load that says
"Windows detected; file permission enforcement is a no-op here. Treat
~/.claw-stu/ as sensitive and protect it via NTFS ACLs or a user-only
profile location." The data dir is still created under
`Path.home() / ".claw-stu"` which maps to `%USERPROFILE%\.claw-stu` on
Windows.

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
`pyproject.toml`'s base `dependencies`.

**Model source and integrity (N5 fix):**
- Source URL (configurable via `AppConfig.embeddings_model_url`):
  `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx`
- Download target: `~/.claw-stu/models/all-MiniLM-L6-v2/model.onnx`
- Also downloaded from the same base URL: `tokenizer.json`, `config.json`,
  `vocab.txt`, `special_tokens_map.json`.
- Integrity: on first successful download, the SHA-256 of `model.onnx` is
  written to `~/.claw-stu/models/all-MiniLM-L6-v2/model.sha256`. Subsequent
  starts recompute the SHA and refuse to load if it mismatches (prevents a
  cached tamper from silently changing retrieval behavior).
- Retry: up to 3 attempts with exponential backoff (1s, 3s, 9s). After a
  final failure, the server starts in **keyword-only search mode** with a
  WARN log and a structured event `{event: "embeddings_unavailable",
  reason: "download_failed"}`.
- **Tests** use a pre-placed dummy ONNX file (~100KB stub with the same
  input/output shape as the real model) installed via a `tests/fixtures/`
  path, so the test suite never touches the network. The `embeddings.py`
  loader is told where to find the fixture via an env var
  `STU_EMBEDDINGS_MODEL_DIR` which `conftest.py` sets for the whole suite.

First-run bootstrap runs in a background thread at server startup;
`search.py` degrades to keyword-only while the download completes, logging
progress via structured events every 5 seconds.

`embeddings.py` exposes:
```python
class Embeddings:
    def __init__(self, model_dir: Path) -> None: ...
    def is_ready(self) -> bool: ...
    def encode(self, text: str) -> np.ndarray: ...  # shape (384,)
    def encode_batch(self, texts: list[str]) -> np.ndarray: ...  # shape (N, 384)
    def bootstrap(self) -> None:
        """Download + verify + load. Called in a background thread at
        server startup; may also be called eagerly from tests."""
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

Note: `LiveContentGenerator` moves from `src/curriculum/live_generator.py`
to `src/orchestrator/live_content.py` during Phase 2 (see §4.1 for the
rationale). The move is a pure rename + import rewrite; the class body
stays the same except for the async migration from §4.2.1.a. Anywhere
this spec refers to "`LiveContentGenerator`" below, the import path
after Phase 2 is `from src.orchestrator.live_content import
LiveContentGenerator`.

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

`SessionRunner.next_directive` adds an **explicit branch** for
`CRISIS_PAUSE` at the top of the dispatch — before the existing
`ONBOARDING / CALIBRATING / CLOSING / CLOSED` checks — returning a
directive with only the crisis message (no block, no check) (N12 fix).
Without this explicit branch, the current dispatch in
`src/engagement/session.py:199-211` would fall through to
`_next_teach_or_check(...)` on a paused session, which would try to
allocate a block — wrong on multiple axes. The regression test
`test_crisis_paused_session_refuses_next_directive` from §4.5.4 is the
one that catches this, and it must be added in Phase 5 alongside the
branch itself.

The session can be closed normally (which produces a summary acknowledging
the pause); resuming requires an explicit admin action.

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
    notes TEXT,                          -- N2 fix: mirror ObservationEvent.notes
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
    total_latency_seconds REAL NOT NULL,   -- N2 fix: match ModalityOutcome field
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

**FTS5 probe (N6 fix):** `page_text_index` uses SQLite FTS5, which is a
compile-time option and may be missing on custom-built SQLite installs.
`src/persistence/connection.py` probes for FTS5 at first open via
`SELECT sqlite_compileoption_used('ENABLE_FTS5')` and raises a clear
`RuntimeError("SQLite FTS5 is required but not available in this build. "
"Install Python via python.org or a distribution whose stdlib sqlite3 "
"ships with FTS5 enabled.")` if absent. The test suite asserts that the
probe fires on a fake connection that returns 0.

**Hashing boundary (N2 fix):** brain pages under `~/.claw-stu/brain/`
live in subdirectories keyed by a **hash** of the `learner_id` (first 12
chars of sha256). This keeps the on-disk filesystem layout from leaking
learner IDs if the directory is ever browsed or tarred. The SQLite
`learners` table uses the **plain** `learner_id` because it is the
primary key consumers (session runner, API) care about. The one
translation point is `BrainStore.__init__` which computes the hash once
per learner and caches it; every `BrainPage` write uses the hashed path.
Logs always use the hash; API endpoints always use the plain id.

#### 4.6.3 `PersistentStore`

One small typed wrapper per entity (`LearnerStore`, `SessionStore`,
`EventStore`, `ArtifactStore`, `KGStore`, `MisconceptionStore`,
`SchedulerRunStore`). No ORM. Each method takes pydantic models in and
returns pydantic models out. Raw SQL is kept in `schema.py` and
`store.py`; nothing outside `persistence` writes SQL directly.

#### 4.6.4 Interaction with `src/api/state.py` (resolves B3 from spec review v1)

The current `AppState.put/get/drop` interface operates on whole
`SessionBundle` objects (profile + session), and `get()` returns a live
reference that the `SessionRunner` mutates in place. A naive SQL-backed
store would break that contract — every `get()` would return a fresh
deserialized copy, and mutations to `session.phase`, `session.signals`,
`session.pathway`, etc., would silently fail to persist between
calls.

**Resolution: `AppState` wraps `PersistentStore` with an in-process identity
cache keyed by `session_id`.**

```python
class AppState:
    def __init__(self, persistence: PersistentStore) -> None:
        self._persistence = persistence
        self._cache: dict[str, SessionBundle] = {}
        self._lock = threading.RLock()

    def put(self, bundle: SessionBundle) -> None:
        """Cache the bundle and checkpoint to persistence.
        
        Decomposes the bundle across entity stores:
        - persistence.learners.upsert(bundle.profile)
        - persistence.sessions.upsert(bundle.session)
        - persistence.events.append_new(bundle.profile.events)
        - persistence.zpd.upsert_all(bundle.profile.zpd_by_domain)
        - persistence.modality_outcomes.upsert_all(
              bundle.profile.modality_outcomes)
        - persistence.misconceptions.upsert_all(bundle.profile.misconceptions)
        """

    def get(self, session_id: str) -> SessionBundle:
        """Return the cached bundle. On cache miss, load from persistence
        and cache the result. Subsequent get() calls return the same
        object by identity — mutations propagate."""

    def drop(self, session_id: str) -> None:
        """Flush to persistence, then evict from cache."""

    def checkpoint(self, session_id: str) -> None:
        """Re-persist the cached bundle without evicting. Called on
        phase transitions and after record_check/record_calibration_answer."""
```

**Mutation propagation:** `SessionRunner.record_check` and other mutators
continue to modify `bundle.session` and `bundle.profile` by reference.
After each mutating call, the API handler explicitly calls
`state.checkpoint(session_id)` to flush the current state to SQLite.
No "auto-persist on every field set" — checkpointing is explicit and happens
at well-defined points (end of each handler that mutates state).

**Cache eviction:** unbounded is wrong for a long-running process. The
cache uses a simple LRU with a default max size of 1024 sessions
(configurable via `STU_SESSION_CACHE_SIZE` env var). On eviction the
bundle is re-persisted before being dropped from memory.

**In-memory test store:** `src/persistence/store.py` ships
`InMemoryPersistentStore` alongside the SQLite-backed `PersistentStore`,
implementing the same typed interface. Tests use
`InMemoryPersistentStore` via a `sqlite_in_memory` fixture in
`tests/conftest.py`. The cache-plus-store pattern means existing tests
that rely on mutation-in-place continue to work unchanged — the cache
hit rate is 100% in tests because nothing else is competing for slots.

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
post-MVP concern per non-goal N8.

**`_require_learner_auth` location and contract (N8 fix from review v1):**
- Lives at `src/api/auth.py` as a FastAPI dependency.
- Reads `STU_LEARNER_AUTH_TOKEN` from the environment. If unset, the
  dependency is a no-op (dev mode, local only).
- If set, every request must include `Authorization: Bearer <token>`.
  Mismatched or missing token → HTTP 401 with body
  `{"detail": "unauthorized"}`. The comparison uses
  `secrets.compare_digest` to avoid timing-side-channel leaks (same
  pattern Claw-ED adopted in v4.11.2026.1).
- Learner-id binding is NOT checked today. A compromised token grants
  access to any learner's data. This is acceptable for dev / single-
  household / single-classroom deployments and explicitly documented as
  non-goal N8. Post-MVP would replace the shared-secret token with a
  per-learner JWT.
- Covered by `tests/test_api.py::TestLearnerAuth` with three cases:
  no token set (pass), token set + correct bearer (pass), token set +
  missing/wrong bearer (401).

**Crisis events do NOT write to the brain (N9 clarification from review v1):**
A crisis pause is intentionally **not** persisted to any brain page or
structured-log payload beyond the single `{event: "crisis_detected",
kind, session_id_hash, learner_id_hash}` line. No raw text, no
`MisconceptionPage`, no `SessionPage` body, no wiki entry. The crisis
path is write-minimized on purpose: SOUL.md §5 says Stuart surfaces
human resources and steps out of the teach loop. Preserving a paper
trail of the specific words a student typed during a crisis would
create a PII retention hazard the project refuses to accept. An
implementer who is tempted to "make the wiki complete" by adding a
crisis entry should not — the omission is the design.

### 4.10 Packaging and distribution (`pip install clawstu`)

Claw-STU ships on PyPI as `clawstu`. Install with:

```bash
pip install clawstu          # base install — all four providers + memory + scheduler
pip install 'clawstu[all]'   # optional frontend-support bundle (post-MVP)
```

#### 4.10.1 Package name

- `pyproject.toml` `[project] name = "clawstu"` (changed from the existing
  `claw-stu`). PEP 503 normalization means `claw-stu` and `clawstu`
  normalize to different names on PyPI, so Jon's desired
  `pip install clawstu` command requires the name to be `clawstu`
  verbatim.
- `src/` remains the top-level package directory (already matches what
  the current pyproject `[tool.setuptools.packages.find]` expects).
- Distribution metadata (classifiers, keywords, description) is updated
  to reflect the reality of the project: it is an adaptive learning
  agent, not a "tutor," per SOUL.md. Classifiers added:
  `"Topic :: Education :: Computer Aided Instruction (CAI)"`,
  `"Framework :: FastAPI"`, `"Development Status :: 3 - Alpha"`
  (up from Pre-Alpha once providers and memory land).

#### 4.10.2 Console entry point

A single CLI command `clawstu` exposes a small surface for
administration. It is **not** the primary user surface (students use the
API or a future frontend). It exists for:

- `clawstu serve` — start the FastAPI app via uvicorn, with the scheduler
  embedded. Defaults to `127.0.0.1:8000` to match Claw-ED's
  localhost-first posture.
- `clawstu scheduler run-once --task <name>` — run a specific proactive
  task once, bypassing the cron schedule. Useful for dev and for backfill.
- `clawstu profile export <learner_id> --out <path>` — exports the learner
  profile + all brain pages for that learner as a tarball. Delivers on
  the "portable, owned by the student" SOUL.md commitment from the CLI.
- `clawstu profile import <path>` — inverse.
- `clawstu doctor` — runs `AppConfig.load()`, pings each configured
  provider, probes SQLite FTS5, checks that embeddings bootstrap is
  reachable, and reports a one-page health summary. Mirrors the `clawed
  doctor` command Claw-ED uses for self-diagnosis.

Entry point declared in `pyproject.toml`:
```toml
[project.scripts]
clawstu = "src.cli:main"
```

Implementation lives at `src/cli.py` (new, ~200 lines). The CLI layer
does **no pedagogical logic** — every command is a thin wrapper around
functions that already exist in `api`, `scheduler`, `memory`, or
`persistence`. This keeps the CLI and the HTTP API as parallel
front-ends over the same core, exactly the way Claw-ED's CLI and API
relate.

#### 4.10.3 Build backend

- Switch from `setuptools` to **hatchling** (matches Claw-ED,
  faster builds, better sdist ergonomics).
- `pyproject.toml` gains `[build-system] requires = ["hatchling"]`
  `build-backend = "hatchling.build"`.
- `[tool.hatch.build.targets.wheel]` packages = `["src"]`, renamed to
  `clawstu` at install time via `[tool.hatch.build.targets.wheel.sources]
  "src" = "clawstu"`. That way `pip install clawstu` gives users `import
  clawstu` at the top level, not `import src`, which is the convention
  the existing code follows internally but that would be wrong to expose
  publicly. (**Implication:** every `from src.xxx import yyy` across the
  codebase becomes `from clawstu.xxx import yyy` during Phase 1 as part
  of the packaging conversion. This is a mechanical find-and-replace
  with `ruff format` as the cleanup pass. Tests and internal imports
  follow the same rewrite.)

#### 4.10.4 CI workflow for PyPI publish

`.github/workflows/ci.yml` already exists (single-commit bootstrap).
This pass **adds a publish job** that mirrors Claw-ED's pattern:

```yaml
publish:
  if: startsWith(github.ref, 'refs/tags/v')
  needs: [python-tests]
  runs-on: ubuntu-latest
  environment: pypi
  permissions:
    id-token: write
  steps:
    - uses: actions/checkout@v5
    - uses: actions/setup-python@v5
      with:
        python-version: '3.12'
    - name: Build
      run: |
        pip install build
        python -m build
    - name: Publish to PyPI
      run: |
        pip install twine
        twine upload --skip-existing dist/*
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
        TWINE_NON_INTERACTIVE: "1"
```

Per the lessons from Claw-ED v4.11.2026's audit: no `|| echo "Upload
skipped"` tail (which masked real failures in Claw-ED's workflow), and
the `test` job must pass before `publish` runs (`needs: [python-tests]`
dependency enforces this).

Version bumps land in `pyproject.toml` and `src/__init__.py` together,
and a git tag `v0.X.0` triggers the publish job.

#### 4.10.5 Optional install script

Post-MVP, a one-line installer mirroring Claw-ED's `scripts/install.sh`:

```bash
curl -fsSL https://raw.githubusercontent.com/SirhanMacx/Claw-STU/main/scripts/install.sh | bash
```

The script: detects Python ≥3.11, installs via `pip install clawstu`,
creates `~/.claw-stu/`, generates a starter `secrets.json` with
placeholder env-var references, and prints the next steps
(`clawstu doctor`, `clawstu serve`). **Not in scope for this pass** —
flagged here so it has a home in the project plan.

#### 4.10.6 Docker image

Out of scope for this pass (non-goal N6 extended). A later pass can add
a minimal `Dockerfile` mirroring Claw-ED's pattern (non-root user,
127.0.0.1 bind by default, env-var-driven config). The Windows path
matters more for MVP because most public-school laptops are Windows,
and the Python install works on Windows today without Docker.

## 5. Implementation phases

Seven phases, each leaves the tree green, each commits independently. Every
phase ends with `pytest --strict-markers -ra` green, `ruff check` clean,
`mypy --strict` clean, and the `test_foundational_reteach.py` suite unchanged.

### Phase 1 — Packaging rename + config + providers (no routing yet)

**Packaging conversion (per §4.10):**
- `pyproject.toml` — `name` renamed from `claw-stu` to `clawstu`; build
  backend switched from setuptools to hatchling; add
  `[tool.hatch.build.targets.wheel.sources] "src" = "clawstu"`; add
  `[project.scripts] clawstu = "clawstu.cli:main"`.
- Every `from src.xxx import yyy` across the codebase becomes
  `from clawstu.xxx import yyy` (mechanical find-and-replace plus
  `ruff format` cleanup). Affects every `.py` file under `src/` and
  `tests/`. On-disk layout stays under `src/` — the wheel rename
  happens at build time via the hatch sources mapping.
- `README.md` — install instructions become `pip install clawstu`.

**Files added (~1100 lines):**
- `src/orchestrator/config.py`
- `src/orchestrator/provider_ollama.py`
- `src/orchestrator/provider_anthropic.py`
- `src/orchestrator/provider_openai.py`
- `src/orchestrator/provider_openrouter.py`
- `src/cli.py` — `clawstu` console entry point (§4.10.2)
- `tests/test_config.py`
- `tests/test_provider_ollama.py`
- `tests/test_provider_anthropic.py`
- `tests/test_provider_openai.py`
- `tests/test_provider_openrouter.py`
- `tests/test_cli.py`
- `tests/test_packaging.py` — asserts `import clawstu` resolves,
  `clawstu --help` runs, `pyproject.toml` lists the right deps.

**Dependencies added to `pyproject.toml`:**
- `anthropic>=0.25` — **promoted** from the existing `[anthropic]` optional
  extra into base `dependencies` (N11 fix — earlier spec said "added" but
  the entry already exists in optional-dependencies). Provider file
  still does `import anthropic` lazily inside the `complete` method so
  users who want to skip the dep can install from a fork with the line
  removed; the default install carries it.
- `openai>=1.20` — same: **promoted** from `[openai]` to base.
- `apscheduler>=3.10` — NEW base dep.
- `onnxruntime>=1.20` — NEW base dep (per Jon's explicit directive: built
  in, not optional).
- `numpy>=1.26` — NEW base dep (transitive of onnxruntime for vector ops).
- `tokenizers>=0.15` — NEW base dep (for MiniLM tokenization).

**Success gate:** All provider tests green via `httpx.MockTransport`. No
wiring into the rest of the app yet. `pyproject.toml` declares every new
dep with an upper bound (`<next-major`) to avoid semver drift.

### Phase 2 — Router + async migration + live-content relocation

**Files added (~450 lines):**
- `src/orchestrator/router.py`
- `tests/test_router.py`
- `tests/test_hierarchy.py` — AST-walks `src/` and asserts the import
  DAG from §4.1 is respected. Guards every subsequent phase.

**Files moved (B2 fix):**
- `src/curriculum/live_generator.py` → `src/orchestrator/live_content.py`
  (pure rename + import-path rewrite; class body unchanged)

**Files modified:**
- `src/orchestrator/providers.py` — `LLMProvider.complete` becomes async.
  `EchoProvider.complete` becomes async. (B1 fix)
- `src/orchestrator/chain.py` — `ReasoningChain.run_template` and `.ask`
  become `async def`. Constructor takes `router` instead of `provider`.
- `src/orchestrator/live_content.py` (the moved file) — all three
  `generate_*` methods become `async def`. `_ask_json` becomes `async def`.
  Constructor takes `router` instead of `provider`.
- `src/engagement/session.py` — `onboard`, `next_directive`, `record_check`,
  `calibration_items`, `record_calibration_answer`, `finish_calibration`,
  `select_check`, `close` become `async def` where a live-content call is
  reachable. Tests updated to `await` them.
- `src/api/session.py` — FastAPI handlers become `async def`.
- `tests/conftest.py` — adds `async_router_for_testing(provider)` fixture.
- `tests/test_orchestrator.py` — only production test file that currently
  constructs `ReasoningChain` or `LiveContentGenerator` (lines 57 and 90
  per spec review v1). Updated in place.
- Existing `tests/test_session_flow.py`, `tests/test_api.py`,
  `tests/test_foundational_reteach.py` — handler bodies become `async def`
  where they call session-runner methods; rest unchanged.

**Success gate:**
- 73 existing tests still green (via `async def` conversion — `pytest-asyncio`
  is already in dev deps with `asyncio_mode = "auto"`).
- `test_router.py` covers the fallback chain.
- `test_hierarchy.py` passes: every import in `src/` respects §4.1.

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

## 11. Changelog

### v2 — 2026-04-11 (same-day revision)

Resolves three **blocking issues** and twelve non-blocking nits from the
spec-document-reviewer's audit of v1, and adds a new packaging section
per Jon's directive that Claw-STU ship on PyPI as `pip install clawstu`.

**Blocking fixes:**
- **B1 async/sync contradiction** (§4.2.1.a, Phase 2). Committed to
  async across the provider → chain → session → API path; sync stays
  for pure-logic modules. Explicit migration plan in Phase 2.
- **B2 import hierarchy violation** (§4.1, §4.4, Phase 2). Moved
  `LiveContentGenerator` from `src/curriculum/live_generator.py` to
  `src/orchestrator/live_content.py`, which is where it belongs
  semantically anyway. Added `tests/test_hierarchy.py` as a permanent
  AST-based guard against re-violation.
- **B3 AppState ↔ PersistentStore mapping** (§4.6.4). Introduced an
  in-process identity cache over `PersistentStore` so `SessionRunner`
  can keep mutating bundles by reference. Explicit checkpoint semantics
  at handler boundaries. LRU eviction with re-persist on evict.

**Non-blocking fixes (N1-N12 from review v1):**
- **N1** — Haiku default bumped to `claude-haiku-4-5` (Haiku 3 is
  deprecated April 19 2026). GLM model name corrected to `z-ai/glm-4.5-air`
  throughout (§4.2.4).
- **N2** — `observation_events` schema gains the `notes` column to match
  `ObservationEvent.notes`. `modality_outcomes.total_latency` renamed
  to `total_latency_seconds` to match `ModalityOutcome.total_latency_seconds`.
  Hashing boundary documented: brain pages use hashed learner ids in
  their on-disk path; SQLite tables use plain learner ids (§4.6.2).
- **N3** — `TaskRoute` pydantic model defined inline in §4.2.5.
- **N4** — Phase 2 test-file scope tightened: the only production test
  file that currently constructs `ReasoningChain`/`LiveContentGenerator`
  is `tests/test_orchestrator.py` lines 57 and 90.
- **N5** — ONNX model source URL (HuggingFace), SHA-256 integrity check,
  3-attempt retry with backoff, degradation to keyword-only on
  persistent failure, and dummy-fixture test strategy (§4.3.3).
- **N6** — SQLite FTS5 compile-time probe added to
  `src/persistence/connection.py` with a clear error message (§4.6.2).
- **N7** — Windows POSIX permissions handling documented: WARN + no-op,
  with guidance on NTFS ACLs (§4.2.5).
- **N8** — `_require_learner_auth` location, contract, and test cases
  documented (§4.9.2).
- **N9** — Crisis events **do not** write to the brain. The omission is
  intentional (PII retention hazard) and is now called out explicitly
  so implementers don't add it "for completeness" (§4.9.2).
- **N10** — Left as-is (minor style nit; "SOUL.md §6" is shorthand for
  "SOUL.md hard constraint #6"; both are greppable).
- **N11** — Phase 1 dependency listing corrected: `anthropic` and
  `openai` are **promoted** from existing `[anthropic]`/`[openai]`
  optional extras to base deps, not newly added (Phase 1, §Phase 1).
- **N12** — Explicit branch for `CRISIS_PAUSE` at the top of
  `SessionRunner.next_directive` dispatch, called out in §4.5.3. The
  regression test `test_crisis_paused_session_refuses_next_directive`
  from §4.5.4 is the catch.

**Added:**
- **§4.10 Packaging and distribution** — Claw-STU ships on PyPI as
  `clawstu`. Name rename from `claw-stu` → `clawstu` to make
  `pip install clawstu` the one-liner. Hatchling build backend with
  `[tool.hatch.build.targets.wheel.sources]` mapping `src/` → `clawstu/`
  at wheel time. Console entry point `clawstu serve | scheduler |
  profile | doctor` at `src/cli.py`. CI workflow adds a `publish` job
  gated on `test` passing and triggered by `v*` tags, mirroring the
  v4.11.2026.1 pattern Claw-ED uses (no `|| echo` mask, OIDC-ready
  permissions declared). **Phase 1 does the packaging rename** as a
  mechanical find-and-replace plus `ruff format` cleanup, in the same
  commit as the new provider files, so every subsequent phase runs
  under the `clawstu` import name.

### v1 — 2026-04-11 (initial)

Initial spec, drafted live during the brainstorming session.

---

*Made by a teacher, for learners. Built by a teacher in New York.*
