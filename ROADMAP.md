# Roadmap

Claw-STU is pre-alpha. This roadmap is a living document — it shifts as
the project learns what learners actually need. The ordering below is the
current best guess; feedback and real usage will reorder it.

## Shipped — v4.12.2026 (Providers, memory, proactive agent)

Shipped and live on PyPI. Tracked in full detail at
[`docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md`](docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md).

**Goals:**
- Real LLM providers (Ollama, Anthropic, OpenAI, OpenRouter) — not just
  the deterministic `EchoProvider`
- Task-level model routing with fallback chain
- Memory system: brain store, hybrid keyword+vector search (ONNX MiniLM
  embeddings as a core dep), knowledge graph, per-learner concept wiki
- Crisis wiring on every student-text entry point
- Proactive scheduler inside FastAPI lifespan — overnight dream cycle,
  pre-generated next session, spaced review, ZPD refresh
- Warm-start session resume (< 200ms, no LLM call in the hot path)
- `~/.claw-stu/` data directory with SQLite persistence (WAL mode)
- PyPI distribution as `pip install clawstu`
- Console entry point: `clawstu serve | scheduler | profile | doctor`

**Non-goals for v4.12.2026:** frontend beyond web UI, guardian dashboard, games, Claw-ED
handoff, serverless deployment, i18n. Each has its own slot below.

## Next — v0.3.0 (Frontend)

A mobile-first web UI so learners don't have to `curl` the API. Students
are on phones and iPads, not terminals.

- React + Tailwind, mobile-first
- Topic onboarding, calibration, teach, check, close flow
- Concept wiki view (the transparency payoff)
- Accessibility from day one (screen reader, keyboard nav, color contrast)
- Runs against the existing FastAPI backend — no new backend work

## Next — v0.4.0 (Guardian dashboard)

Age-appropriate transparency for parents and guardians about what the
student is learning. **Not** a surveillance tool.

- Read-only summary view: topics covered, sessions completed, concepts
  mastered, misconceptions resolved
- No raw utterances, no screen recordings, no session-by-session
  blow-by-blow. Compiled truth, not timeline.
- Student opt-in required. The profile is still owned by the student.
- Works with single-guardian and multi-guardian setups (divorced
  families, guardianship arrangements)

## Later — v0.5.0 (Games and simulations)

Interactive learning experiences beyond text + questions.

- Timeline challenges (drag era cards into order)
- Map exploration (click regions, answer location-based questions)
- Escape rooms (sequenced concept puzzles)
- Jeopardy-style review
- Claw-ED's existing game-type reference library transfers directly

## Later — v0.6.0 (Multi-domain expansion)

Post-MVP per Handoff.md. The deterministic seed library grows beyond the
four US History blocks. Live-content generation already works for any
topic in v4.12.2026 -- this phase adds **curated** seed content for:

- Global History (covering the 9th-10th grade Regents scope)
- Civics (government, Supreme Court, elections)
- ELA (reading comprehension, argumentative writing, rhetorical analysis)
- Science (biology, chemistry, physics at HS level)
- Math (algebra, geometry, statistics at HS level)

Curated content means human-reviewed primary sources, human-reviewed
calibration items, human-reviewed rubrics. The LLM is never the sole
source of truth for MVP-seeded content.

## Later — v0.7.0 (Claw-ED ↔ Claw-STU handoff)

A teacher using [Claw-ED](https://github.com/SirhanMacx/Claw-ED) can
optionally share their curriculum with their students' Claw-STU
instances, creating a hybrid human-AI learning environment.

- Export a unit or lesson from Claw-ED → import into the student's
  Claw-STU brain as a topic pathway
- The student's Claw-STU reads the teacher's voice (from Claw-ED's
  pedagogical fingerprint) and reinforces it rather than fighting it
- Opt-in on both sides. No automatic data sharing. No surveillance.

## Later — v0.8.0 (Peer learning)

Facilitate connections between students working on similar topics, with
robust safety architecture.

- Students can opt into "I'm learning about X" discovery
- Peer connection mediated entirely by Stuart — no direct messaging, no
  exchange of PII, no profile visibility
- Shared learning activities (collaborative timeline construction,
  paired source analysis, peer-review of written responses)
- Hard-walled: no private messaging, no photo sharing, no location data,
  no off-platform contact

## Later — v0.9.0 (Offline-first mode)

For students without reliable internet access, the core functionality
runs fully locally.

- Local Ollama is already supported in v4.12.2026 for model inference
- Brain + SQLite are already local
- This phase adds: local-only config (no "it works better with Claude"
  fallbacks that require a network), explicit offline-mode startup
  check, pre-packaged content bundles that ship with the installer

## Later — v1.0.0 (Lifelong portability)

The learner profile grows with the student from childhood through
adulthood. Stuart at 12 and Stuart at 30 are the same agent, evolved.

- Profile schema versioning with forward-compatible migrations
- Long-term storage strategy: archival compression of session pages
  older than 180 days into a `LearnerArchivePage` summary
- Identity re-key (when a student changes their name, email, or wants
  to detach from a previous account without losing their profile)
- Personal research mode: Stuart acts as a research-assistant rather
  than a calibrated teacher when the learner is an adult exploring a
  topic outside any curriculum

## Explicitly deferred

These are ideas we've considered and set aside. Included so the roadmap
is honest about what we're choosing not to build.

- **A native mobile app** — the web UI covers mobile. A native app is a
  separate team's worth of work for marginal benefit.
- **Voice interface** — tempting but ethically loaded for minors.
  Deferred until we can think carefully about when it helps a learner
  and when it crosses SOUL.md's "not a friend" line.
- **Multi-tenant hosted service** — we are not a SaaS company. The
  open-source project exists so families, schools, and communities can
  self-host. A hosted offering may exist one day but it is not a
  roadmap item for the core project.
- **A cryptocurrency, an NFT, or a "Learn-to-Earn" tokenomics layer** —
  no.

---

If something on this list matters to you and is moving slowly, open an
issue. If something matters to you and isn't on this list, open an issue.
If you want to implement something on this list, open a PR.

*Made by a teacher, for learners. Built by a teacher in New York.*
