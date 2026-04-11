"""Connection factory tests — spec §4.6.2 / §4.6.3.

Covers: fresh database initialization, WAL journal mode, foreign-key
enforcement, the FTS5 probe success path, and the FTS5 probe failure
path (where we inject a fake connection so the real sqlite3 FTS5 build
doesn't matter).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from clawstu.persistence.connection import (
    PersistenceError,
    initialize_database,
    open_connection,
    probe_fts5,
)


def test_open_connection_returns_initialized_db(tmp_path: Path) -> None:
    db_path = tmp_path / "stu.db"
    conn = open_connection(db_path)
    try:
        initialize_database(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
        tables = {row[0] for row in rows}
        assert "learners" in tables
        assert "page_text_index" in tables
    finally:
        conn.close()


def test_open_connection_enables_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "wal.db"
    conn = open_connection(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        # WAL shows up as "wal" on file-backed DBs.
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_open_connection_enables_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "fk.db"
    conn = open_connection(db_path)
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
    finally:
        conn.close()


def test_probe_fts5_returns_true_on_real_sqlite() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        assert probe_fts5(conn) is True
    finally:
        conn.close()


def test_probe_fts5_raises_persistence_error_when_disabled() -> None:
    class FakeCursor:
        def fetchone(self) -> tuple[int]:
            return (0,)

    class FakeConnection:
        def execute(self, _sql: str) -> FakeCursor:
            return FakeCursor()

    fake: Any = FakeConnection()
    with pytest.raises(PersistenceError) as excinfo:
        probe_fts5(fake)
    assert "FTS5" in str(excinfo.value)
