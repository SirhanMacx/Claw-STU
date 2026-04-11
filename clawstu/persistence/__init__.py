"""SQLite persistence layer for Claw-STU.

This package owns all SQL in the project. Everything outside
`clawstu.persistence` goes through typed entity stores that take and
return pydantic models — no other module imports `sqlite3` directly.

See spec `docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md`
section 4.6 for the full design. Phase 3 delivers schema.py, connection.py,
store.py (entity stores + InMemoryPersistentStore), migrations.py, and
wires `clawstu.api.state.AppState` to a persistent store with an LRU
identity cache so the existing mutation-in-place contract survives the
transition.
"""

from __future__ import annotations
