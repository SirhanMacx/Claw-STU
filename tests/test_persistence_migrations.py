"""Migration runner tests — version-tracked, idempotent, transactional."""

from __future__ import annotations

import sqlite3

import pytest

from clawstu.persistence.connection import open_connection
from clawstu.persistence.migrations import (
    LATEST_VERSION,
    MIGRATIONS,
    current_version,
    migrate,
)


def test_fresh_database_reaches_latest_version() -> None:
    conn = open_connection(":memory:")
    try:
        assert current_version(conn) == 0
        migrate(conn)
        assert current_version(conn) == LATEST_VERSION
        # The migration should have created the learners table.
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='learners'"
        ).fetchall()
        assert rows
    finally:
        conn.close()


def test_migrate_is_idempotent() -> None:
    conn = open_connection(":memory:")
    try:
        migrate(conn)
        migrate(conn)  # second call must be a no-op
        assert current_version(conn) == LATEST_VERSION
    finally:
        conn.close()


def test_partial_failure_rolls_back_in_transaction() -> None:
    """A bad SQL statement in a migration must roll back its transaction.

    The user_version pragma must NOT advance if the migration body
    raises. We seed the DB at the latest good version, then inject a
    bad migration above that, and assert the runner refuses to bump
    the version when the body errors.
    """
    conn = open_connection(":memory:")
    try:
        from clawstu.persistence import migrations as migrations_module

        # First, run the real migrations to establish a clean baseline.
        migrate(conn)
        baseline = current_version(conn)
        assert baseline == LATEST_VERSION

        bad_migration = (
            baseline + 1,
            "CREATE TABLE __bad (id INTEGER); BANANA SQL ERROR;",
        )
        original = migrations_module.MIGRATIONS
        try:
            migrations_module.MIGRATIONS = [*original, bad_migration]
            with pytest.raises(sqlite3.OperationalError):
                migrate(conn)
            # Version should still be baseline, not baseline + 1.
            assert current_version(conn) == baseline
            # And no __bad table should exist.
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='__bad'"
            ).fetchall()
            assert not rows
        finally:
            migrations_module.MIGRATIONS = original
    finally:
        conn.close()


def test_migrations_list_has_at_least_one_entry() -> None:
    assert MIGRATIONS
    versions = [v for v, _sql in MIGRATIONS]
    # Strictly increasing.
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
