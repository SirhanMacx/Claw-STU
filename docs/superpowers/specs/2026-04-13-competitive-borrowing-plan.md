# Competitive Borrowing Plan — What to Take, What to Skip

## Sources Analyzed
1. **DeepTutor** (HKUDS) — RAG-powered tutoring with multi-agent problem solving
2. **Karpathy Skills** (forrestchang) — Behavioral guidelines for LLM coding agents
3. **Multica** (multica-ai) — Managed multi-agent platform with persistent skills

---

## What We Already Have That They Don't

| Capability | Claw-ED + Claw-STU | DeepTutor | Karpathy | Multica |
|---|---|---|---|---|
| ZPD-based learner modeling | ✅ | ❌ | ❌ | ❌ |
| Safety gates (crisis, boundary, sycophancy) | ✅ | ❌ | ❌ | ❌ |
| Pedagogical strategies (CRQ, scaffolding) | ✅ | ❌ | ❌ | ❌ |
| Teacher voice preservation (soul.md) | ✅ | ❌ | ❌ | ❌ |
| Quality gate (12 checks, auto-retry) | ✅ | ❌ | ❌ | ❌ |
| Multi-format export (DOCX/PPTX/PDF/CC) | ✅ | ❌ | ❌ | ❌ |
| Curriculum KB with 58K+ teacher images | ✅ | ❌ | ❌ | ❌ |

We are stronger on pedagogy. They are stronger on infrastructure patterns.

---

## What to Borrow

### From DeepTutor — 3 ideas

**1. Query Diversification Before Planning** (Priority: HIGH)
- DeepTutor's PlannerAgent generates 3 different search queries per question
- Parallel retrieval → LLM aggregation of diverse results
- **Apply to:** Stuart's `search_brain` and `search_teacher_materials` tools
- **Implementation:** Before answering a student question, generate 3 query variations (rephrase, synonym, related concept), search all three, merge results via reciprocal rank fusion
- **Effort:** ~50 lines in `clawstu/agent/tools/search_brain.py`

**2. Incremental Document Addition** (Priority: MEDIUM)
- DeepTutor can add documents to an existing KB without full re-index
- **Apply to:** Stuart's shared KB bridge and Ed's curriculum KB
- **Implementation:** Ed's `CurriculumKB.index()` already supports this partially; formalize the API so Stuart can trigger incremental adds
- **Effort:** API formalization, no major code change

**3. Unified Workspace Switching** (Priority: LOW)
- DeepTutor lets users switch between Chat → Deep Solve → Quiz within one thread
- **Apply to:** Stuart's agent loop could offer mode hints: "Want me to explain, quiz you, or make a game?"
- **Implementation:** Agent prompt includes mode awareness; tool selection adapts
- **Effort:** Prompt engineering, no code change

### From Karpathy Skills — 4 ideas

**4. Behavioral Contract for Stuart** (Priority: HIGH)
- Karpathy's CLAUDE.md injects behavioral principles into every LLM call
- Stuart should have equivalent behavioral guardrails beyond safety
- **Apply to:** `clawstu/agent/prompt.py` — add a "Stuart's Behavioral Contract" section
- **Principles:**
  - **Check understanding before advancing** — never assume the student got it
  - **Minimal explanation first** — start simple, add complexity only on request
  - **Surface misconceptions explicitly** — name what the student believes vs. reality
  - **One thing at a time** — never teach two concepts in one turn
- **Effort:** ~30 lines in prompt.py

**5. Goal-Driven Learning Loops** (Priority: HIGH)
- Karpathy's "transform imperatives into verifiable goals" maps directly to pedagogy
- **Apply to:** Stuart's session runner and agent loop
- **Transform:** "Teach me the Civil War" → "By end of session: student can identify 3 causes and explain how they connected"
- **Implementation:** Agent generates learning objectives BEFORE teaching, checks them AFTER
- **Effort:** New tool `define_learning_goals` + check in session close

**6. Assumption Surfacing** (Priority: MEDIUM)
- Before solving, Stuart should state what it assumes about the student's current knowledge
- **Apply to:** Agent loop's first turn
- **Implementation:** Prompt instruction: "Before teaching, state your 3 assumptions about what this student already knows. Ask if they're correct."
- **Effort:** Prompt engineering

**7. Surgical Feedback** (Priority: MEDIUM)
- When reviewing student work, give targeted feedback on ONE thing
- **Apply to:** Stuart's check/evaluation phase
- **Implementation:** Evaluator returns primary feedback + secondary (deferred) items
- **Effort:** ~20 lines in `clawstu/assessment/evaluator.py`

### From Multica — 3 ideas

**8. Persistent Skill Compounding** (Priority: HIGH)
- Agent solutions persist as workspace-scoped reusable skills
- **Apply to:** When Stuart generates a worksheet/game/visual that works well, save it as a reusable template
- **Implementation:** After generation + positive student feedback, save the artifact as a "proven template" in brain store
- **Schema:** `BrainPage` type `TemplatePage` — stores the prompt + output + success metrics
- **Effort:** New page type + save logic in agent loop post-execution

**9. Session Resumption Across Tasks** (Priority: MEDIUM)
- Multica preserves session ID so agents can resume context
- Stuart already has session persistence via `cli_state.py`
- **Apply to:** WebSocket and Telegram sessions — allow `clawstu resume <session-id>`
- **Implementation:** Already partially exists; formalize as a first-class CLI command
- **Effort:** Wire existing persistence to `clawstu resume`

**10. Pull-Based Task Queue** (Priority: LOW — future)
- Multica's daemon polls for work instead of being pushed
- **Apply to:** Stuart's scheduler already does background tasks; could expand to teacher-assigned tasks
- **Vision:** Teacher (Ed) assigns "practice fractions" to a student → Stuart picks it up and runs the session autonomously
- **Effort:** Architectural change, defer to v6

---

## What to Skip

| Idea | Source | Why Skip |
|---|---|---|
| Graph-based RAG | DeepTutor | Marketing fiction — not actually implemented. Our KG is already real. |
| LlamaIndex dependency | DeepTutor | Heavy dependency for what our custom vector search already does. |
| Multi-provider LLM abstraction | DeepTutor | Our ModelRouter is already better (task-level routing, fallback chains). |
| Claude Code plugin format | Karpathy | Too narrow — we need cross-platform, not Claude-specific. |
| Go backend | Multica | We're Python. No benefit to rewriting. |
| PostgreSQL + pgvector | Multica | SQLite is correct for local-first. Postgres is server-first. |
| Board/kanban UI | Multica | Not relevant to 1:1 tutoring. |
| TutorBot Discord/WeChat | DeepTutor | We have Telegram. Adding more channels is straightforward later. |

---

## Implementation Priority

### Sprint 1 (This week — prompt + search improvements)
- [4] Behavioral contract in Stuart's system prompt
- [5] Goal-driven learning loops (define objectives → check them)
- [1] Query diversification in search tools

### Sprint 2 (Next week — persistence + feedback)
- [8] Persistent skill/template compounding
- [7] Surgical feedback in evaluator
- [6] Assumption surfacing in first turn

### Sprint 3 (Following week — infrastructure)
- [9] Session resumption CLI command
- [2] Incremental KB addition API
- [3] Mode-aware agent (explain/quiz/game hints)

### Deferred (v6)
- [10] Pull-based task queue for teacher-assigned work
