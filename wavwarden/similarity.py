"""Deterministic audio descriptor crawler for future similarity workflows."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH, get_connection
from wavwarden.models import (
    SimilarityAuditFile,
    SimilarityAuditGroup,
    SimilarityAuditPair,
    SimilarityAuditReport,
    SimilarityAuditSummary,
    SimilarityCrawlReport,
    SimilarityCrawlSummary,
    SimilarityDescriptor,
    SimilaritySearchReport,
    SimilaritySearchResult,
)
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
    if any(
        descriptor_row[column] is None
        for column in ("spectral_centroid", "spectral_bandwidth", "spectral_rolloff", "spectral_flatness")
    ):
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
            "spectral_centroid": 0.0,
            "spectral_bandwidth": 0.0,
            "spectral_rolloff": 0.0,
            "spectral_flatness": 0.0,
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

    spectral = _compute_spectral_features(mono, sample_rate, np)

    return {
        "analyzed_duration_s": analyzed_duration_s,
        "peak": peak,
        "rms": rms,
        "crest_factor": crest_factor,
        "silence_ratio": silence_ratio,
        "clipping_count": clipping_count,
        "zero_crossing_rate": zero_crossing_rate,
        "transient_density": transient_density,
        **spectral,
        "error": None,
    }


def _compute_spectral_features(mono, sample_rate: int, np) -> dict[str, float]:
    if mono.size < 2 or sample_rate <= 0:
        return {
            "spectral_centroid": 0.0,
            "spectral_bandwidth": 0.0,
            "spectral_rolloff": 0.0,
            "spectral_flatness": 0.0,
        }

    frame_size = 2048
    if mono.size < frame_size:
        frame_size = 2 ** max(8, int(math.floor(math.log2(mono.size))))
    hop_size = max(1, frame_size // 2)
    if mono.size < frame_size:
        padded = np.pad(mono, (0, frame_size - mono.size))
        frames_view = padded.reshape(1, frame_size)
    else:
        frame_count = 1 + ((mono.size - frame_size) // hop_size)
        shape = (frame_count, frame_size)
        strides = (mono.strides[0] * hop_size, mono.strides[0])
        frames_view = np.lib.stride_tricks.as_strided(mono, shape=shape, strides=strides)

    frame_rms = np.sqrt(np.mean(np.square(frames_view), axis=1))
    active_frames = frames_view[frame_rms > 0.000001]
    if active_frames.size == 0:
        return {
            "spectral_centroid": 0.0,
            "spectral_bandwidth": 0.0,
            "spectral_rolloff": 0.0,
            "spectral_flatness": 0.0,
        }

    window = np.hanning(frame_size).astype("float32")
    magnitudes = np.abs(np.fft.rfft(active_frames * window, axis=1))
    magnitudes = np.maximum(magnitudes, 1e-12)
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / sample_rate)
    magnitude_sums = np.sum(magnitudes, axis=1)
    centroid = np.sum(magnitudes * freqs, axis=1) / magnitude_sums
    bandwidth = np.sqrt(np.sum(magnitudes * np.square(freqs - centroid[:, None]), axis=1) / magnitude_sums)

    cumulative = np.cumsum(magnitudes, axis=1)
    rolloff_threshold = magnitude_sums[:, None] * 0.85
    rolloff_indices = np.argmax(cumulative >= rolloff_threshold, axis=1)
    rolloff = freqs[rolloff_indices]

    flatness = np.exp(np.mean(np.log(magnitudes), axis=1)) / np.mean(magnitudes, axis=1)
    return {
        "spectral_centroid": float(np.mean(centroid)),
        "spectral_bandwidth": float(np.mean(bandwidth)),
        "spectral_rolloff": float(np.mean(rolloff)),
        "spectral_flatness": float(np.mean(flatness)),
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


def _descriptor_from_metrics(
    path: Path, *, backend: str, generated_at: str, max_duration_s: float | None, metrics: dict
) -> SimilarityDescriptor:
    stat = path.stat()
    return SimilarityDescriptor(
        file_id=0,
        path=str(path),
        backend=backend,
        size_bytes=stat.st_size,
        mtime=stat.st_mtime,
        md5=None,
        max_duration_s=max_duration_s,
        duration_bucket=_duration_bucket(metrics.get("analyzed_duration_s")),
        generated_at=generated_at,
        **metrics,
    )


def _descriptor_vector(values: dict) -> tuple[float, ...] | None:
    if values.get("error") is not None:
        return None
    raw = {
        "peak": values.get("peak"),
        "rms": values.get("rms"),
        "crest_factor": values.get("crest_factor"),
        "silence_ratio": values.get("silence_ratio"),
        "clipping_count": values.get("clipping_count"),
        "zero_crossing_rate": values.get("zero_crossing_rate"),
        "transient_density": values.get("transient_density"),
        "spectral_centroid": values.get("spectral_centroid"),
        "spectral_bandwidth": values.get("spectral_bandwidth"),
        "spectral_rolloff": values.get("spectral_rolloff"),
        "spectral_flatness": values.get("spectral_flatness"),
        "analyzed_duration_s": values.get("analyzed_duration_s"),
    }
    if raw["peak"] is None or raw["rms"] is None:
        return None
    return (
        float(raw["peak"] or 0.0),
        float(raw["rms"] or 0.0),
        min(float(raw["crest_factor"] or 0.0), 20.0) / 20.0,
        float(raw["silence_ratio"] or 0.0),
        math.log1p(float(raw["clipping_count"] or 0.0)) / 10.0,
        math.log1p(float(raw["zero_crossing_rate"] or 0.0)) / 10.0,
        math.log1p(float(raw["transient_density"] or 0.0)) / 5.0,
        math.log1p(float(raw["spectral_centroid"] or 0.0)) / 10.0,
        math.log1p(float(raw["spectral_bandwidth"] or 0.0)) / 10.0,
        math.log1p(float(raw["spectral_rolloff"] or 0.0)) / 10.0,
        float(raw["spectral_flatness"] or 0.0),
        math.log1p(float(raw["analyzed_duration_s"] or 0.0)) / 10.0,
    )


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _score(distance: float) -> float:
    return 1.0 / (1.0 + distance)


def _write_descriptor(conn, descriptor: SimilarityDescriptor) -> None:
    conn.execute(
        """
        INSERT INTO audio_descriptors (
            file_id, backend, path, size_bytes, mtime, md5, max_duration_s, analyzed_duration_s,
            peak, rms, crest_factor, silence_ratio, clipping_count,
            zero_crossing_rate, transient_density, spectral_centroid, spectral_bandwidth,
            spectral_rolloff, spectral_flatness, duration_bucket, generated_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            spectral_centroid=excluded.spectral_centroid,
            spectral_bandwidth=excluded.spectral_bandwidth,
            spectral_rolloff=excluded.spectral_rolloff,
            spectral_flatness=excluded.spectral_flatness,
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
            descriptor.spectral_centroid,
            descriptor.spectral_bandwidth,
            descriptor.spectral_rolloff,
            descriptor.spectral_flatness,
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
            SELECT size_bytes, mtime, md5, max_duration_s, error, spectral_centroid,
                   spectral_bandwidth, spectral_rolloff, spectral_flatness
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


def _descriptor_rows(conn, *, root: Path | None, max_duration_s: float | None):
    rows = conn.execute(
        """
        SELECT f.id AS file_id, f.path, f.filename, f.md5, f.sample_rate,
               f.bit_depth, f.channels, f.duration_s, d.analyzed_duration_s,
               d.peak, d.rms, d.crest_factor, d.silence_ratio,
               d.clipping_count, d.zero_crossing_rate, d.transient_density,
               d.spectral_centroid, d.spectral_bandwidth, d.spectral_rolloff,
               d.spectral_flatness,
               d.duration_bucket, d.error
        FROM audio_descriptors d
        JOIN files f ON f.id = d.file_id
        WHERE d.backend = ?
          AND d.error IS NULL
          AND ((? IS NULL AND d.max_duration_s IS NULL) OR d.max_duration_s = ?)
        ORDER BY f.path
        """,
        (DETERMINISTIC_BACKEND, max_duration_s, max_duration_s),
    ).fetchall()
    if root is None:
        return rows
    return [row for row in rows if Path(row["path"]) == root or _is_relative_to(Path(row["path"]), root)]


def search_similarity_descriptors(
    query_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    max_duration_s: float | None = 30.0,
    limit: int = 20,
    quiet: bool = False,
) -> SimilaritySearchReport:
    """Search cached deterministic descriptors using a query audio file."""
    query_path = query_path.expanduser().resolve()
    if not query_path.exists():
        raise ValueError(f"query file not found: {query_path}")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    generated_at = _utc_now()
    query_metrics = _compute_audio_descriptor(query_path, max_duration_s=max_duration_s)
    query_descriptor = _descriptor_from_metrics(
        query_path,
        backend=DETERMINISTIC_BACKEND,
        generated_at=generated_at,
        max_duration_s=max_duration_s,
        metrics=query_metrics,
    )
    query_vector = _descriptor_vector(query_descriptor.model_dump())
    if query_vector is None:
        raise ValueError(f"could not analyze query file: {query_descriptor.error}")

    conn = get_connection(db_path)
    rows = _descriptor_rows(conn, root=None, max_duration_s=max_duration_s)
    conn.close()

    scored: list[SimilaritySearchResult] = []
    for row in rows:
        candidate_values = dict(row)
        candidate_vector = _descriptor_vector(candidate_values)
        if candidate_vector is None:
            continue
        distance = _distance(query_vector, candidate_vector)
        scored.append(
            SimilaritySearchResult(
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                distance=distance,
                score=_score(distance),
                duration_s=row["duration_s"],
                sample_rate=row["sample_rate"],
                bit_depth=row["bit_depth"],
                channels=row["channels"],
                peak=row["peak"],
                rms=row["rms"],
                crest_factor=row["crest_factor"],
                silence_ratio=row["silence_ratio"],
                clipping_count=row["clipping_count"],
                zero_crossing_rate=row["zero_crossing_rate"],
                transient_density=row["transient_density"],
                spectral_centroid=row["spectral_centroid"],
                spectral_bandwidth=row["spectral_bandwidth"],
                spectral_rolloff=row["spectral_rolloff"],
                spectral_flatness=row["spectral_flatness"],
                duration_bucket=row["duration_bucket"],
            )
        )

    scored.sort(key=lambda result: (result.distance, result.path))
    report = SimilaritySearchReport(
        generated_at=generated_at,
        tool_version=__version__,
        backend=DETERMINISTIC_BACKEND,
        query_path=str(query_path),
        db_path=str(db_path),
        max_duration_s=max_duration_s,
        candidates_considered=len(scored),
        limit=limit,
        query_descriptor=query_descriptor,
        results=scored[:limit],
    )
    if not quiet:
        show_similarity_search_report(report)
    return report


def audit_similarity_descriptors(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    threshold: float = 0.92,
    max_duration_s: float | None = 30.0,
    exclude_exact_md5: bool = True,
    limit: int = 200,
    output_path: Path | None = None,
    quiet: bool = False,
) -> SimilarityAuditReport:
    """Report near-duplicate groups from cached deterministic descriptors."""
    root = root.expanduser().resolve()
    if not root.exists():
        raise ValueError(f"path not found: {root}")
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be greater than 0 and less than or equal to 1")
    if limit < 0:
        raise ValueError("limit must be 0 or greater")

    conn = get_connection(db_path)
    rows = _descriptor_rows(conn, root=root, max_duration_s=max_duration_s)
    conn.close()

    vectors: dict[int, tuple[float, ...]] = {}
    by_id = {int(row["file_id"]): row for row in rows}
    for row in rows:
        vector = _descriptor_vector(dict(row))
        if vector is not None:
            vectors[int(row["file_id"])] = vector

    parent: dict[int, int] = {file_id: file_id for file_id in vectors}

    def find(file_id: int) -> int:
        while parent[file_id] != file_id:
            parent[file_id] = parent[parent[file_id]]
            file_id = parent[file_id]
        return file_id

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    pairs: list[SimilarityAuditPair] = []
    exact_md5_pairs_excluded = 0
    file_ids = sorted(vectors)
    for left_index, left_id in enumerate(file_ids):
        left = by_id[left_id]
        for right_id in file_ids[left_index + 1 :]:
            right = by_id[right_id]
            left_md5 = left["md5"]
            right_md5 = right["md5"]
            if exclude_exact_md5 and left_md5 and left_md5 == right_md5:
                exact_md5_pairs_excluded += 1
                continue
            distance = _distance(vectors[left_id], vectors[right_id])
            score = _score(distance)
            if score < threshold:
                continue
            pair = SimilarityAuditPair(
                left_file_id=left_id,
                right_file_id=right_id,
                left_path=left["path"],
                right_path=right["path"],
                distance=distance,
                score=score,
                shared_duration_bucket=left["duration_bucket"] == right["duration_bucket"],
            )
            pairs.append(pair)
            union(left_id, right_id)

    group_pairs: dict[int, list[SimilarityAuditPair]] = {}
    group_file_ids: dict[int, set[int]] = {}
    for pair in pairs:
        root_id = find(pair.left_file_id)
        group_pairs.setdefault(root_id, []).append(pair)
        group_file_ids.setdefault(root_id, set()).update({pair.left_file_id, pair.right_file_id})

    groups: list[SimilarityAuditGroup] = []
    for group_index, root_id in enumerate(sorted(group_pairs), start=1):
        group_pair_list = sorted(group_pairs[root_id], key=lambda pair: (-pair.score, pair.left_path, pair.right_path))
        file_rows = [
            by_id[file_id] for file_id in sorted(group_file_ids[root_id], key=lambda file_id: by_id[file_id]["path"])
        ]
        files = [
            SimilarityAuditFile(
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                md5=row["md5"],
                duration_s=row["duration_s"],
                sample_rate=row["sample_rate"],
                bit_depth=row["bit_depth"],
                channels=row["channels"],
                duration_bucket=row["duration_bucket"],
            )
            for row in file_rows
        ]
        scores = [pair.score for pair in group_pair_list]
        groups.append(
            SimilarityAuditGroup(
                group_id=group_index,
                file_count=len(files),
                pair_count=len(group_pair_list),
                min_score=min(scores),
                max_score=max(scores),
                files=files,
                pairs=group_pair_list,
            )
        )

    groups.sort(key=lambda group: (-group.max_score, -group.pair_count, group.files[0].path if group.files else ""))
    for index, group in enumerate(groups, start=1):
        group.group_id = index
    reported_groups = groups if limit == 0 else groups[:limit]
    report = SimilarityAuditReport(
        generated_at=_utc_now(),
        tool_version=__version__,
        backend=DETERMINISTIC_BACKEND,
        root=str(root),
        db_path=str(db_path),
        threshold=threshold,
        max_duration_s=max_duration_s,
        exclude_exact_md5=exclude_exact_md5,
        limit=limit,
        summary=SimilarityAuditSummary(
            descriptors_considered=len(vectors),
            candidate_pairs=len(pairs),
            exact_md5_pairs_excluded=exact_md5_pairs_excluded,
            candidate_groups=len(groups),
            reported_groups=len(reported_groups),
        ),
        groups=reported_groups,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_dumps(report), encoding="utf-8")
    if not quiet:
        show_similarity_audit_report(report)
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


def show_similarity_search_report(report: SimilaritySearchReport) -> None:
    table = Table(title="Similarity search", show_lines=False)
    table.add_column("Score", justify="right")
    table.add_column("Distance", justify="right")
    table.add_column("Filename")
    table.add_column("Path")
    for result in report.results:
        table.add_row(f"{result.score:.3f}", f"{result.distance:.4f}", result.filename, result.path)
    console.print(table)


def show_similarity_audit_report(report: SimilarityAuditReport) -> None:
    table = Table(title="Similarity near-duplicate audit", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Descriptors considered", f"{report.summary.descriptors_considered:,}")
    table.add_row("Candidate pairs", f"{report.summary.candidate_pairs:,}")
    table.add_row("Candidate groups", f"{report.summary.candidate_groups:,}")
    table.add_row("Reported groups", f"{report.summary.reported_groups:,}")
    table.add_row("Exact MD5 pairs excluded", f"{report.summary.exact_md5_pairs_excluded:,}")
    console.print(table)
    if not report.groups:
        return
    group_table = Table(title="Top similarity groups", show_lines=False)
    group_table.add_column("Group", justify="right")
    group_table.add_column("Files", justify="right")
    group_table.add_column("Pairs", justify="right")
    group_table.add_column("Max score", justify="right")
    group_table.add_column("First file")
    for group in report.groups[:20]:
        first_file = group.files[0].path if group.files else ""
        group_table.add_row(
            str(group.group_id),
            str(group.file_count),
            str(group.pair_count),
            f"{group.max_score:.3f}",
            first_file,
        )
    console.print(group_table)
