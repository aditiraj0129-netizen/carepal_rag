"""SQLite persistence (prototype data store). One short-lived connection per unit of work."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY, title TEXT, tier TEXT, content_type TEXT, sha256 TEXT,
    fetched_at TEXT, status TEXT, provenance TEXT, fetch_method TEXT, chunk_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY, url TEXT NOT NULL, page_title TEXT, section_path TEXT,
    content_type TEXT, tier TEXT, flags_json TEXT DEFAULT '[]', text TEXT NOT NULL,
    embed_text TEXT NOT NULL, bm25_text TEXT NOT NULL, token_count INTEGER,
    prev_chunk_id TEXT, next_chunk_id TEXT, conflict_group TEXT,
    provenance TEXT, content_sha256 TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_url ON chunks(url);
CREATE TABLE IF NOT EXISTS index_state (
    id INTEGER PRIMARY KEY CHECK (id = 1), embedding_model TEXT, embedding_dim INTEGER,
    chroma_collection TEXT, bm25_file TEXT, chunk_count INTEGER, bm25_hash TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS embedding_cache (
    chunk_id TEXT, model_id TEXT, dim INTEGER, vector BLOB, PRIMARY KEY (chunk_id, model_id)
);
CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, source TEXT,
    status TEXT, report_json TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, session_hash TEXT, language TEXT, started_at TEXT,
    after_hours INTEGER DEFAULT 0, turn_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, text_redacted TEXT, route TEXT,
    outcome TEXT, gap_reason TEXT, language TEXT, generator TEXT, retrieval_ms INTEGER,
    generation_ms INTEGER, total_ms INTEGER, trace_id TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE TABLE IF NOT EXISTS retrieval_hits (
    message_id TEXT, chunk_id TEXT, retriever TEXT, rank INTEGER, score REAL,
    fused_rank INTEGER, rrf_score REAL, used_in_context INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hits_msg ON retrieval_hits(message_id);
CREATE TABLE IF NOT EXISTS message_citations (
    message_id TEXT, chunk_id TEXT, position INTEGER
);
CREATE TABLE IF NOT EXISTS unanswered (
    id TEXT PRIMARY KEY, message_id TEXT, question_redacted TEXT, english_query TEXT, language TEXT,
    reason TEXT, top_dense REAL, term_coverage REAL, status TEXT DEFAULT 'new', created_at TEXT
);
CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY, conversation_id TEXT, name TEXT, phone TEXT, consent INTEGER,
    language TEXT, reason TEXT, priority TEXT, question_redacted TEXT, status TEXT,
    delivery TEXT, created_at TEXT, delete_after TEXT
);
CREATE INDEX IF NOT EXISTS idx_handoffs_phone ON handoffs(phone, created_at);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY, message_id TEXT, value INTEGER, comment_redacted TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS pipeline_events (
    id TEXT PRIMARY KEY, message_id TEXT, level TEXT, stage TEXT, error_type TEXT,
    message_redacted TEXT, degraded INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY, config_json TEXT, split TEXT, created_at TEXT, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS eval_results (
    run_id TEXT, item_id TEXT, metrics_json TEXT, outcome TEXT, notes TEXT
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(path: Path | str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def session(path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error, always close."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
