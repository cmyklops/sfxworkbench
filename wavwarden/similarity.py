"""Deterministic audio descriptor crawler for future similarity workflows."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH, get_connection
from wavwarden.models import SimilarityCrawlReport, SimilarityCrawlSummary, SimilarityDescriptor
from wavwarden.utils import json_dumps

console = Console()

DEFAULT_SIMILARITY_CACHE = Path.home() / ".wavwarden" / "similarity"
DETERMINISTIC_BACKEND = "deterministic_v1"
_COMMIT_BATCH = 250


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _duration_bucket(duration_s: float | None) -> str | None:
    if duration_s is None:
        return None
    if duration_s < 1:
        return "subsecond"
    if duration_s < 10:
        return "short"
    if duration_s < 60:
        return "medium"
    if duration_s < 300:
        return "long"
    return "very_long"


def _existing_descriptor_is_current(row, descriptor_row, *, max_duration_s: float | None) -> bool:
    if descriptor_row is None:
        return False
    if descriptor_row["error"] is not None:
        return False
    return (
        descriptor_row["size_bytes"] == row["size_bytes"]
        and descriptor_row["mtime"] == row["mtime"]
        and descriptor_row["md5"] == row["md5"]
        and descriptor_row["max_duration_s"] == max_duration_s
    )


def _compute_audio_descriptor(path: Path, *, max_duration_s: float | None) -> dict:
    try:
        import numpy as np
        import soundfile as sf
    except Exception as e:
        return {"error": f"audio descriptor dependencies unavailable: {e}"}

    try:
        with sf.SoundFile(str(path)) as sound_file:
            sample_rate = sound_file.samplerate
            total_frames = len(sound_file)
            frames = -1
            if max_duration_s is not None and max_duration_s > 0:
                frames = min(total_frames, max(1, int(max_duration_s * sample_rate)))
            audio = sound_file.read(frames=frames, dtype="float32", always_2d=True)
    except Exception as e:
        return {"error": str(e)}

    if audio.size == 0:
        return {
            "analyzed_duration_s": 0.0,
            "peak": 0.0,
            "rms": 0.0,
            "crest_factor": None,
            "silence_ratio": 1.0,
            "clipping_count": 0,
            "zero_crossing_rate": 0.0,
            "transient_density": 0.0,
            "error": None,
        }

    analyzed_duration_s = float(audio.shape[0] / sample_rate) if sample_rate else None
    abs_audio = np.abs(audio)
    peak = float(abs_audio.max())
    rms = float(math.sqrt(float(np.mean(np.square(audio)))))
    crest_factor = float(peak / rms) if rms > 0 else None
    silence_ratio = float(np.mean(abs_audio <= 0.0001))
    clipping_count = int(np.count_nonzero(abs_audio >= 0.999))

    mono = audio.mean(axis=1)
    if mono.size > 1 and analyzed_duration_s and analyzed_duration_s > 0:
        signs = np.signbit(mono)
        zero_crossings = int(np.count_nonzero(signs[1:] != signs[:-1]))
        zero_crossing_rate = float(zero_crossings / analyzed_duration_s)
    else:
        zero_crossing_rate = 0.0

    transient_density = 0.0
    if mono.size >= 1024 and analyzed_duration_s and analyzed_duration_s > 0:
        frame_size = 1024
        frame_count = mono.size // frame_size
        frames_view = mono[: frame_count * frame_size].reshape(frame_count, frame_size)
        frame_rms = np.sqrt(np.mean(np.square(frames_view), axis=1))
        if frame_rms.size > 1:
            deltas = np.diff(frame_rms)
            threshold = max(0.01, float(np.mean(frame_rms)) * 0.5)
            transient_density = float(np.count_nonzero(deltas > threshold) / analyzed_duration_s)

    return {
        "analyzed_duration_s": analyzed_duration_s,
        "peak": peak,
        "rms": rms,
        "crest_factor": crest_factor,
        "silence_ratio": silence_ratio,
        "clipping_count": clipping_count,
        "zero_crossing_rate": zero_crossing_rate,
        "transient_density": transient_density,
        "error": None,
    }


def _descriptor_from_row(
    row, *, backend: str, generated_at: str, max_duration_s: float | None, metrics: dict
) -> SimilarityDescriptor:
    return SimilarityDescriptor(
        file_id=row["id"],
        path=row["path"],
        backend=backend,
        size_bytes=row["size_bytes"],
        mtime=row["mtime"],
        md5=row["md5"],
        max_duration_s=max_duration_s,
        duration_bucket=_duration_bucket(row["duration_s"]),
        generated_at=generated_at,
        **metrics,
    )


def _write_descriptor(conn, descriptor: SimilarityDescriptor) -> None:
    conn.execute(
        """
        INSERT INTO audio_descriptors (
            file_id, backend, path, size_bytes, mtime, md5, max_duration_s, analyzed_duration_s,
            peak, rms, crest_factor, silence_ratio, clipping_count,
            zero_crossing_rate, transient_density, duration_bucket, generated_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id, backend) DO UPDATE SET
            path=excluded.path,
            size_bytes=excluded.size_bytes,
            mtime=excluded.mtime,
            md5=excluded.md5,
            max_duration_s=excluded.max_duration_s,
            analyzed_duration_s=excluded.analyzed_duration_s,
            peak=excluded.peak,
            rms=excluded.rms,
            crest_factor=excluded.crest_factor,
            silence_ratio=excluded.silence_ratio,
            clipping_count=excluded.clipping_count,
            zero_crossing_rate=excluded.zero_crossing_rate,
            transient_density=excluded.transient_density,
            duration_bucket=excluded.duration_bucket,
            generated_at=excluded.generated_at,
            error=excluded.error
        """,
        (
            descriptor.file_id,
            descriptor.backend,
            descriptor.path,
            descriptor.size_bytes,
            descriptor.mtime,
            descriptor.md5,
            descriptor.max_duration_s,
            descriptor.analyzed_duration_s,
            descriptor.peak,
            descriptor.rms,
            descriptor.crest_factor,
            descriptor.silence_ratio,
            descriptor.clipping_count,
            descriptor.zero_crossing_rate,
            descriptor.transient_density,
            descriptor.duration_bucket,
            descriptor.generated_at,
            descriptor.error,
        ),
    )


def crawl_similarity_descriptors(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    cache_path: Path | None = DEFAULT_SIMILARITY_CACHE,
    max_duration_s: float | None = 30.0,
    force: bool = False,
    limit: int = 50,
    quiet: bool = False,
) -> SimilarityCrawlReport:
    """Analyze indexed files under root and cache deterministic descriptors."""
    root = root.resolve()
    if not root.exists():
        raise ValueError(f"path not found: {root}")
    if cache_path is not None:
        cache_path = cache_path.expanduser().resolve()
        cache_path.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path)
    started_at = _utc_now()
    run_row = conn.execute(
        """
        INSERT INTO analysis_runs (
            backend, root, db_path, cache_path, max_duration_s, started_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            DETERMINISTIC_BACKEND,
            str(root),
            str(db_path),
            str(cache_path) if cache_path else None,
            max_duration_s,
            started_at,
            "running",
        ),
    ).fetchone()
    run_id = int(run_row["id"])
    conn.commit()

    rows = conn.execute(
        """
        SELECT id, path, filename, size_bytes, mtime, md5, sample_rate, bit_depth,
               channels, duration_s
        FROM files
        WHERE scan_error IS NULL
        ORDER BY path
        """
    ).fetchall()
    rows = [row for row in rows if Path(row["path"]) == root or _is_relative_to(Path(row["path"]), root)]

    summary = SimilarityCrawlSummary(total_files=len(rows))
    descriptors: list[SimilarityDescriptor] = []
    pending = 0

    for row in rows:
        existing = conn.execute(
            """
            SELECT size_bytes, mtime, md5, max_duration_s, error
            FROM audio_descriptors
            WHERE file_id = ? AND backend = ?
            """,
            (row["id"], DETERMINISTIC_BACKEND),
        ).fetchone()
        if not force and _existing_descriptor_is_current(row, existing, max_duration_s=max_duration_s):
            summary.skipped += 1
            continue

        path = Path(row["path"])
        generated_at = _utc_now()
        if not path.exists():
            metrics = {"error": "file not found"}
        else:
            metrics = _compute_audio_descriptor(path, max_duration_s=max_duration_s)

        descriptor = _descriptor_from_row(
            row,
            backend=DETERMINISTIC_BACKEND,
            generated_at=generated_at,
            max_duration_s=max_duration_s,
            metrics=metrics,
        )
        _write_descriptor(conn, descriptor)
        summary.analyzed += 1
        if descriptor.error is not None:
            summary.errors += 1
        if limit <= 0 or len(descriptors) < limit:
            descriptors.append(descriptor)
        pending += 1
        if pending >= _COMMIT_BATCH:
            conn.commit()
            pending = 0

    finished_at = _utc_now()
    conn.execute(
        """
        UPDATE analysis_runs
        SET finished_at = ?, status = ?, total_files = ?, analyzed = ?, skipped = ?, errors = ?
        WHERE id = ?
        """,
        (finished_at, "completed", summary.total_files, summary.analyzed, summary.skipped, summary.errors, run_id),
    )
    conn.commit()
    conn.close()

    report = SimilarityCrawlReport(
        generated_at=finished_at,
        tool_version=__version__,
        run_id=run_id,
        backend=DETERMINISTIC_BACKEND,
        root=str(root),
        db_path=str(db_path),
        cache_path=str(cache_path) if cache_path else None,
        max_duration_s=max_duration_s,
        force=force,
        summary=summary,
        descriptors=descriptors,
    )
    if cache_path is not None:
        (cache_path / f"similarity_crawl_{run_id}.json").write_text(json_dumps(report), encoding="utf-8")
    if not quiet:
        show_similarity_crawl_report(report)
    return report


def show_similarity_crawl_report(report: SimilarityCrawlReport) -> None:
    table = Table(title="Similarity descriptor crawl", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Backend", report.backend)
    table.add_row("Total indexed files", f"{report.summary.total_files:,}")
    table.add_row("Analyzed", f"{report.summary.analyzed:,}")
    table.add_row("Skipped", f"{report.summary.skipped:,}")
    table.add_row("Errors", f"{report.summary.errors:,}")
    table.add_row("Cache", report.cache_path or "SQLite only")
    console.print(table)
