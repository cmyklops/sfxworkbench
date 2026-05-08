"""sfx search command — FTS5 full-text search over filename and stem."""

from pathlib import Path

from wavwarden.db import get_connection


def search(db_path: Path, query: str, limit: int = 50) -> list[dict]:
    """FTS5 full-text search over filename and stem."""
    conn = get_connection(db_path)

    rows = conn.execute(
        """
        SELECT f.path, f.filename, f.stem, f.extension, f.size_bytes,
               f.sample_rate, f.bit_depth, f.channels, f.duration_s, f.is_ucs
        FROM files_fts fts
        JOIN files f ON f.id = fts.rowid
        WHERE files_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()

    conn.close()
    return [dict(row) for row in rows]
