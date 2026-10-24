"""SQLite metadata store + FTS5 full-text index.

Design notes
- One short-lived connection per unit of work (thread safe; WAL allows concurrent readers during a scan).
- Chunks never cross a page boundary, so every search hit maps to exactly one PDF page.
- chunks_fts is an external-content FTS5 table kept in sync by triggers.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from .config import get_settings

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL,
    last_scan_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending|indexed|partial|duplicate|missing|error|ocr_needed|skipped
    duplicate_of INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    possible_duplicate_of INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    -- bibliographic metadata; every field carries its provenance (*_src)
    title TEXT, title_src TEXT,
    authors TEXT, authors_src TEXT,
    edition TEXT, edition_src TEXT,
    year INTEGER, year_src TEXT,
    publisher TEXT, publisher_src TEXT,
    isbn TEXT, isbn_src TEXT,
    metadata_verified INTEGER NOT NULL DEFAULT 0, -- 1 only after the user confirms it
    -- extraction statistics
    page_count INTEGER,
    text_pages INTEGER,
    ocr_pages INTEGER,
    empty_pages INTEGER,
    chunk_count INTEGER,
    label_mode TEXT,                              -- embedded|inferred|mixed|none|reflowable
    reflowable INTEGER NOT NULL DEFAULT 0,
    has_toc INTEGER NOT NULL DEFAULT 0,
    quality_score INTEGER,
    quality_notes TEXT,
    error TEXT,
    extractor_version INTEGER,
    added_at TEXT NOT NULL,
    indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_documents_sha ON documents(sha256);
CREATE INDEX IF NOT EXISTS ix_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS ix_documents_folder ON documents(folder_id);

CREATE TABLE IF NOT EXISTS pages (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_index INTEGER NOT NULL,                  -- 0-based physical page in the file
    printed_label TEXT,                           -- page number as printed in the book (if known)
    label_src TEXT,                               -- embedded|inferred|NULL
    chapter TEXT,
    section TEXT,
    char_count INTEGER NOT NULL DEFAULT 0,
    ocr INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (document_id, page_index)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS toc (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    level INTEGER NOT NULL,
    title TEXT NOT NULL,
    start_page INTEGER NOT NULL,                  -- 0-based
    end_page INTEGER,
    PRIMARY KEY (document_id, seq)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_index INTEGER NOT NULL,
    chunk_no INTEGER NOT NULL,
    chapter TEXT,
    section TEXT,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_doc_page ON chunks(document_id, page_index);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, chapter, section,
    content='chunks', content_rowid='id',
    tokenize="porter unicode61 remove_diacritics 2"
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, chapter, section) VALUES (new.id, new.text, new.chapter, new.section);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, chapter, section)
    VALUES ('delete', old.id, old.text, old.chapter, old.section);
END;

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,                          -- queued|running|done|failed|cancelled
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    progress TEXT,                                 -- JSON
    log TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
    # Jobs interrupted by a crash/restart must not stay 'running' forever - but only if no other
    # process (e.g. a scheduled CLI scan) currently holds the scan lock.
    from .services.lock import ScanLock

    lock = ScanLock()
    if lock.acquire():
        try:
            with session() as conn:
                conn.execute(
                    "UPDATE jobs SET status='failed', finished_at=?, log = log || ? WHERE status IN ('queued','running')",
                    (now_iso(), "\n[interrupted: process stopped before the job finished]"),
                )
        finally:
            lock.release()


def audit(conn: sqlite3.Connection, action: str, detail: str = "") -> None:
    conn.execute("INSERT INTO audit_log(ts, action, detail) VALUES (?,?,?)", (now_iso(), action, detail))
