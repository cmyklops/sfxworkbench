"""Cross-feature job tracking for long-running local operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sfxworkbench.db import DEFAULT_DB_PATH, get_connection


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _progress_payload(
    *,
    phase: str = "",
    completed: int = 0,
    total: int | None = None,
    message: str = "",
) -> str:
    percent: float | None = None
    if total and total > 0:
        percent = max(0.0, min(100.0, (completed / total) * 100.0))
    return json.dumps(
        {
            "phase": phase,
            "completed": completed,
            "total": total,
            "message": message,
            "percent": percent,
        },
        sort_keys=True,
    )


def start_job(
    db_path: Path = DEFAULT_DB_PATH,
    action: str = "",
    *,
    status: str = "running",
    message: str = "",
) -> int:
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO jobs (action, status, started_at, progress)
            VALUES (?, ?, ?, ?)
            """,
            (
                action,
                status,
                _utc_now(),
                _progress_payload(phase="starting", completed=0, total=None, message=message),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def update_job_progress(
    db_path: Path = DEFAULT_DB_PATH,
    job_id: int | None = None,
    *,
    phase: str = "",
    completed: int = 0,
    total: int | None = None,
    message: str = "",
) -> None:
    if job_id is None:
        return
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE jobs SET progress = ? WHERE id = ? AND status = 'running'",
            (_progress_payload(phase=phase, completed=completed, total=total, message=message), int(job_id)),
        )
        conn.commit()
    finally:
        conn.close()


def finish_job(
    db_path: Path = DEFAULT_DB_PATH,
    job_id: int | None = None,
    *,
    status: str,
    output_artifact_id: int | None = None,
    error: str | None = None,
) -> None:
    if job_id is None:
        return
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, finished_at = ?, output_artifact_id = ?, error = ?
            WHERE id = ?
            """,
            (status, _utc_now(), output_artifact_id, error, int(job_id)),
        )
        conn.commit()
    finally:
        conn.close()
