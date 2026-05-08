"""SQLite connection management and schema for wavwarden."""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".wavwarden" / "index.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    stem TEXT,
    extension TEXT,
    size_bytes INTEGER,
    mtime REAL,
    md5 TEXT,
    sample_rate INTEGER,
    bit_depth INTEGER,
    channels INTEGER,
    duration_s REAL,
    subtype TEXT,
    has_bext INTEGER DEFAULT 0,
    has_ixml INTEGER DEFAULT 0,
    is_ucs INTEGER DEFAULT 0,
    scan_error TEXT,
    scanned_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename,
    stem,
    content='files',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, filename, stem) VALUES (new.id, new.filename, new.stem);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE OF filename, stem ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, stem) VALUES ('delete', old.id, old.filename, old.stem);
    INSERT INTO files_fts(rowid, filename, stem) VALUES (new.id, new.filename, new.stem);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename, stem) VALUES ('delete', old.id, old.filename, old.stem);
END;

CREATE TABLE IF NOT EXISTS fn_issues (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    component TEXT NOT NULL,
    issue TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS scan_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_ext ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_md5 ON files(md5);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size_bytes);
CREATE INDEX IF NOT EXISTS idx_fn_issues_file ON fn_issues(file_id);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Idempotent schema creation — safe to call on an existing DB."""
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create parent dir, apply schema, return connection with row_factory and WAL mode."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_schema(conn)
    return conn
