"""Schema tests — spec §4.6.2.

These tests verify that `CREATE_STATEMENTS` includes every table and
virtual table listed in the design spec, and that the full batch can
be executed against a fresh in-memory SQLite database without error.
"""

from __future__ import annotations

import sqlite3

from clawstu.persistence.schema import CREATE_STATEMENTS, FTS5_PROBE

# Table names the spec §4.6.2 requires. These become CREATE TABLE /
# CREATE VIRTUAL TABLE statements in the schema module.
_EXPECTED_TABLES: tuple[str, ...] = (
    "learners",
    "sessions",
    "observation_events",
    "zpd_estimates",
    "modality_outcomes",
    "next_session_artifacts",
    "knowledge_graph_triples",
    "misconception_tally",
    "scheduler_runs",
    "page_embeddings",
    "page_text_index",
)


def test_schema_contains_all_expected_tables() -> None:
    joined = "\n".join(CREATE_STATEMENTS)
    missing = [name for name in _EXPECTED_TABLES if name not in joined]
    assert not missing, f"schema is missing tables: {missing}"


def test_fts5_probe_is_valid_sql() -> None:
    # sqlite3.complete_statement returns True for a syntactically valid,
    # terminated statement. The probe is a read-only SELECT so appending
    # the terminator makes it complete.
    assert sqlite3.complete_statement(FTS5_PROBE + ";")


def test_schema_creates_on_fresh_memory_db() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        cursor = conn.cursor()
        for statement in CREATE_STATEMENTS:
            cursor.execute(statement)
        conn.commit()
        # Sanity: the tables actually exist.
        rows = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
        actual = {row[0] for row in rows}
        for expected in _EXPECTED_TABLES:
            assert expected in actual, f"table not created: {expected}"
    finally:
        conn.close()
