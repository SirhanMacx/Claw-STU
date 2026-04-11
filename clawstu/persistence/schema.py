"""Raw SQL schema definitions (spec §4.6.2).

All `TEXT` timestamps are ISO-8601 UTC. WAL mode and foreign keys are
enabled by `clawstu.persistence.connection.open_connection`; FTS5 is
probed at open time via `FTS5_PROBE`.

No runtime logic lives in this module — it is a pure collection of
string constants. `connection.py` and `migrations.py` consume them.
"""

from __future__ import annotations

# Each element is a single DDL statement. sqlite3 does not allow a
# cursor.execute() with multiple statements in one call, so we split
# the schema into individually-executable strings and let the callers
# apply them in a transaction.
CREATE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS learners (
        learner_id TEXT PRIMARY KEY,
        age_bracket TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_active_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        learner_id TEXT NOT NULL REFERENCES learners(learner_id),
        domain TEXT NOT NULL,
        topic TEXT,
        phase TEXT NOT NULL,
        pathway_json TEXT,
        started_at TEXT NOT NULL,
        closed_at TEXT,
        crisis_paused INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learner_id TEXT NOT NULL,
        session_id TEXT,
        kind TEXT NOT NULL,
        domain TEXT NOT NULL,
        modality TEXT,
        tier TEXT,
        correct INTEGER,
        latency_seconds REAL,
        concept TEXT,
        notes TEXT,
        timestamp TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zpd_estimates (
        learner_id TEXT NOT NULL,
        domain TEXT NOT NULL,
        tier TEXT NOT NULL,
        confidence REAL NOT NULL,
        samples INTEGER NOT NULL,
        last_updated TEXT NOT NULL,
        PRIMARY KEY (learner_id, domain)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS modality_outcomes (
        learner_id TEXT NOT NULL,
        modality TEXT NOT NULL,
        attempts INTEGER NOT NULL,
        successes INTEGER NOT NULL,
        total_latency_seconds REAL NOT NULL,
        PRIMARY KEY (learner_id, modality)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS next_session_artifacts (
        learner_id TEXT PRIMARY KEY,
        pathway_json TEXT NOT NULL,
        first_block_json TEXT NOT NULL,
        first_check_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        consumed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_graph_triples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        source_session TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kg_subject ON knowledge_graph_triples(subject)",
    "CREATE INDEX IF NOT EXISTS idx_kg_object ON knowledge_graph_triples(object)",
    """
    CREATE TABLE IF NOT EXISTS misconception_tally (
        learner_id TEXT NOT NULL,
        concept TEXT NOT NULL,
        count INTEGER NOT NULL,
        last_seen_at TEXT NOT NULL,
        PRIMARY KEY (learner_id, concept)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduler_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT NOT NULL,
        learner_id_hash TEXT,
        outcome TEXT NOT NULL,
        duration_ms INTEGER NOT NULL,
        token_cost_input INTEGER NOT NULL DEFAULT 0,
        token_cost_output INTEGER NOT NULL DEFAULT 0,
        run_at TEXT NOT NULL,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS page_embeddings (
        page_key TEXT PRIMARY KEY,
        vector BLOB NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE VIRTUAL TABLE IF NOT EXISTS page_text_index USING fts5(page_key, text)",
)


FTS5_PROBE = "SELECT sqlite_compileoption_used('ENABLE_FTS5')"
