"""SQLite connection management and schema for sfxworkbench."""

import contextlib
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".sfxworkbench" / "index.db"
_SQL_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")
_LIKE_ESCAPE = "\\"
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")

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
    backend_version TEXT,
    parameters_json TEXT,
    parameters_hash TEXT,
    segment_method TEXT,
    root TEXT NOT NULL,
    db_path TEXT NOT NULL,
    cache_path TEXT,
    max_duration_s REAL,
    max_files INTEGER,
    force INTEGER DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    status_reason TEXT,
    total_files INTEGER DEFAULT 0,
    analyzed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audio_descriptors (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    backend TEXT NOT NULL,
    backend_version TEXT,
    parameters_hash TEXT,
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
    backend_version TEXT,
    parameters_hash TEXT,
    path TEXT NOT NULL,
    max_duration_s REAL,
    segment_index INTEGER NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    duration_s REAL NOT NULL,
    peak REAL,
    rms REAL,
    crest_factor REAL,
    silence_ratio REAL,
    zero_crossing_rate REAL,
    spectral_centroid REAL,
    spectral_bandwidth REAL,
    spectral_rolloff REAL,
    spectral_flatness REAL,
    confidence REAL,
    method TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_embeddings (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    segment_id INTEGER REFERENCES audio_segments(id) ON DELETE CASCADE,
    backend TEXT NOT NULL,
    model_version TEXT NOT NULL,
    parameters_hash TEXT,
    dimensions INTEGER NOT NULL,
    vector_ref TEXT,
    generated_at TEXT NOT NULL,
    error TEXT,
    UNIQUE (file_id, segment_id, backend, model_version, parameters_hash)
);

CREATE TABLE IF NOT EXISTS similarity_feedback (
    id INTEGER PRIMARY KEY,
    backend TEXT NOT NULL,
    scope TEXT NOT NULL,
    left_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    right_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    left_segment_index INTEGER NOT NULL DEFAULT -1,
    right_segment_index INTEGER NOT NULL DEFAULT -1,
    state TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(scope IN ('file', 'segment')),
    CHECK(state IN ('favorite', 'hidden', 'ignored', 'accepted', 'rejected')),
    UNIQUE (
        backend, scope, left_file_id, right_file_id,
        left_segment_index, right_segment_index
    )
);

CREATE TABLE IF NOT EXISTS accepted_tags (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    method TEXT,
    confidence REAL,
    evidence TEXT,
    plan_entry_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (file_id, field, value)
);

CREATE TABLE IF NOT EXISTS metadata_fields (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (file_id, namespace, key, value, source)
);

CREATE TABLE IF NOT EXISTS tag_apply_log (
    id INTEGER PRIMARY KEY,
    plan_path TEXT,
    db_path TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 1,
    generated_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    feature TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL,
    mtime REAL NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    entry_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    progress TEXT,
    output_artifact_id INTEGER REFERENCES artifacts(id) ON DELETE SET NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS artifact_rows (
    id INTEGER PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    row_type TEXT NOT NULL,
    action TEXT,
    source TEXT,
    target TEXT,
    status TEXT,
    detail TEXT,
    search_text TEXT,
    UNIQUE (artifact_id, row_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS artifact_rows_fts USING fts5(
    search_text,
    content='artifact_rows',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS artifact_rows_ai AFTER INSERT ON artifact_rows BEGIN
    INSERT INTO artifact_rows_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;

CREATE TRIGGER IF NOT EXISTS artifact_rows_au AFTER UPDATE OF search_text ON artifact_rows BEGIN
    INSERT INTO artifact_rows_fts(artifact_rows_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
    INSERT INTO artifact_rows_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;

CREATE TRIGGER IF NOT EXISTS artifact_rows_ad AFTER DELETE ON artifact_rows BEGIN
    INSERT INTO artifact_rows_fts(artifact_rows_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
END;

CREATE INDEX IF NOT EXISTS idx_files_ext ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_md5 ON files(md5);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size_bytes);
CREATE INDEX IF NOT EXISTS idx_fn_issues_file ON fn_issues(file_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_backend ON analysis_runs(backend);
CREATE INDEX IF NOT EXISTS idx_audio_descriptors_backend ON audio_descriptors(backend);
CREATE INDEX IF NOT EXISTS idx_audio_descriptors_path ON audio_descriptors(path);
CREATE INDEX IF NOT EXISTS idx_audio_segments_backend ON audio_segments(backend);
CREATE INDEX IF NOT EXISTS idx_audio_segments_file ON audio_segments(file_id);
CREATE INDEX IF NOT EXISTS idx_audio_embeddings_backend ON audio_embeddings(backend);
CREATE INDEX IF NOT EXISTS idx_audio_embeddings_file ON audio_embeddings(file_id);
CREATE INDEX IF NOT EXISTS idx_similarity_feedback_state ON similarity_feedback(state);
CREATE INDEX IF NOT EXISTS idx_similarity_feedback_left ON similarity_feedback(left_file_id);
CREATE INDEX IF NOT EXISTS idx_similarity_feedback_right ON similarity_feedback(right_file_id);
CREATE INDEX IF NOT EXISTS idx_accepted_tags_file ON accepted_tags(file_id);
CREATE INDEX IF NOT EXISTS idx_accepted_tags_field ON accepted_tags(field);
CREATE INDEX IF NOT EXISTS idx_metadata_fields_file ON metadata_fields(file_id);
CREATE INDEX IF NOT EXISTS idx_metadata_fields_key ON metadata_fields(namespace, key);
CREATE INDEX IF NOT EXISTS idx_metadata_fields_value ON metadata_fields(value);
CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_mtime ON artifacts(mtime);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(kind);
CREATE INDEX IF NOT EXISTS idx_artifacts_feature ON artifacts(feature);
CREATE INDEX IF NOT EXISTS idx_artifacts_category ON artifacts(category);
CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_action ON jobs(action);
CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at);
CREATE INDEX IF NOT EXISTS idx_artifact_rows_artifact ON artifact_rows(artifact_id);
CREATE INDEX IF NOT EXISTS idx_artifact_rows_type ON artifact_rows(row_type);
"""

_FILES_COLUMN_MIGRATIONS = {
    "has_riff_info": "INTEGER DEFAULT 0",
    "has_adm": "INTEGER DEFAULT 0",
    "has_cue_markers": "INTEGER DEFAULT 0",
    "has_sampler": "INTEGER DEFAULT 0",
    "metadata_sources": "TEXT",
}

_AUDIO_DESCRIPTORS_COLUMN_MIGRATIONS = {
    "backend_version": "TEXT",
    "parameters_hash": "TEXT",
    "max_duration_s": "REAL",
    "spectral_centroid": "REAL",
    "spectral_bandwidth": "REAL",
    "spectral_rolloff": "REAL",
    "spectral_flatness": "REAL",
    "segment_count": "INTEGER DEFAULT 0",
    "segment_method": "TEXT",
}

_AUDIO_SEGMENTS_COLUMN_MIGRATIONS = {
    "backend_version": "TEXT",
    "parameters_hash": "TEXT",
    "crest_factor": "REAL",
    "silence_ratio": "REAL",
    "zero_crossing_rate": "REAL",
    "spectral_centroid": "REAL",
    "spectral_bandwidth": "REAL",
    "spectral_rolloff": "REAL",
    "spectral_flatness": "REAL",
}

_ANALYSIS_RUNS_COLUMN_MIGRATIONS = {
    "backend_version": "TEXT",
    "parameters_json": "TEXT",
    "parameters_hash": "TEXT",
    "segment_method": "TEXT",
    "max_files": "INTEGER",
    "force": "INTEGER DEFAULT 0",
    "status_reason": "TEXT",
}


def escape_like_pattern(value: str) -> str:
    """Escape text used inside a SQLite LIKE pattern."""
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE + _LIKE_ESCAPE)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )


def _normalized_path_text(path: Path | str | None) -> str:
    if path is None:
        return ""
    raw = str(path)
    if raw == "":
        return ""

    text = raw.replace("\\", "/")
    is_unc = text.startswith("//")
    is_drive = bool(_WINDOWS_DRIVE_RE.match(text))

    if is_unc:
        remainder = re.sub(r"/+", "/", text[2:])
        text = f"//{remainder}"
    else:
        text = re.sub(r"/+", "/", text)

    if text != "/":
        text = text.rstrip("/")
    if is_drive and text.endswith(":"):
        text = f"{text}/"
    if is_drive and text.endswith(":/"):
        text = text[:-1]

    return text or "/"


def canonical_path_key(path: Path | str | None) -> str:
    """Return a lexical path key for cross-platform scope comparisons.

    Stored DB paths are intentionally left untouched. This helper normalizes
    only for comparison: separators become ``/``, repeated separators collapse,
    trailing separators are removed except for roots, and Windows-like paths
    (drive-letter or UNC) compare case-insensitively.
    """
    text = _normalized_path_text(path)
    is_unc = text.startswith("//")
    is_drive = bool(_WINDOWS_DRIVE_RE.match(text))
    if is_drive or is_unc:
        text = text.casefold()
    return text


def is_windows_path_like(path: Path | str | None) -> bool:
    """Return whether *path* has Windows drive or UNC syntax lexically."""
    if path is None:
        return False
    text = str(path).replace("\\", "/")
    return bool(_WINDOWS_DRIVE_RE.match(text)) or text.startswith("//")


def resolve_scope_root(root: Path | str) -> Path:
    """Resolve POSIX roots while preserving Windows-style lexical test roots."""
    path = Path(root).expanduser()
    if is_windows_path_like(root):
        return path
    return path.resolve()


def _sql_canonical_path_key(path: str | None) -> str:
    return canonical_path_key(path)


def register_path_functions(conn: sqlite3.Connection) -> None:
    """Register SQLite scalar functions used by path-scope queries."""
    conn.create_function("sfx_path_key", 1, _sql_canonical_path_key, deterministic=True)


def path_scope_filter(column: str = "path") -> str:
    """Return SQL for matching one path or descendants without wildcard leaks."""
    if not _SQL_COLUMN_RE.match(column):
        raise ValueError(f"unsupported SQL path column: {column}")
    expr = f"sfx_path_key({column})"
    return f"({expr} = ? OR {expr} LIKE ? ESCAPE '{_LIKE_ESCAPE}')"


def path_scope_params(root: Path | str) -> tuple[str, str]:
    """Return parameters for :func:`path_scope_filter`."""
    root_key = canonical_path_key(root)
    return root_key, escape_like_pattern(root_key) + "/%"


def is_scoped_path(candidate: Path | str, root: Path | str) -> bool:
    """Return whether *candidate* is *root* or a lexical descendant of it."""
    candidate_key = canonical_path_key(candidate)
    root_key = canonical_path_key(root)
    return candidate_key == root_key or candidate_key.startswith(root_key.rstrip("/") + "/")


def scoped_relative_path(candidate: Path | str, root: Path | str) -> str | None:
    """Return a slash-separated relative path if *candidate* is within *root*."""
    candidate_key = canonical_path_key(candidate)
    root_key = canonical_path_key(root)
    if candidate_key == root_key:
        return ""
    prefix = root_key.rstrip("/") + "/"
    if candidate_key.startswith(prefix):
        candidate_text = _normalized_path_text(candidate)
        root_text = _normalized_path_text(root)
        return candidate_text[len(root_text.rstrip("/") + "/") :]
    return None


def scoped_relative_parts(candidate: Path | str, root: Path | str) -> tuple[str, ...] | None:
    """Return lexical relative path parts if *candidate* is within *root*."""
    relative = scoped_relative_path(candidate, root)
    if relative is None:
        return None
    if not relative:
        return ()
    return tuple(part for part in relative.split("/") if part)


def path_sort_key(path: Path | str) -> str:
    """Return a stable lexical key for sorting paths across separator styles."""
    return canonical_path_key(path)


def windows_collision_path_key(path: Path | str) -> str:
    """Return a Windows-style case-insensitive path key for target collision checks."""
    key = canonical_path_key(path)
    parts = []
    for part in key.split("/"):
        if part in {"", "."}:
            parts.append(part)
        else:
            parts.append(part.rstrip(" .").casefold())
    return "/".join(parts)


def windows_collision_name_key(name: str) -> str:
    """Return a Windows-style comparison key for one path component."""
    return name.rstrip(" .").casefold()


def apply_schema(conn: sqlite3.Connection) -> None:
    """Idempotent schema creation — safe to call on an existing DB."""
    conn.executescript(_SCHEMA_SQL)
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(files)").fetchall()}
    for column, definition in _FILES_COLUMN_MIGRATIONS.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE files ADD COLUMN {column} {definition}")
    existing_run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis_runs)").fetchall()}
    for column, definition in _ANALYSIS_RUNS_COLUMN_MIGRATIONS.items():
        if column not in existing_run_columns:
            conn.execute(f"ALTER TABLE analysis_runs ADD COLUMN {column} {definition}")
    existing_descriptor_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(audio_descriptors)").fetchall()
    }
    for column, definition in _AUDIO_DESCRIPTORS_COLUMN_MIGRATIONS.items():
        if column not in existing_descriptor_columns:
            conn.execute(f"ALTER TABLE audio_descriptors ADD COLUMN {column} {definition}")
    existing_segment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(audio_segments)").fetchall()}
    for column, definition in _AUDIO_SEGMENTS_COLUMN_MIGRATIONS.items():
        if column not in existing_segment_columns:
            conn.execute(f"ALTER TABLE audio_segments ADD COLUMN {column} {definition}")
    conn.commit()


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create parent dir, apply schema, return connection with row_factory and WAL mode."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    register_path_functions(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_schema(conn)
    return conn


@contextlib.contextmanager
def connection(db_path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Context-managed wrapper around :func:`get_connection`.

    Guarantees the SQLite connection is closed (releasing any WAL lock) when
    the ``with`` block exits, including via exception. Prefer this over the
    bare :func:`get_connection` + manual ``.close()`` pattern.
    """
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
