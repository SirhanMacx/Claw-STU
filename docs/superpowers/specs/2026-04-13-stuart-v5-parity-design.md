# Stuart v5.0 Architecture Spec (v4.13.2026)

**Status:** Draft
**Author:** SirhanMacx + Claude Opus 4.6
**Date:** 2026-04-13
**Supersedes:** SessionRunner as sole orchestration path

---

## 1. Core Principle

Ed builds lessons for a class of 30. Stuart generates exactly what ONE student
needs, in the modality that works for THEM, and nothing more.

Stuart does not produce a full lesson bundle. Stuart observes what the learner
struggles with, picks the right modality, generates THAT artifact, checks
understanding, and adapts. Same generative power as Ed, applied surgically --
one artifact at a time, chosen by the learner model.

---

## 2. Architecture Overview

```
                        CURRENT (v4.12)                   V5 (v4.13)
                  +---------------------+          +------------------------+
  Student input   |   InboundSafetyGate |          |   InboundSafetyGate    |
        |         +---------------------+          +------------------------+
        v                   |                                |
  +-------------+           v                                v
  |SessionRunner|   hardcoded state       +---------------------------------+
  |  (phases)   |   machine: onboard ->   | AgentLoop (max 10 iter/turn)    |
  +-------------+   calibrate -> teach -> |   - reads learner profile       |
        |           check -> adapt ->     |   - selects tool (or Q&A path)  |
        v           close                 |   - executes tool               |
  +-------------+                         |   - checks understanding        |
  | LLM chain   |                         |   - decides next move           |
  +-------------+                         +---------------------------------+
        |                                     |         |         |
        v                                     v         v         v
  +-------------+                         generate_*  export_*  search_*
  |  Outbound   |                             |         |         |
  |  filters    |                             v         v         v
  +-------------+                         +---------------------------------+
                                          |  OutboundContentFilter          |
                                          |  BoundaryEnforcer               |
                                          +---------------------------------+
                                                        |
                                                        v
                                                    Student
```

The `SessionRunner` becomes one tool the agent can call -- not the entire
architecture. Simple Q&A and structured sessions still use the current path.
The agent loop activates when the student's request requires generation.

---

## 3. Module Map

```
clawstu/
  agent/                        # NEW -- agent loop package
    __init__.py
    loop.py                     # tool-use agent loop
    tools/                      # auto-discovered tool modules
      __init__.py               # discovery + registry
      generate_worksheet.py
      generate_game.py
      generate_visual.py
      generate_simulation.py
      generate_animation.py
      generate_slides.py
      generate_study_guide.py
      generate_practice_test.py
      generate_flashcards.py
      export_pdf.py
      export_docx.py
      export_html.py
      export_flashcards.py
      search_web.py
      search_teacher_materials.py
      search_brain.py
      fetch_source.py
      read_learner_profile.py
      write_session_note.py
      read_concept_wiki.py
      review_misconceptions.py
      run_session.py            # wraps existing SessionRunner
    prompt.py                   # composable system prompt builder
    approvals.py                # tool-execution approval policy
  engagement/
    session.py                  # EXISTING -- SessionRunner stays
  orchestrator/
    chain.py                    # EXISTING -- ReasoningChain stays
  safety/                       # EXISTING -- all gates reused
```

---

## 4. Agent Loop (`agent/loop.py`)

### 4.1 Interface

```python
class AgentLoop:
    """Tool-use agent loop. Max iterations per turn: 10."""

    def __init__(
        self,
        *,
        router: ModelRouter,
        prompt_builder: PromptBuilder,
        tool_registry: ToolRegistry,
        approval_policy: ApprovalPolicy,
        safety_gate: InboundSafetyGate,
        content_filter: ContentFilter,
        boundary_enforcer: BoundaryEnforcer,
    ) -> None: ...

    async def run_turn(
        self,
        student_message: str,
        learner_profile: LearnerProfile,
        session_context: SessionContext,
    ) -> TurnResult: ...
```

### 4.2 Turn Lifecycle

```
1. InboundSafetyGate.scan(student_message)
   -> crisis? escalate immediately
   -> boundary? return canonical restate

2. PromptBuilder.build(learner_profile, session_context)
   -> system prompt with ZPD, age bracket, modality prefs, brain pages

3. LLM call with tool definitions
   -> model returns text OR tool_use block

4. If tool_use:
   a. ApprovalPolicy.check(tool_name, tool_args) -> allow/deny
   b. ToolRegistry.execute(tool_name, tool_args, learner_context)
   c. Feed tool result back to model (loop, max 10 iterations)

5. Final text response:
   a. ContentFilter.scan(text, age_bracket)
   b. BoundaryEnforcer.scan_outbound(text)
   c. Return to student
```

### 4.3 Data Types

```python
@dataclass(frozen=True)
class TurnResult:
    response_text: str
    artifacts: list[GeneratedArtifact]   # files produced this turn
    tool_calls: list[ToolCallRecord]     # audit log
    profile_updates: list[ObservationEvent]

@dataclass(frozen=True)
class GeneratedArtifact:
    artifact_type: str          # "worksheet", "game", "simulation", etc.
    content: str | bytes        # raw content
    filename: str               # suggested filename
    mime_type: str              # "text/html", "application/pdf", etc.
    metadata: dict[str, Any]    # tool-specific metadata

@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]
    result_summary: str
    duration_ms: int
    approved: bool
```

### 4.4 Iteration Cap

Hard cap of 10 tool-use iterations per turn. If the model has not produced a
final text response after 10 iterations, the loop returns a graceful fallback:
"Let me simplify. Here's what I have so far..." plus any artifacts generated.

---

## 5. Generation Tools

Every generation tool implements:

```python
class GenerationTool(Protocol):
    """Protocol all generation tools satisfy."""

    name: str
    description: str

    async def execute(
        self,
        *,
        topic: str,
        learner: LearnerProfile,
        brain_context: list[BrainPage],
        params: dict[str, Any],
    ) -> GeneratedArtifact: ...
```

### 5.1 Tool Catalog

| Tool | Output | Format |
|------|--------|--------|
| `generate_worksheet` | Scaffolded practice at learner ZPD | Markdown/HTML |
| `generate_game` | Matching, sorting, timeline, quiz game | Standalone HTML |
| `generate_visual` | Diagram, timeline, concept map, cause-effect | SVG/HTML |
| `generate_simulation` | Interactive simulation (physics, math, scenarios) | Standalone HTML |
| `generate_animation` | Manim-style animated explanation | HTML/MP4 |
| `generate_slides` | 3-5 slide mini deck for visual learners | HTML |
| `generate_study_guide` | Condensed review from session history | Markdown |
| `generate_practice_test` | Assessment at learner level + answer key | Markdown/HTML |
| `generate_flashcards` | Spaced repetition cards | JSON (Anki/Quizlet) |

### 5.2 Generation Pipeline (all tools)

```
1. Read learner profile -> ZPD tier, age bracket, domain, modality outcomes
2. Read relevant brain pages -> what Stuart knows about this student's grasp
3. Build generation prompt -> topic + constraints from (1) + context from (2)
4. LLM generation -> raw artifact content
5. ContentFilter.scan(content, age_bracket) -> block or allow
6. BoundaryEnforcer.scan_outbound(content) -> strip sycophancy
7. Return GeneratedArtifact
```

Step 5-6 are non-negotiable. No generated content reaches the student without
passing both filters.

---

## 6. Export Tools

```python
class ExportTool(Protocol):
    async def execute(
        self,
        *,
        artifact: GeneratedArtifact,
        output_path: Path | None = None,
    ) -> ExportResult: ...

@dataclass(frozen=True)
class ExportResult:
    path: Path
    size_bytes: int
    format: str   # "pdf", "docx", "html", "apkg"
```

| Tool | Input | Output |
|------|-------|--------|
| `export_pdf` | Any artifact | Clean PDF via WeasyPrint |
| `export_docx` | Worksheets, study guides | Word doc via python-docx |
| `export_html` | Simulations, games | Standalone HTML (self-contained) |
| `export_flashcards` | Flashcard artifact | Anki `.apkg` or Quizlet CSV |

---

## 7. Research / Retrieval Tools

```python
class RetrievalTool(Protocol):
    async def execute(
        self,
        *,
        query: str,
        learner: LearnerProfile,
        max_results: int = 5,
    ) -> list[RetrievalResult]: ...

@dataclass(frozen=True)
class RetrievalResult:
    title: str
    snippet: str
    source_url: str | None
    relevance_score: float
    age_appropriate: bool
```

| Tool | Source | Notes |
|------|--------|-------|
| `search_web` | Web (age-filtered) | SafeSearch enforced, results filtered by age bracket |
| `search_teacher_materials` | Shared KB (`SHARED_KB_PATH`) | Queries Ed's ingested curriculum |
| `search_brain` | BrainStore | Existing memory/search.py, formalized as tool |
| `fetch_source` | Specific URL/doc | Retrieve + summarize, age-gated |

### 7.1 Teacher Material Priority

When teacher materials exist in the shared KB, `search_teacher_materials` runs
FIRST. Web search is a fallback. Stuart teaches from the teacher's sources, not
random internet content.

---

## 8. Memory & Context Tools

These formalize existing memory subsystem access as agent tools:

| Tool | Operation | Backing Module |
|------|-----------|----------------|
| `read_learner_profile` | Read current ZPD, modality prefs, history | `profile.model` |
| `write_session_note` | Record observation during session | `memory.writer` |
| `read_concept_wiki` | What Stuart knows about a concept | `memory.wiki` |
| `review_misconceptions` | What this student consistently gets wrong | `memory.pages.MisconceptionPage` |

---

## 9. Approval Policy (`agent/approvals.py`)

Student safety is paramount. Every tool execution is gated:

```python
class ApprovalPolicy:
    """Decides whether a tool call is allowed to execute."""

    ALWAYS_ALLOWED: ClassVar[set[str]] = {
        "read_learner_profile",
        "read_concept_wiki",
        "review_misconceptions",
        "search_brain",
    }

    REQUIRES_GENERATION_BUDGET: ClassVar[set[str]] = {
        "generate_worksheet", "generate_game", "generate_visual",
        "generate_simulation", "generate_animation", "generate_slides",
        "generate_study_guide", "generate_practice_test", "generate_flashcards",
    }

    NEVER_ALLOWED: ClassVar[set[str]] = set()  # reserved for future lockdowns

    def check(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session_context: SessionContext,
    ) -> ApprovalDecision: ...
```

**Generation budget:** Max 3 generation tool calls per turn. Prevents runaway
artifact production from a single student message.

---

## 10. Safety Invariants

These hold across the entire v5 architecture. Violations are P0 bugs.

1. **No unfiltered output.** Every string shown to a student passes through
   `ContentFilter.scan()` AND `BoundaryEnforcer.scan_outbound()`.
2. **No ungated tool execution.** Every tool call passes through
   `ApprovalPolicy.check()` before execution.
3. **Crisis detection on every message.** `InboundSafetyGate.scan()` runs
   before the agent loop sees any student input.
4. **Age-bracket awareness.** All generation tools receive the learner's
   `AgeBracket` and produce content appropriate to that bracket.
5. **No sycophancy.** `BoundaryEnforcer` strips performative praise,
   emotional claims, and friend-roleplay from all outbound text.
6. **Iteration cap.** Agent loop hard-stops at 10 iterations per turn.
7. **Generation budget.** Max 3 generation tool calls per turn.
8. **Teacher materials first.** When shared KB exists, teacher content takes
   priority over web search.

---

## 11. Shared KB Bridge

```
Ed (Claw-ED)                          Stuart (Claw-STU)
+-------------------+                 +-------------------+
| clawed ingest     |                 | search_teacher_   |
|   <materials>     |   reads from    |   materials tool   |
|        |          |  <------------- |        |          |
|        v          |                 |        v          |
| ~/.eduagent/kb/   |                 | SHARED_KB_PATH    |
|   sources/        |                 |   env var         |
|   embeddings/     |                 +-------------------+
+-------------------+

Config: SHARED_KB_PATH=~/.eduagent/kb  (or custom path)
```

When `SHARED_KB_PATH` is set, Stuart's `search_teacher_materials` queries Ed's
knowledge base. When unset, the tool returns an empty result (not an error).

---

## 12. CLI Additions

Current commands: `learn`, `resume`, `wiki`, `progress`, `history`, `review`,
`setup`, `serve`, `doctor`, `scheduler`, `profile`.

### v5 additions:

```python
@app.command()
def generate(
    artifact_type: str = typer.Argument(..., help="worksheet|game|visual|simulation|..."),
    topic: str = typer.Argument(..., help="Topic to generate for"),
    learner_id: str = typer.Option(None, help="Target learner (default: last active)"),
) -> None: ...

@app.command()
def export(
    session_id: str = typer.Argument(..., help="Session to export from"),
    fmt: str = typer.Argument("pdf", help="pdf|docx|html|flashcards"),
) -> None: ...

@app.command()
def ingest(path: Path = typer.Argument(..., help="Materials to ingest into shared KB")) -> None: ...

@app.command()
def search(query: str = typer.Argument(..., help="Search brain + teacher materials")) -> None: ...

@app.command()
def flashcards(topic: str = typer.Argument(...)) -> None: ...

@app.command()
def practice(topic: str = typer.Argument(...)) -> None: ...

@app.command()
def game(topic: str = typer.Argument(...)) -> None: ...
```

---

## 13. Telegram Additions

Current commands: `/start`, `/learn`, `/ask`, `/progress`, `/quit`, `/help`.

### v5 additions:

| Command | Handler | Notes |
|---------|---------|-------|
| `/game <topic>` | Generates game, sends as HTML doc | Falls back to text quiz |
| `/practice <topic>` | Generates practice problems | Inline message |
| `/flashcards <topic>` | Generates flashcards | Sends as document |
| `/export` | Exports current session as PDF | Sends as document |
| `/study <topic>` | Generates study guide | Sends as document |

Artifact delivery: Telegram `send_document` for PDFs, HTML files, flashcard
exports. Inline message for text-only artifacts (practice problems, short
study guides).

---

## 14. Composable System Prompt (`agent/prompt.py`)

```python
class PromptBuilder:
    """Composes the agent's system prompt from learner context."""

    def build(
        self,
        learner: LearnerProfile,
        session_context: SessionContext,
        brain_pages: list[BrainPage],
    ) -> str:
        """Returns system prompt with these sections:

        1. SOUL.md core identity
        2. Learner context block:
           - Age bracket, domain, current ZPD tier
           - Modality outcome history (what works, what doesn't)
           - Active misconceptions
           - Session history summary
        3. Tool usage instructions
        4. Safety constraints (from SOUL.md non-identity rules)
        5. Brain page summaries (relevant concept pages)
        """
        ...
```

The prompt is rebuilt on every turn. Learner context is fresh, not stale.

---

## 15. Tool Discovery (`agent/tools/__init__.py`)

```python
class ToolRegistry:
    """Auto-discovers tool modules from the tools/ directory."""

    def discover(self) -> None:
        """Scan agent/tools/ for modules with a TOOL_DEF attribute."""
        ...

    def get_definitions(self) -> list[ToolDefinition]:
        """Return Anthropic tool-use format definitions for all tools."""
        ...

    def execute(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        learner_context: LearnerContext,
    ) -> Any:
        """Look up and execute a tool by name."""
        ...
```

Each tool module exports a `TOOL_DEF: ToolDefinition` and an `execute` async
function. New tools are added by dropping a file in `agent/tools/`.

---

## 16. Migration Path

| Phase | Scope | Success Criteria |
|-------|-------|------------------|
| 1 | Add `clawstu/agent/` package: loop, tools, prompt, approvals | Unit tests for loop lifecycle, approval policy |
| 2 | Port generation tools from Ed (single-learner adapted) | 9 tools produce artifacts, all pass content filter |
| 3 | Port export tools | PDF, DOCX, HTML, flashcard export from artifacts |
| 4 | Add retrieval tools (web search, teacher KB) | `search_teacher_materials` reads from shared KB path |
| 5 | CLI and Telegram parity | All 7 new CLI commands work; 5 new Telegram commands |
| 6 | Shared KB bridge | Ed ingest -> Stuart search end-to-end |

**Compatibility:** The existing `SessionRunner` remains the default for
structured sessions. The agent loop is activated when the student's request
requires generation or retrieval. No breaking changes to the API or existing
CLI commands.

---

## 17. Version

This spec targets **v4.13.2026.0** (Claw-STU). The version bump signals the
architectural shift from "session runner" to "personal learning agent."
