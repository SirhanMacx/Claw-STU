"""Minimal migration runner.

The persistence layer uses SQLite's `PRAGMA user_version` to track which
schema migrations have been applied. Each migration is a `(version, sql)`
tuple in the module-level `MIGRATIONS` list. `migrate(conn)` reads the
current version, applies every pending migration in order under a
transaction, and bumps `user_version` after each successful step.

Phase 3 ships exactly one migration: a single SQL string that joins
every CREATE statement from `clawstu.persistence.schema` so a fresh
database catches up to the spec §4.6.2 schema in one shot. Future
phases will append additional `(version, sql)` tuples; the runner is
designed to never re-apply an already-applied version, even if it is
called many times in the lifetime of a process.

The runner is wrapped in `with conn:` so any error inside a single
migration's SQL rolls back atomically — the user_version pragma is
written inside the same transaction as the migration body, so a
failure leaves both the schema state and the version pointer
untouched.
"""

from __future__ import annotations

import sqlite3

from clawstu.persistence.schema import CREATE_STATEMENTS

# The single Phase 3 migration body — every CREATE statement joined
# by `;` so it can be applied in one executescript() call. Each
# statement individually uses `IF NOT EXISTS`, so re-running the body
# against an already-populated database is safe.
_PHASE3_DDL = ";\n".join(stmt.strip() for stmt in CREATE_STATEMENTS) + ";"

MIGRATIONS: list[tuple[int, str]] = [
    (1, _PHASE3_DDL),
]


def _max_target_version() -> int:
    return max((version for version, _sql in MIGRATIONS), default=0)


# Module-level snapshot used by `LATEST_VERSION`. Tests that mutate
# MIGRATIONS at runtime should call `_max_target_version()` instead.
LATEST_VERSION: int = _max_target_version()


def current_version(conn: sqlite3.Connection) -> int:
    """Return the connection's `PRAGMA user_version`."""
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    value = row[0]
    if not isinstance(value, int):
        raise RuntimeError(f"unexpected user_version row: {row!r}")
    return value


def _split_statements(sql: str) -> list[str]:
    """Split a multi-statement migration body into individual statements.

    `sqlite3.Connection.executescript` issues an implicit COMMIT before
    running its body, so it cannot participate in the surrounding
    transaction. Splitting on `;` and running each piece via `execute`
    keeps the migration atomic — a failure mid-way rolls everything
    back to the pre-migration state.
    """
    pieces = [piece.strip() for piece in sql.split(";")]
    return [piece for piece in pieces if piece]


def migrate(conn: sqlite3.Connection) -> None:
    """Apply every pending migration to ``conn``.

    Each migration runs inside its own transaction so a failure
    leaves the schema and the version pointer untouched. Migrations
    that have already been applied are skipped silently — the runner
    is safe to call repeatedly.
    """
    current = current_version(conn)
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        statements = _split_statements(sql)
        try:
            conn.execute("BEGIN")
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = version
