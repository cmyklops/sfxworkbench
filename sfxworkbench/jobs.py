"""Cross-feature job tracking for long-running local operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sfxworkbench.db import DEFAULT_DB_PATH, get_connection


@dataclass(frozen=True)
class JobSummary:
    id: int
    action: str
    status: str
    started_at: str
    finished_at: str
    progress: str
    output_artifact_id: int | None = None
    error: str | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_job_summary(row) -> JobSummary:
    return JobSummary(
        id=int(row["id"]),
        action=str(row["action"] or ""),
        status=str(row["status"] or ""),
        started_at=str(row["started_at"] or ""),
        finished_at=str(row["finished_at"] or ""),
        progress=str(row["progress"] or ""),
        output_artifact_id=int(row["output_artifact_id"]) if row["output_artifact_id"] is not None else None,
        error=str(row["error"]) if row["error"] is not None else None,
    )


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


def interrupt_running_jobs(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    error: str = "Previous TUI session ended before this action reported completion.",
) -> list[JobSummary]:
    """Mark persisted running jobs as interrupted during TUI startup.

    TUI workers are in-process. If the terminal closes, those workers cannot be
    resumed, but their durable plans/logs and action history can be rediscovered.
    This prevents stale "running" rows from looking active on the next launch.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = 'running'
            ORDER BY started_at DESC, id DESC
            """
        ).fetchall()
        if not rows:
            return []
        finished_at = _utc_now()
        conn.executemany(
            """
            UPDATE jobs
            SET status = 'interrupted', finished_at = ?, error = ?
            WHERE id = ?
            """,
            [(finished_at, error, int(row["id"])) for row in rows],
        )
        conn.commit()
        return [
            JobSummary(
                id=int(row["id"]),
                action=str(row["action"] or ""),
                status="interrupted",
                started_at=str(row["started_at"] or ""),
                finished_at=finished_at,
                progress=str(row["progress"] or ""),
                output_artifact_id=int(row["output_artifact_id"]) if row["output_artifact_id"] is not None else None,
                error=error,
            )
            for row in rows
        ]
    finally:
        conn.close()


def latest_job(db_path: Path = DEFAULT_DB_PATH) -> JobSummary | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    return _row_to_job_summary(row) if row is not None else None
