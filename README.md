# Claw-STU

**Stuart** — a personal learning agent that grows with the student.

Claw-STU is the student-facing counterpart to [Claw-ED](https://github.com/sirhanmacx/claw-ed),
the teacher-facing pedagogical agent. Where Claw-ED asks *"How does this teacher teach?"*,
Claw-STU asks *"How does this student learn?"* — and adapts continuously.

> Every kid deserves a Stuart.

## Vision

The traditional education pipeline (K-12 → college → career) is structurally dependent on
the existence of jobs at the end. As AI systems increasingly perform knowledge work at or
above human capability, that pipeline is fracturing. Meanwhile, the craft of education —
teaching humans how to think, reason, evaluate evidence, tolerate ambiguity, and adapt to
novel situations — has never been more important.

Claw-STU exists to serve the learner directly, independent of any institution. It is not a
tutoring bot, not a content-delivery system. It is a personal learning agent that builds a
learner profile from observed interactions and delivers instruction calibrated to the
student's Zone of Proximal Development (ZPD).

See [`Handoff.md`](./Handoff.md) for the full vision document and pedagogical philosophy.

## Core Principles

1. **ZPD always.** The agent operates between what the student can do alone and what
   they can do with support. Too easy = disengagement. Too hard = shutdown.
2. **Differentiation is not optional.** Multiple tiers of complexity, multiple modalities
   (text, visual, interactive, Socratic). The *agent* observes what works — the student
   does not pick from a menu.
3. **Check for understanding, then proceed.** No forward progress without verification.
   Constructed-response questions over click-through quizzes.
4. **Primary sources over summaries.** Especially in humanities. HAPP framework
   (Historical context, Audience, Purpose, Point of view) as default for source analysis.
5. **The agent is not the teacher.** Stuart is a cognitive tool. It does not simulate
   friendship, intimacy, or emotional care. Warm and honest — but always a tool.

## Architecture

```
claw-stu/
├── SOUL.md                  # Stuart's identity and behavioral constraints
├── HEARTBEAT.md             # Runtime health and self-monitoring contract
├── src/
│   ├── profile/             # Learner profile engine
│   ├── curriculum/          # Content and pathway management
│   ├── assessment/          # Check-for-understanding engine
│   ├── engagement/          # Session management and signal processing
│   ├── safety/              # Guardrails, escalation, boundaries
│   ├── orchestrator/        # LLM provider abstraction and prompts
│   └── api/                 # FastAPI routes
└── tests/                   # Test suite (test-first, always)
```

## Getting Started

Requires Python 3.11+.

```bash
# Install in editable mode with dev extras
pip install -e ".[dev]"

# Run the test suite
pytest

# Start the API locally
uvicorn src.api.main:app --reload
```

Once the server is running, the interactive docs live at `http://localhost:8000/docs`.

## Status

Pre-alpha. The MVP target is a single adaptive learning session:

1. **Onboard** — age + topic of interest, no login
2. **Calibrate** — 3–5 varied-format diagnostic questions to seed a ZPD baseline
3. **Teach** — one ~10-minute learning block in the best-guess modality
4. **Check** — a constructed-response question (not multiple choice)
5. **Adapt** — advance, re-teach via a *different* modality, or deepen
6. **Close** — summary, profile update

## Safety & Privacy

- The learner profile is **owned by the student**. It is portable, exportable, and
  deletable on demand.
- No ads, no data sales, no behavioral tracking for third parties — ever.
- Age-appropriate content filtering is foundational, not a feature flag.
- Crisis signals (self-harm, abuse, acute distress) trigger immediate human-resource
  escalation. Stuart does not counsel.

## License

MIT — see [`LICENSE`](./LICENSE). Open source by conviction, not convenience.

---

*Made by a teacher, for learners. Built by a teacher in New York.*
