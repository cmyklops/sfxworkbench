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
    has_riff_info INTEGER DEFAULT 0,
    has_adm INTEGER DEFAULT 0,
    has_cue_markers INTEGER DEFAULT 0,
    has_sampler INTEGER DEFAULT 0,
    metadata_sources TEXT,
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

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    backend TEXT NOT NULL,
    root TEXT NOT NULL,
    db_path TEXT NOT NULL,
    cache_path TEXT,
    max_duration_s REAL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    total_files INTEGER DEFAULT 0,
    analyzed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audio_descriptors (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    backend TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER,
    mtime REAL,
    md5 TEXT,
    max_duration_s REAL,
    analyzed_duration_s REAL,
    peak REAL,
    rms REAL,
    crest_factor REAL,
    silence_ratio REAL,
    clipping_count INTEGER DEFAULT 0,
    zero_crossing_rate REAL,
    transient_density REAL,
    spectral_centroid REAL,
    spectral_bandwidth REAL,
    spectral_rolloff REAL,
    spectral_flatness REAL,
    segment_count INTEGER DEFAULT 0,
    segment_method TEXT,
    duration_bucket TEXT,
    generated_at TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (file_id, backend)
);

CREATE TABLE IF NOT EXISTS audio_segments (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    backend TEXT NOT NULL,
    path TEXT NOT NULL,
    max_duration_s REAL,
    segment_index INTEGER NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    duration_s REAL NOT NULL,
    peak REAL,
    rms REAL,
    confidence REAL,
    method TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_ext ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_md5 ON files(md5);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size_bytes);
CREATE INDEX IF NOT EXISTS idx_fn_issues_file ON fn_issues(file_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_backend ON analysis_runs(backend);
CREATE INDEX IF NOT EXISTS idx_audio_descriptors_backend ON audio_descriptors(backend);
CREATE INDEX IF NOT EXISTS idx_audio_descriptors_path ON audio_descriptors(path);
CREATE INDEX IF NOT EXISTS idx_audio_segments_backend ON audio_segments(backend);
CREATE INDEX IF NOT EXISTS idx_audio_segments_file ON audio_segments(file_id);
"""

_FILES_COLUMN_MIGRATIONS = {
    "has_riff_info": "INTEGER DEFAULT 0",
    "has_adm": "INTEGER DEFAULT 0",
    "has_cue_markers": "INTEGER DEFAULT 0",
    "has_sampler": "INTEGER DEFAULT 0",
    "metadata_sources": "TEXT",
}

_AUDIO_DESCRIPTORS_COLUMN_MIGRATIONS = {
    "max_duration_s": "REAL",
    "spectral_centroid": "REAL",
    "spectral_bandwidth": "REAL",
    "spectral_rolloff": "REAL",
    "spectral_flatness": "REAL",
    "segment_count": "INTEGER DEFAULT 0",
    "segment_method": "TEXT",
}


def apply_schema(conn: sqlite3.Connection) -> None:
    """Idempotent schema creation — safe to call on an existing DB."""
    conn.executescript(_SCHEMA_SQL)
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(files)").fetchall()}
    for column, definition in _FILES_COLUMN_MIGRATIONS.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE files ADD COLUMN {column} {definition}")
    existing_descriptor_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(audio_descriptors)").fetchall()
    }
    for column, definition in _AUDIO_DESCRIPTORS_COLUMN_MIGRATIONS.items():
        if column not in existing_descriptor_columns:
            conn.execute(f"ALTER TABLE audio_descriptors ADD COLUMN {column} {definition}")
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
