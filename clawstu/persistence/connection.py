"""SQLite connection factory for the persistence layer (spec §4.6).

Every SQLite connection created here goes through the same setup:

- WAL journal mode (so readers and writers don't block each other).
- Foreign keys enabled (so the `sessions.learner_id` constraint
  actually fires).
- FTS5 probe at open time — the ``page_text_index`` virtual table is
  FTS5-backed, and FTS5 is a compile-time option that may be absent
  from custom-built stdlib sqlite3. Missing FTS5 raises
  `PersistenceError` with a clear remediation message rather than
  exploding later from a `CREATE VIRTUAL TABLE ... USING fts5`
  failure.

`initialize_database` is a one-shot that applies every CREATE from
`clawstu.persistence.schema` inside a transaction. It is idempotent
because every statement uses ``IF NOT EXISTS``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from clawstu.persistence.schema import CREATE_STATEMENTS, FTS5_PROBE

FTS5_UNAVAILABLE_MESSAGE = (
    "SQLite FTS5 is required but not available in this build. "
    "Install Python via python.org or a distribution whose stdlib "
    "sqlite3 ships with FTS5 enabled."
)


class PersistenceError(RuntimeError):
    """Raised for any recoverable failure in the persistence layer.

    The only thing we raise this for in Phase 3 is missing FTS5
    support. Future phases may grow additional subclasses.
    """


class _ProbeCursor(Protocol):
    def fetchone(self) -> tuple[int, ...] | None: ...


class _ProbeConnection(Protocol):
    def execute(self, sql: str, /) -> _ProbeCursor: ...


def probe_fts5(conn: _ProbeConnection) -> bool:
    """Return True if FTS5 is available on ``conn``.

    Raises `PersistenceError` if the probe returns 0 (explicitly
    disabled in this build). Any other result — including a sqlite3
    version so old that the compileoption function is missing — will
    propagate the underlying exception.
    """
    row = conn.execute(FTS5_PROBE).fetchone()
    enabled = bool(row[0]) if row else False
    if not enabled:
        raise PersistenceError(FTS5_UNAVAILABLE_MESSAGE)
    return True


def open_connection(db_path: Path | str) -> sqlite3.Connection:
    """Return a ready-to-use connection to ``db_path``.

    The connection has WAL journaling and foreign keys enabled, and
    has already passed the FTS5 probe. Callers are responsible for
    closing the connection.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        probe_fts5(conn)
    except Exception:
        conn.close()
        raise
    return conn


def initialize_database(conn: sqlite3.Connection) -> None:
    """Run every CREATE in `CREATE_STATEMENTS` against ``conn``.

    Wrapped in a single transaction so a mid-schema failure leaves no
    partial tables. Safe to call repeatedly — all statements use
    ``IF NOT EXISTS``.
    """
    with conn:
        for statement in CREATE_STATEMENTS:
            conn.execute(statement)
