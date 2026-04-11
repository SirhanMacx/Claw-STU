"""Memory layer — brain pages, hybrid search, context assembly.

The memory layer owns the "brain" of the learning agent. It encodes:

- **Brain pages** (`clawstu.memory.pages`): small pydantic models for
  Learner / Concept / Session / Source / Misconception / Topic pages,
  each rendered as a markdown file with a YAML-ish frontmatter block.
- **Store** (`clawstu.memory.store`): atomic file-backed CRUD over
  those pages, hashed per-learner subdirectories under
  `~/.claw-stu/brain/`.
- **Embeddings** (`clawstu.memory.embeddings`): a protocol plus two
  implementations — a zero-vector `NullEmbeddings` that is the default
  in Phase 4, and an `OnnxEmbeddings` scaffold that Phase 6 will wire
  to the real sentence-transformers MiniLM weights.
- **Search** (`clawstu.memory.search`): a hybrid keyword + vector
  retrieval with Reciprocal Rank Fusion, which degenerates to
  keyword-only when embeddings aren't ready.
- **Context assembly** (`clawstu.memory.context`): pulls a bounded
  prompt-injectable slice of the brain for a given learner + concept.
- **Write path** (`clawstu.memory.writer`): the post-session hook that
  mints a SessionPage, updates the LearnerPage, and refreshes each
  ConceptPage the session touched.
- **Dream cycle** (`clawstu.memory.dream`): the overnight compiled-truth
  rewrite pass. Idempotent — a second run over an unchanged brain is
  a no-op.
- **Knowledge graph** (`clawstu.memory.knowledge_graph`): a thin
  memory-layer facade over `clawstu.persistence.store.KGStore`.
- **Concept wiki** (`clawstu.memory.wiki`): the user-visible
  per-(learner, concept) document answering "why did you show me this?"
- **Source capture** (`clawstu.memory.capture`): entry point for
  student-shared materials; Phase 4 ships the page-writing half, the
  API wiring lands in Phase 5.

Layering: `clawstu.memory` may import from stdlib, pydantic, numpy,
`clawstu.profile.*`, `clawstu.persistence.*`, and `clawstu.safety.*`.
It MUST NOT reach into curriculum, assessment, engagement, or
orchestrator — those layers depend on memory, not the other way around.
The import DAG is enforced by `tests/test_hierarchy.py`.
"""

from __future__ import annotations
