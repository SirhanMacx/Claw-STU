# Claw-STU Architecture

## Overview

Claw-STU is a personal learning agent. Stuart lives in your terminal and on a local web server, running adaptive learning sessions that calibrate to each student's level and remember what works.

This document describes the v0.2 architecture -- how sessions flow through the system, what each module does, and how components connect.

---

## System Diagram

```
Student
  |
  +-- Terminal: clawstu learn --> CLI chat loop (cli_chat.py)
  |                                 +-- Session runner (engagement/session.py)
  |                                 +-- ReasoningChain (orchestrator/chain.py)
  |                                 +-- ModelRouter --> LLM Provider
  |                                       +-- Ollama (local/cloud)
  |                                       +-- Anthropic
  |                                       +-- OpenAI
  |                                       +-- OpenRouter
  |                                       +-- EchoProvider (offline fallback)
  |
  +-- Web API: clawstu serve --> FastAPI app (api/main.py)
  |                                +-- Session endpoints
  |                                +-- Learner endpoints
  |                                +-- Admin/health endpoints
  |                                +-- Embedded scheduler (scheduler/runner.py)
  |
  +-- Companion commands:
       clawstu ask      --> one-shot Socratic question
       clawstu wiki     --> per-learner concept wiki
       clawstu progress --> learner dashboard
       clawstu history  --> session list
       clawstu review   --> spaced review due list
```

---

## Module Map

```
clawstu/
+-- cli.py                  # Typer entry point, routes to subcommands
+-- cli_chat.py             # Interactive learn/resume chat loop
+-- cli_companions.py       # wiki, progress, history, review, ask, profile
+-- cli_state.py            # JSON-snapshot persistence for CLI mode
+-- setup_wizard.py         # Interactive provider setup
+-- api/
|   +-- main.py             # FastAPI app factory + lifespan
|   +-- session.py          # Session endpoints (POST /sessions, etc.)
|   +-- learners.py         # Learner endpoints (GET /learners, wiki, review)
|   +-- profile.py          # Profile export/import endpoints
|   +-- admin.py            # Health + scheduler transparency
|   +-- auth.py             # Bearer token auth (optional)
|   +-- state.py            # In-memory AppState shared across routes
|   +-- static/             # Web UI (index.html)
+-- engagement/
|   +-- session.py          # Deterministic session state machine
|   +-- modalities.py       # Seven modality definitions
+-- assessment/
|   +-- evaluator.py        # CRQ rubric scorer + multiple choice
+-- orchestrator/
|   +-- chain.py            # ReasoningChain (prompt -> LLM -> safety filter)
|   +-- router.py           # ModelRouter (TaskKind -> provider + model)
|   +-- config.py           # AppConfig from secrets.json + env vars
|   +-- prompts.py          # PromptLibrary (versioned templates)
|   +-- live_content.py     # LiveContentGenerator (blocks, checks, pathways)
|   +-- providers.py        # LLMProvider protocol + EchoProvider
|   +-- provider_ollama.py  # Ollama via httpx
|   +-- provider_anthropic.py
|   +-- provider_openai.py
|   +-- provider_openrouter.py
|   +-- task_kinds.py       # TaskKind enum (calibration, teaching, etc.)
+-- memory/
|   +-- store.py            # BrainStore (per-learner markdown pages)
|   +-- pages/              # Page types: learner, concept, session, etc.
|   +-- search.py           # Hybrid keyword + vector search (FTS5 + ONNX)
|   +-- embeddings.py       # MiniLM ONNX embeddings
|   +-- knowledge_graph.py  # Concept relationships
|   +-- wiki.py             # Per-learner concept wiki generator
|   +-- context.py          # build_learner_context() for LLM injection
|   +-- capture.py          # Student-shared source capture
|   +-- writer.py           # Brain page writer (from session events)
|   +-- dream.py            # Dream cycle (rewrite compiled truth)
+-- profile/
|   +-- model.py            # LearnerProfile + ProfileStore
|   +-- zpd.py              # ZPD estimator (approaching/meeting/exceeding)
|   +-- observer.py         # Observational profile updates from events
|   +-- export.py           # JSON export/import with atomic writes
+-- safety/
|   +-- content_filter.py   # Age-appropriate outbound keyword filter
|   +-- escalation.py       # Crisis detection (self-harm, abuse, distress)
|   +-- boundaries.py       # Outbound boundary enforcer (sycophancy, etc.)
|   +-- gate.py             # Inbound safety gate on all student text
+-- persistence/
|   +-- store.py            # SQLite persistent store (WAL mode)
|   +-- connection.py       # Connection pool management
|   +-- migrations.py       # Schema migration system
|   +-- schema.py           # Table definitions
+-- scheduler/
|   +-- runner.py           # APScheduler wrapper
|   +-- registry.py         # Task registry with cron specs
|   +-- context.py          # ProactiveContext (router + brain + persistence)
|   +-- tasks/
|       +-- dream_cycle.py
|       +-- prepare_next_session.py
|       +-- spaced_review.py
|       +-- refresh_zpd.py
|       +-- prune_stale.py
+-- curriculum/
    +-- sources.py          # Seed content library
    +-- pathways.py         # Learning pathway generation
```

---

## Session Flow

A learning session follows a deterministic state machine:

```
ONBOARD --> CALIBRATING --> TEACHING --> CHECKING --> (pass?) --> CLOSING
                                           |                       ^
                                           +-- (fail) --> RETEACH --+
                                                            |
                                                       (different modality)
```

1. **ONBOARD**: Student provides name, age, topic. Profile created or loaded.
2. **CALIBRATING**: 3-5 diagnostic questions of varied format and difficulty. Results seed the ZPD estimate for this domain.
3. **TEACHING**: One learning block generated at the student's complexity tier, using the modality the router selects.
4. **CHECKING**: A constructed-response question (not multiple choice). Scored against a rubric.
5. **RETEACH** (on fail): Same concept, different modality. This invariant is tested in `test_foundational_reteach.py`.
6. **CLOSING**: Session summary, profile update, brain page writes.

Crisis detection runs on every student utterance. If triggered, the session enters CRISIS_PAUSE and surfaces human resources.

---

## Memory Architecture

Stuart's memory has three layers:

| Layer | Storage | Purpose |
|-------|---------|---------|
| **Brain pages** | Markdown files in `~/.claw-stu/brain/` | Compiled truth + timeline per learner, concept, session, source, misconception, topic |
| **Knowledge graph** | In-memory + SQLite | Concept relationships (prerequisite_for, builds_on, taught_in) |
| **Vector search** | ONNX MiniLM embeddings + FTS5 | Hybrid keyword + semantic search with Reciprocal Rank Fusion |

The overnight **dream cycle** rewrites each learner's compiled truth from their timeline. This means the second time you ask about a topic, Stuart knows what you understood from last session.

---

## Provider Architecture

All LLM calls go through the `ModelRouter`, which maps a `TaskKind` to a specific provider + model:

```
TaskKind (e.g., SOCRATIC_DIALOGUE)
    |
    v
ModelRouter.for_task()
    |
    v
(provider, model) -- e.g., (AnthropicProvider, "claude-sonnet-4-6")
    |
    v
provider.complete(system, messages, model)
    |
    v
ReasoningChain applies boundary enforcement on output
```

The fallback chain tries providers in order until one succeeds: Ollama, OpenAI, Anthropic, OpenRouter, EchoProvider. Echo always succeeds (it returns the input), so the system never crashes on a provider failure.

---

## Safety Architecture

Safety is not a feature flag -- it is foundational:

1. **Inbound gate** (`safety/gate.py`): Every student text entry is scanned before any evaluator or orchestrator call.
2. **Crisis detection** (`safety/escalation.py`): Regex patterns for self-harm, abuse, and distress. Match triggers CRISIS_PAUSE + resource packet.
3. **Content filter** (`safety/content_filter.py`): Deterministic keyword blocklist on every outbound string, calibrated by age bracket.
4. **Boundary enforcer** (`safety/boundaries.py`): Strips sycophancy ("great question!"), emotional claims ("I'm proud of you"), and innate praise before output reaches the student.

These run in sequence on every response. They are deterministic (no LLM calls) so they cannot be prompt-injected.

---

## Data Storage

All persistent data lives under `$CLAW_STU_DATA_DIR` (defaults to `~/.claw-stu/`):

```
~/.claw-stu/
+-- secrets.json        # API keys (restricted file permissions)
+-- state.json          # CLI-mode persistence snapshot
+-- clawstu.db          # SQLite database (WAL mode)
+-- brain/              # Per-learner markdown brain pages
    +-- <learner_id>/
        +-- learner.md
        +-- concept-*.md
        +-- session-*.md
        +-- misconception-*.md
        +-- topic-*.md
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| CLI | Typer + Rich |
| Web framework | FastAPI |
| Async HTTP | httpx |
| LLM APIs | anthropic, openai, ollama (via HTTP), openrouter (via HTTP) |
| Data validation | Pydantic 2.x |
| Embeddings | ONNX Runtime + MiniLM |
| Database | SQLite (WAL mode) |
| Scheduler | APScheduler |
| Linting | Ruff |
| Type checking | mypy (strict) |
| Testing | pytest + pytest-asyncio |
