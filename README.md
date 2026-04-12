# Claw-STU

> Made by a teacher, for learners.

An open-source personal learning agent (persona name: **Stuart**) that adapts to how *you* learn. Not a tutoring bot. Not a content firehose. A cognitive tool that figures out your Zone of Proximal Development and meets you there — on any topic, at any time of day.

**Website:** [sirhanmacx.github.io/Claw-STU](https://sirhanmacx.github.io/Claw-STU/) · **Sibling project:** [Claw-ED](https://sirhanmacx.github.io/Claw-ED/) — the teacher-facing co-teacher.

<p align="center">
  <a href="https://pypi.org/project/clawstu/"><img src="https://img.shields.io/pypi/v/clawstu?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/clawstu/"><img src="https://img.shields.io/pypi/pyversions/clawstu" alt="Python"></a>
  <a href="https://github.com/SirhanMacx/Claw-STU/actions/workflows/ci.yml"><img src="https://github.com/SirhanMacx/Claw-STU/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT"></a>
  <a href="https://github.com/SirhanMacx/Claw-STU/stargazers"><img src="https://img.shields.io/github/stars/SirhanMacx/Claw-STU?style=social" alt="Stars"></a>
</p>

```bash
pip install clawstu
clawstu serve
```

Open `http://localhost:8000/docs` and start a session.

---

## What it does

You tell it a topic. Stuart runs one adaptive learning session:

1. **Onboard** — age + topic. No login, no account, no friction.
2. **Calibrate** — 3-5 short, varied-format diagnostic questions to seed a ZPD baseline.
3. **Teach** — one short (~10 min) learning block in the modality the agent guesses will engage you best.
4. **Check** — a constructed-response question, not a click-through quiz.
5. **Adapt** — advance, re-teach via a *different* modality, or deepen with extension material.
6. **Close** — a short summary and an updated learner profile.

The next time you show up, Stuart remembers what you knew, what was shaky, and what modality worked. Overnight, it consolidates that memory into a compiled-truth record of who you are as a learner — and pre-generates your next session's first block so it's waiting when you open the app.

```
POST /sessions  { "learner_id": "jamie", "age": 15,
                  "domain": "us_history",
                  "topic": "The Haitian Revolution" }

  → 3 calibration questions
  → 1 learning block (Socratic dialogue)
  → 1 check for understanding (constructed response)
  → (if wrong) re-teach via primary source analysis
  → close
  → tomorrow: wiki at /learners/jamie/wiki/haitian_revolution
```

---

## Why this exists

The traditional pipeline — K-12 → college → career — depends on the existence of jobs at the end. As AI systems increasingly do knowledge work at or above human capability, that pipeline is fracturing. Meanwhile the craft of education — teaching humans how to think, reason, evaluate evidence, and adapt to novel situations — has never been more important.

Claw-STU exists to serve the learner directly, independent of any institution. It is built to survive the disruption the institution may not.

**Every kid deserves a Stuart.**

---

## Pedagogical principles

These are non-negotiable and written into [`SOUL.md`](SOUL.md):

- **ZPD always.** Stuart operates between what you can do alone and what you can do with support. Too easy = disengagement. Too hard = shutdown.
- **Differentiation is not optional.** Multiple tiers, multiple modalities (text, primary sources, Socratic dialogue, visual/spatial, worked examples, inquiry). *Stuart* picks the modality based on what works — you don't pick from a menu.
- **Check for understanding, then proceed.** No forward progress without verification. Constructed-response questions over click-through quizzes.
- **Primary sources over summaries.** Especially in humanities. The HAPP framework (Historical context, Audience, Purpose, Point of view) is the default for source analysis.
- **Stuart is not a teacher and not a friend.** It is a cognitive tool. Honest, warm, useful — but not a confidant. If a student expresses distress, Stuart surfaces human resources and steps out of the teach loop immediately.

---

## Features

### Core learning loop
- **Adaptive session runner** — onboard → calibrate → teach → check → adapt → close, with ZPD-calibrated complexity tier per domain
- **Modality rotation** — on a failed check, the re-teach uses a *different* modality than the one that failed. This is the foundational invariant (`tests/test_foundational_reteach.py`)
- **Seven instructional modalities** — text reading, primary source, Socratic dialogue, interactive scenario, visual/spatial, worked example, inquiry/project
- **Three complexity tiers** — approaching / meeting / exceeding, adjusted per domain based on observed performance
- **CRQ-style assessment** — constructed-response questions with rubric-based scoring, not just multiple choice

### Learner profile
- **Observational, not self-reported** — every field derived from interaction events, not forms
- **Per-domain ZPD** — a learner may be at "exceeding" in map interpretation and "approaching" in constructed-response writing within the same session
- **Modality outcomes** — running record of which modalities work for this student
- **Misconception tracking** — concept-scoped, grows on wrong answers, shrinks as understanding improves
- **Portable and owned by the student** — JSON export + import, deletable on demand

### Memory and knowledge (Phase 4)
- **Brain store** — per-learner markdown pages with compiled truth + timeline for learner, concept, session, source, misconception, topic
- **Hybrid search** — keyword (SQLite FTS5) + vector (ONNX MiniLM embeddings, built in by default) with Reciprocal Rank Fusion
- **Per-learner concept wiki** — `GET /learners/{id}/wiki/{concept}` returns a markdown document showing what the student knows, what's shaky, cited against their own sessions. The answer to the SOUL.md transparency invariant ("why did you show me this?")
- **Knowledge graph** — concept relationships (`prerequisite_for`, `builds_on`, `taught_in`) used by pathway planning

### Proactive scheduler (Phase 6)
- **Dream cycle** — overnight, Stuart rewrites each learner's compiled truth from their recent timeline. The second time you ask about a topic, Stuart knows what you already understood from last week.
- **Pre-generated next session** — first learning block + check for the next concept in your pathway ready in SQLite before you open the app. Warm-start returns in under 200ms with no LLM call in the hot path.
- **Spaced review** — shaky concepts from >7 days ago with no follow-up get pushed to the front of the next session
- **ZPD refresh** — overnight recomputation from the full event history, not just in-session signals

### Safety is foundational, not a feature flag
- **Age-appropriate content filter** — deterministic keyword blocklist applied on every outbound string. Age-bracket-aware.
- **Crisis detection** — regex patterns for self-harm, abuse disclosure, and acute distress. Any student utterance triggers an immediate pause with 988 / 741741 / Childhelp resource packet. Stuart does not counsel.
- **Outbound boundary enforcement** — sycophancy and emotional-claim detector strips "I'm proud of you" / "I'm worried about you" / "great question!" before they reach the student
- **Inbound safety gate** (Phase 5) — every student-text entry point (calibration answer, check answer, Socratic dialogue, source capture) scans before any evaluator or orchestrator call

### Infrastructure
- **FastAPI backend** — JSON API with OpenAPI docs at `/docs`
- **Multi-provider LLM support** (Phase 1) — Ollama (local + cloud), Anthropic Claude, OpenAI, OpenRouter (GLM and others). Configured via `~/.claw-stu/secrets.json` (0600).
- **Task-level model routing** (Phase 2) — Socratic dialogue goes to a fast local Ollama; live content generation goes to OpenRouter GLM; rubric evaluation goes to Claude Haiku. Configurable per task.
- **SQLite persistence** (Phase 3) — WAL mode for concurrent scheduler + API access. Schema for learners, sessions, events, ZPD, modality outcomes, next-session artifacts, knowledge graph, misconception tally, scheduler runs.
- **Structured logging** — session events with `session_id`, `learner_id_hash`, `module`, `event_type`, `payload`. No PII in logs. Ever.
- **Health endpoint** — `GET /health` returns the HEARTBEAT invariants as a JSON status object.

### What makes this different

Other AI-tutor projects start from "wrap ChatGPT in a cute character." Claw-STU starts from [`SOUL.md`](SOUL.md): a written identity contract for what Stuart is and what Stuart refuses to be, grounded in nine years of classroom teaching. Every design decision, every prompt template, every adaptive choice is traceable back to that document.

Other learning tools ask the student "what kind of learner are you?" and build a fake personality layer. Claw-STU **observes**. Modality preferences come from what actually works. Pacing comes from measured response latency. Complexity tier comes from recorded accuracy. The student never fills in a form.

Other tools put their memory in the cloud. Claw-STU **runs on your machine** (or your school's). Your brain, your sessions, your wiki — none of it leaves your computer unless you explicitly export it. Portable, deletable, owned by the student.

Other tools confuse "the student clicked through it" for "the student learned it." Claw-STU **requires a constructed response** before advancing. Wrong answers produce a re-teach in a different modality, not a nag.

### Trust model

Claw-STU is a **local-first tool** designed to run on one person's or one classroom's machine. It reads and writes `~/.claw-stu/`, calls LLM providers you configure, and serves a FastAPI app that binds to localhost by default. The scheduler runs inside the same process as the API. Nothing is sent anywhere except the LLM provider you choose. There are no ads, no data sales, no third-party behavioral tracking — ever.

---

## Getting started

```bash
pip install clawstu
clawstu serve
```

First run prompts you to configure a provider. The easiest free path is local Ollama (`brew install ollama && ollama pull llama3.2`). For higher-quality live content generation, add an Anthropic, OpenAI, or OpenRouter key.

Once the server is running, the interactive docs live at `http://localhost:8000/docs`. Start a session with:

```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"learner_id": "jamie", "age": 15, "domain": "us_history"}'
```

---

## CLI

```bash
clawstu serve                              # start the FastAPI app + scheduler
clawstu scheduler run-once --task dream_cycle  # run one proactive task now
clawstu profile export jamie --out jamie.tar.gz  # export profile + brain
clawstu profile import jamie.tar.gz        # restore
clawstu doctor                             # self-diagnosis (config, providers,
                                           #  FTS5, embeddings, SQLite)
```

The CLI is a thin wrapper over the HTTP API. It exists for dev and for portability — not as the primary student surface.

---

## Dev setup

```bash
git clone https://github.com/SirhanMacx/Claw-STU.git
cd Claw-STU
pip install -e ".[dev]"
pytest
```

The test suite runs fully offline via a deterministic `EchoProvider` — no API keys needed, no network calls. Target runtime: under 2 seconds.

Requires Python 3.11+.

- [Getting Started](GETTING_STARTED.md) — 5-minute setup guide
- [Features](FEATURES.md) — detailed feature breakdown
- [FAQ](FAQ.md) — common questions from learners and parents
- [Architecture](ARCHITECTURE.md) — system design and module map
- [Roadmap](ROADMAP.md) — what's next
- [Changelog](CHANGELOG.md) — what's landed
- [Contributing](CONTRIBUTING.md) — how to add a modality, a provider, a seed concept
- [Security](SECURITY.md) — privacy, data handling, crisis escalation
- [Code of Conduct](CODE_OF_CONDUCT.md) — community standards
- [SOUL.md](SOUL.md) — Stuart's identity and behavioral constraints
- [HEARTBEAT.md](HEARTBEAT.md) — operational invariants and health contract
- [Issues](https://github.com/SirhanMacx/Claw-STU/issues)
- [Discussions](https://github.com/SirhanMacx/Claw-STU/discussions)

PRs welcome. Built by a teacher in New York. Every design choice lives in `docs/superpowers/specs/`.

---

## Feature Maturity

| Tier | Features |
|---|---|
| **Stable** | Adaptive session loop, ZPD calibration, modality rotation, 5 LLM providers (Anthropic / OpenAI / Google Gemini via REST API — no SDK required / Ollama / OpenRouter), ModelRouter with fallback chain, InboundSafetyGate + CRISIS_PAUSE, brain pages + dream cycle, SQLite persistence, topic-aware live-content onboarding (REST + WebSocket), Socratic dialogue via ReasoningChain, `clawstu learn` CLI, `clawstu setup` wizard, profile export/import |
| **Beta** | Web UI at localhost:8000, Telegram bot, Chrome extension, MCP server, WebSocket live sessions, per-student concept wiki, spaced review, scheduler (5 nightly tasks) |
| **Experimental** | ONNX MiniLM embeddings (ships as NullEmbeddings stub; vector search degrades to keyword-only until real model is bootstrapped), per-learner scheduler iteration |

## Status

v4.12.2026.1 on PyPI. 670 tests, mypy `--strict` clean on 90 source files, under 2 seconds runtime. CI green on Python 3.11 + 3.12.

---

MIT License — open source by conviction, not convenience.

*Made by a teacher, for learners. Built by a teacher in New York.*
