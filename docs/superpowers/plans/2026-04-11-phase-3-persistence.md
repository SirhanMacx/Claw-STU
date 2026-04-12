# Phase 3 Implementation Plan: Persistence (SQLite)

**Goal:** Add a SQLite-backed `PersistentStore` with typed entity stores, FTS5 probe, and in-memory test variant. Wire `AppState` to checkpoint/restore via the store while preserving the existing mutation-in-place contract through an identity cache.

**Architecture:** `clawstu/persistence/` owns all SQL. One connection factory with WAL + foreign keys + FTS5 probe. Entity stores (`LearnerStore`, `SessionStore`, `EventStore`, `ZPDStore`, `ModalityStore`, `MisconceptionStore`, `ArtifactStore`, `KGStore`, `SchedulerRunStore`) are thin typed wrappers. `PersistentStore` aggregates them. `InMemoryPersistentStore` shares the same interface for tests. `AppState` wraps `PersistentStore` with an LRU identity cache keyed by `session_id`, so mutations-in-place propagate but survive process restart after explicit `checkpoint()`. Foreign keys on: `sessions.learner_id → learners.learner_id`.

**Tech Stack:** `sqlite3` stdlib, pydantic v2, no ORM, `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`, `CREATE VIRTUAL TABLE ... USING fts5`.

---

## Task 0: Baseline

Verify HEAD `d2a0f76`, 174 tests, mypy + ruff clean.

## Task 1: `clawstu/persistence/schema.py` — raw SQL + FTS5 probe

**Files:**
- Create: `clawstu/persistence/__init__.py` (empty package marker)
- Create: `clawstu/persistence/schema.py`
- Create: `tests/test_persistence_schema.py`

**Contents of schema.py:**
- Module docstring citing spec §4.6.2
- `CREATE_STATEMENTS: tuple[str, ...]` = list of all 11 CREATE TABLE / CREATE INDEX / CREATE VIRTUAL TABLE statements from the spec
- `FTS5_PROBE = "SELECT sqlite_compileoption_used('ENABLE_FTS5')"`
- No runtime logic, just string constants

**Test (`tests/test_persistence_schema.py`):** 3 tests
1. `test_schema_contains_all_expected_tables` — assert every table name from §4.6.2 appears in `CREATE_STATEMENTS`
2. `test_fts5_probe_is_valid_sql` — parse the probe via `sqlite3.complete_statement`
3. `test_schema_creates_on_fresh_memory_db` — run every CREATE statement against `:memory:` and confirm no errors

**Commit:** `feat(persistence): schema.py with all §4.6.2 tables`

## Task 2: `clawstu/persistence/connection.py` — factory + WAL + FTS5 probe

**Files:**
- Create: `clawstu/persistence/connection.py`
- Create: `tests/test_persistence_connection.py`

**Contents of connection.py:**
- `PersistenceError(RuntimeError)` exception class
- `FTS5_UNAVAILABLE_MESSAGE = "SQLite FTS5 is required..."`
- `open_connection(db_path: Path) -> sqlite3.Connection` — opens WAL, foreign keys, runs FTS5 probe, raises `PersistenceError` on probe fail
- `initialize_database(conn: sqlite3.Connection) -> None` — runs every statement in `CREATE_STATEMENTS` in a transaction

**Tests:** 5 tests
1. Fresh DB creates all tables
2. WAL mode confirmed via `PRAGMA journal_mode`
3. Foreign keys enabled
4. FTS5 probe succeeds on stdlib Python
5. `PersistenceError` raised when probe returns 0 (via monkey-patched connection that makes the probe return 0)

**Commit:** `feat(persistence): connection factory with WAL + FTS5 probe`

## Task 3: `clawstu/persistence/store.py` — entity stores

**Files:**
- Create: `clawstu/persistence/store.py`
- Create: `tests/test_persistence_store.py`

**Contents of store.py:**
- `LearnerStore` with `upsert(profile: LearnerProfile)` and `get(learner_id: str) -> LearnerProfile | None`
- `SessionStore` with `upsert(session: Session)` / `get(session_id: str) -> Session | None` / `list_for_learner(learner_id: str) -> list[Session]`
- `EventStore` with `append(event: ObservationEvent, learner_id: str, session_id: str | None)` / `list_for_learner(learner_id: str) -> list[ObservationEvent]`
- `ZPDStore`, `ModalityStore`, `MisconceptionStore` — upsert_all + get_all
- `ArtifactStore` — upsert + get + mark_consumed (for next_session_artifacts)
- `KGStore` — append triple + find_by_subject
- `SchedulerRunStore` — append + list_recent
- `PersistentStore` wrapper class holding all the above, plus `initialize()` and `close()`
- `InMemoryPersistentStore` — in-memory dict-based variant implementing the same interface

**Tests:** 15+ tests covering round-trip for every entity type, both SQLite and InMemory variants (via parametrize).

**Commit:** `feat(persistence): typed entity stores + InMemoryPersistentStore`

## Task 4: `clawstu/persistence/migrations.py` — minimal runner

**Files:**
- Create: `clawstu/persistence/migrations.py`
- Create: `tests/test_persistence_migrations.py`

**Contents:**
- `PRAGMA user_version` based versioning
- `MIGRATIONS: list[tuple[int, str]]` — (version, sql) pairs, starts with `[(1, <all CREATE_STATEMENTS joined>)]`
- `migrate(conn)` — reads current user_version, applies pending, bumps version
- Idempotent — running twice is a no-op

**Tests:** 3 tests — fresh DB reaches latest version, already-migrated is no-op, partial failure rolls back.

**Commit:** `feat(persistence): minimal migration runner`

## Task 5: Wire `AppState` to `PersistentStore` with identity cache

**Files:**
- Modify: `clawstu/api/state.py`
- Modify: `tests/conftest.py` — add `sqlite_in_memory` fixture
- Create: `tests/test_app_state_persistence.py`

**Contents of new AppState:**
- Takes `persistence: PersistentStore` in __init__
- LRU cache (`collections.OrderedDict`) keyed by session_id, default max 1024 (configurable via `STU_SESSION_CACHE_SIZE`)
- `put`, `get`, `drop`, `checkpoint` methods per spec §4.6.4
- `get_state()` reads `STU_SESSION_CACHE_SIZE` env var + builds a module-level singleton with `InMemoryPersistentStore` by default (SQLite wiring waits for explicit config)

**Tests:**
- Existing `tests/test_api.py` + `tests/test_session_flow.py` still green with the new AppState
- New tests: mutation-in-place propagation (put→get returns same object by identity), checkpoint before drop writes to persistence, cache eviction re-persists before eviction

**Commit:** `feat(api): AppState wraps PersistentStore with LRU identity cache`

## Task 6: Final regression + push

Full suite, mypy, ruff, CI green.
