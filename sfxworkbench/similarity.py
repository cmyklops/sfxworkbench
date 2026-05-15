"""Deterministic audio descriptor crawler for future similarity workflows."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection, is_scoped_path, resolve_scope_root
from sfxworkbench.models import (
    SimilarityAuditFile,
    SimilarityAuditGroup,
    SimilarityAuditPair,
    SimilarityAuditReport,
    SimilarityAuditSummary,
    SimilarityBackendCapability,
    SimilarityBackendsReport,
    SimilarityCrawlReport,
    SimilarityCrawlSummary,
    SimilarityDescriptor,
    SimilarityFeedbackChange,
    SimilarityFeedbackEntry,
    SimilarityFeedbackReport,
    SimilarityFeedbackSummary,
    SimilaritySearchReport,
    SimilaritySearchResult,
    SimilaritySegment,
    SimilaritySegmentsReport,
    SimilaritySegmentsSummary,
)
from sfxworkbench.utils import atomic_write_json, progress_interval

console = Console()

DEFAULT_SIMILARITY_CACHE = Path.home() / ".sfxworkbench" / "similarity"
DETERMINISTIC_BACKEND = "deterministic_v1"
DETERMINISTIC_BACKEND_VERSION = "1.1"
SEGMENT_METHOD = "rms_event_v2"
_COMMIT_BATCH = 250
FEEDBACK_STATES = {"favorite", "hidden", "ignored", "accepted", "rejected"}
ProgressCallback = Callable[[str, int, int | None, str], None]
_PROGRESS_MAX_INTERVAL = 100


def _similarity_crawl_progress_message(
    *,
    processed: int,
    total: int,
    analyzed: int,
    skipped: int,
    pending: int,
    segments: int,
    errors: int,
    current: str | None = None,
) -> str:
    message = (
        f"Processed {processed:,}/{total:,}; analyzed {analyzed:,}, "
        f"skipped {skipped:,}, pending {pending:,}, segments {segments:,}, errors {errors:,}"
    )
    if current:
        return f"{message}; current {current}"
    return message


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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


def _analysis_parameters(*, max_duration_s: float | None, throttle_ms: int = 0) -> dict:
    return {
        "max_duration_s": max_duration_s,
        "throttle_ms": throttle_ms,
        "segment_method": SEGMENT_METHOD,
        "descriptor_vector": "basic_spectral_temporal_v2",
    }


def _parameters_hash(parameters: dict) -> str:
    payload = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _existing_descriptor_is_current(row, descriptor_row, *, max_duration_s: float | None, parameters_hash: str) -> bool:
    if descriptor_row is None:
        return False
    if descriptor_row["error"] is not None:
        return False
    if any(
        descriptor_row[column] is None
        for column in ("spectral_centroid", "spectral_bandwidth", "spectral_rolloff", "spectral_flatness")
    ):
        return False
    if descriptor_row["segment_method"] != SEGMENT_METHOD:
        return False
    if descriptor_row["backend_version"] != DETERMINISTIC_BACKEND_VERSION:
        return False
    if descriptor_row["parameters_hash"] != parameters_hash:
        return False
    return (
        descriptor_row["size_bytes"] == row["size_bytes"]
        and descriptor_row["mtime"] == row["mtime"]
        and descriptor_row["md5"] == row["md5"]
        and descriptor_row["max_duration_s"] == max_duration_s
    )


def _compute_audio_descriptor(path: Path, *, max_duration_s: float | None) -> dict:
    metrics, _segments = _compute_audio_analysis(path, max_duration_s=max_duration_s)
    return metrics


def _compute_audio_analysis(path: Path, *, max_duration_s: float | None) -> tuple[dict, list[dict]]:
    try:
        import numpy as np
        import soundfile as sf
    except Exception as e:
        return {"error": f"audio descriptor dependencies unavailable: {e}"}, []

    try:
        with sf.SoundFile(str(path)) as sound_file:
            sample_rate = sound_file.samplerate
            total_frames = len(sound_file)
            frames = -1
            if max_duration_s is not None and max_duration_s > 0:
                frames = min(total_frames, max(1, int(max_duration_s * sample_rate)))
            audio = sound_file.read(frames=frames, dtype="float32", always_2d=True)
    except Exception as e:
        return {"error": str(e)}, []

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
            "segment_count": 0,
            "segment_method": SEGMENT_METHOD,
            "error": None,
        }, []

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
    segments = _detect_audio_segments(mono, sample_rate, np)

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
        "segment_count": len(segments),
        "segment_method": SEGMENT_METHOD,
        "error": None,
    }, segments


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


def _compute_segment_features(segment_audio, sample_rate: int, np) -> dict[str, float | None]:
    if segment_audio.size == 0:
        return {
            "peak": 0.0,
            "rms": 0.0,
            "crest_factor": None,
            "silence_ratio": 1.0,
            "zero_crossing_rate": 0.0,
            "spectral_centroid": 0.0,
            "spectral_bandwidth": 0.0,
            "spectral_rolloff": 0.0,
            "spectral_flatness": 0.0,
        }

    abs_audio = np.abs(segment_audio)
    peak = float(abs_audio.max())
    rms = float(math.sqrt(float(np.mean(np.square(segment_audio)))))
    crest_factor = float(peak / rms) if rms > 0 else None
    silence_ratio = float(np.mean(abs_audio <= 0.0001))
    duration_s = float(segment_audio.size / sample_rate) if sample_rate else 0.0
    if segment_audio.size > 1 and duration_s > 0:
        signs = np.signbit(segment_audio)
        zero_crossings = int(np.count_nonzero(signs[1:] != signs[:-1]))
        zero_crossing_rate = float(zero_crossings / duration_s)
    else:
        zero_crossing_rate = 0.0
    return {
        "peak": peak,
        "rms": rms,
        "crest_factor": crest_factor,
        "silence_ratio": silence_ratio,
        "zero_crossing_rate": zero_crossing_rate,
        **_compute_spectral_features(segment_audio, sample_rate, np),
    }


def _detect_audio_segments(mono, sample_rate: int, np, *, max_segments: int = 10) -> list[dict]:
    if mono.size < 2 or sample_rate <= 0:
        return []

    total_duration_s = float(mono.size / sample_rate)
    frame_size = max(256, int(sample_rate * 0.05))
    hop_size = max(128, int(sample_rate * 0.025))
    if mono.size < frame_size:
        padded = np.pad(mono, (0, frame_size - mono.size))
        frames_view = padded.reshape(1, frame_size)
    else:
        frame_count = 1 + ((mono.size - frame_size) // hop_size)
        shape = (frame_count, frame_size)
        strides = (mono.strides[0] * hop_size, mono.strides[0])
        frames_view = np.lib.stride_tricks.as_strided(mono, shape=shape, strides=strides)

    frame_rms = np.sqrt(np.mean(np.square(frames_view), axis=1))
    if frame_rms.size == 0 or float(np.max(frame_rms)) <= 0.000001:
        return []

    max_rms = float(np.max(frame_rms))
    noise_floor = float(np.percentile(frame_rms, 20))
    adaptive_threshold = max(noise_floor * 3.0, max_rms * 0.1)
    threshold = max(0.002, min(max_rms * 0.5, adaptive_threshold))
    active = frame_rms >= threshold
    if not np.any(active):
        return []

    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(active)))

    merged: list[tuple[float, float]] = []
    max_gap_s = 0.15
    for start_index, end_index in ranges:
        start_s = max(0.0, (start_index * hop_size) / sample_rate)
        end_s = min(total_duration_s, (((end_index - 1) * hop_size) + frame_size) / sample_rate)
        if merged and start_s - merged[-1][1] <= max_gap_s:
            merged[-1] = (merged[-1][0], end_s)
        else:
            merged.append((start_s, end_s))

    segments: list[dict] = []
    min_duration_s = min(0.1, total_duration_s)
    for start_s, end_s in merged:
        duration_s = end_s - start_s
        if duration_s < min_duration_s:
            continue
        start_frame = max(0, int(start_s * sample_rate))
        end_frame = min(mono.size, max(start_frame + 1, int(end_s * sample_rate)))
        segment_audio = mono[start_frame:end_frame]
        features = _compute_segment_features(segment_audio, sample_rate, np)
        rms = float(features["rms"] or 0.0)
        confidence = min(1.0, rms / (threshold * 3.0)) if threshold > 0 else 0.0
        segments.append(
            {
                "start_s": start_s,
                "end_s": end_s,
                "duration_s": duration_s,
                **features,
                "confidence": confidence,
                "method": SEGMENT_METHOD,
            }
        )

    segments.sort(key=lambda segment: (-segment["confidence"], segment["start_s"]))
    segments = segments[:max_segments]
    segments.sort(key=lambda segment: segment["start_s"])
    for index, segment in enumerate(segments):
        segment["segment_index"] = index
    return segments


def _descriptor_from_row(
    row, *, backend: str, generated_at: str, max_duration_s: float | None, parameters_hash: str, metrics: dict
) -> SimilarityDescriptor:
    return SimilarityDescriptor(
        file_id=row["id"],
        path=row["path"],
        backend=backend,
        backend_version=DETERMINISTIC_BACKEND_VERSION,
        parameters_hash=parameters_hash,
        size_bytes=row["size_bytes"],
        mtime=row["mtime"],
        md5=row["md5"],
        max_duration_s=max_duration_s,
        duration_bucket=_duration_bucket(row["duration_s"]),
        generated_at=generated_at,
        **metrics,
    )


def _descriptor_from_metrics(
    path: Path, *, backend: str, generated_at: str, max_duration_s: float | None, parameters_hash: str, metrics: dict
) -> SimilarityDescriptor:
    stat = path.stat()
    return SimilarityDescriptor(
        file_id=0,
        path=str(path),
        backend=backend,
        backend_version=DETERMINISTIC_BACKEND_VERSION,
        parameters_hash=parameters_hash,
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


def _segment_vector(values: dict) -> tuple[float, ...] | None:
    if values.get("peak") is None or values.get("rms") is None:
        return None
    return (
        float(values.get("peak") or 0.0),
        float(values.get("rms") or 0.0),
        min(float(values.get("crest_factor") or 0.0), 20.0) / 20.0,
        math.log1p(float(values.get("zero_crossing_rate") or 0.0)) / 10.0,
        math.log1p(float(values.get("spectral_centroid") or 0.0)) / 10.0,
        math.log1p(float(values.get("spectral_rolloff") or 0.0)) / 10.0,
        float(values.get("spectral_flatness") or 0.0),
    )


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _score(distance: float) -> float:
    return 1.0 / (1.0 + distance)


def _segment_audit_bucket(row: dict) -> tuple[str | None, int, int, int]:
    return (
        row.get("duration_bucket"),
        int(math.log1p(float(row.get("zero_crossing_rate") or 0.0)) * 1.5),
        int(math.log1p(float(row.get("spectral_centroid") or 0.0)) * 1.5),
        int(math.log1p(float(row.get("spectral_rolloff") or 0.0)) * 1.5),
    )


def _file_audit_bucket(row: dict) -> tuple[str | None, int, int, int]:
    return (
        row.get("duration_bucket"),
        int(math.log1p(float(row.get("zero_crossing_rate") or 0.0)) * 1.5),
        int(math.log1p(float(row.get("spectral_centroid") or 0.0)) * 1.5),
        int(math.log1p(float(row.get("spectral_rolloff") or 0.0)) * 1.5),
    )


def _audit_candidate_unit_pairs(unit_ids: list[int], by_id: dict[int, dict], *, scope: str) -> list[tuple[int, int]]:
    buckets: dict[tuple[str | None, int, int, int], list[int]] = {}
    for unit_id in unit_ids:
        bucket = _file_audit_bucket(by_id[unit_id]) if scope == "file" else _segment_audit_bucket(by_id[unit_id])
        buckets.setdefault(bucket, []).append(unit_id)

    pairs: set[tuple[int, int]] = set()
    for bucket_ids in buckets.values():
        if len(bucket_ids) < 2:
            continue
        ordered_ids = sorted(bucket_ids)
        for left_index, left_id in enumerate(ordered_ids):
            left = by_id[left_id]
            for right_id in ordered_ids[left_index + 1 :]:
                if left["file_id"] == by_id[right_id]["file_id"]:
                    continue
                pairs.add((left_id, right_id))
    return sorted(pairs)


def _write_descriptor(conn, descriptor: SimilarityDescriptor) -> None:
    conn.execute(
        """
        INSERT INTO audio_descriptors (
            file_id, backend, backend_version, parameters_hash, path, size_bytes, mtime, md5,
            max_duration_s, analyzed_duration_s,
            peak, rms, crest_factor, silence_ratio, clipping_count,
            zero_crossing_rate, transient_density, spectral_centroid, spectral_bandwidth,
            spectral_rolloff, spectral_flatness, segment_count, segment_method,
            duration_bucket, generated_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id, backend) DO UPDATE SET
            backend_version=excluded.backend_version,
            parameters_hash=excluded.parameters_hash,
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
            segment_count=excluded.segment_count,
            segment_method=excluded.segment_method,
            duration_bucket=excluded.duration_bucket,
            generated_at=excluded.generated_at,
            error=excluded.error
        """,
        (
            descriptor.file_id,
            descriptor.backend,
            descriptor.backend_version,
            descriptor.parameters_hash,
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
            descriptor.segment_count,
            descriptor.segment_method,
            descriptor.duration_bucket,
            descriptor.generated_at,
            descriptor.error,
        ),
    )


def _delete_segments(conn, *, file_id: int, backend: str, max_duration_s: float | None) -> None:
    conn.execute(
        """
        DELETE FROM audio_segments
        WHERE file_id = ? AND backend = ?
          AND ((? IS NULL AND max_duration_s IS NULL) OR max_duration_s = ?)
        """,
        (file_id, backend, max_duration_s, max_duration_s),
    )


def _write_segments(
    conn,
    *,
    file_id: int,
    path: str,
    backend: str,
    backend_version: str,
    parameters_hash: str,
    max_duration_s: float | None,
    generated_at: str,
    segments: list[dict],
) -> None:
    _delete_segments(conn, file_id=file_id, backend=backend, max_duration_s=max_duration_s)
    for segment in segments:
        conn.execute(
            """
            INSERT INTO audio_segments (
                file_id, backend, backend_version, parameters_hash, path, max_duration_s,
                segment_index, start_s, end_s,
                duration_s, peak, rms, crest_factor, silence_ratio, zero_crossing_rate,
                spectral_centroid, spectral_bandwidth, spectral_rolloff, spectral_flatness,
                confidence, method, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                backend,
                backend_version,
                parameters_hash,
                path,
                max_duration_s,
                segment["segment_index"],
                segment["start_s"],
                segment["end_s"],
                segment["duration_s"],
                segment["peak"],
                segment["rms"],
                segment["crest_factor"],
                segment["silence_ratio"],
                segment["zero_crossing_rate"],
                segment["spectral_centroid"],
                segment["spectral_bandwidth"],
                segment["spectral_rolloff"],
                segment["spectral_flatness"],
                segment["confidence"],
                segment["method"],
                generated_at,
            ),
        )


def crawl_similarity_descriptors(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    cache_path: Path | None = DEFAULT_SIMILARITY_CACHE,
    max_duration_s: float | None = 30.0,
    force: bool = False,
    max_files: int | None = None,
    throttle_ms: int = 0,
    limit: int = 50,
    quiet: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> SimilarityCrawlReport:
    """Analyze indexed files under root and cache deterministic descriptors."""
    root = resolve_scope_root(root)
    if not root.exists():
        raise ValueError(f"path not found: {root}")
    if max_files is not None and max_files < 1:
        raise ValueError("max_files must be at least 1")
    if throttle_ms < 0:
        raise ValueError("throttle_ms must be 0 or greater")
    if cache_path is not None:
        cache_path = cache_path.expanduser().resolve()
        cache_path.mkdir(parents=True, exist_ok=True)
    parameters = _analysis_parameters(max_duration_s=max_duration_s, throttle_ms=throttle_ms)
    parameters_hash = _parameters_hash(parameters)

    conn = get_connection(db_path)
    started_at = _utc_now()
    run_row = conn.execute(
        """
        INSERT INTO analysis_runs (
            backend, backend_version, parameters_json, parameters_hash, segment_method,
            root, db_path, cache_path, max_duration_s, max_files, force, started_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            DETERMINISTIC_BACKEND,
            DETERMINISTIC_BACKEND_VERSION,
            json.dumps(parameters, sort_keys=True),
            parameters_hash,
            SEGMENT_METHOD,
            str(root),
            str(db_path),
            str(cache_path) if cache_path else None,
            max_duration_s,
            max_files,
            int(force),
            started_at,
            "running",
        ),
    ).fetchone()
    run_id = int(run_row["id"])
    conn.commit()

    if progress_callback is not None:
        progress_callback("loading", 0, None, "Loading indexed files")
    rows = conn.execute(
        """
        SELECT id, path, filename, size_bytes, mtime, md5, sample_rate, bit_depth,
               channels, duration_s
        FROM files
        WHERE scan_error IS NULL
        ORDER BY path
        """
    ).fetchall()
    rows = [row for row in rows if is_scoped_path(row["path"], root)]
    total = len(rows)
    if progress_callback is not None:
        progress_callback(
            "crawling",
            0,
            total,
            _similarity_crawl_progress_message(
                processed=0,
                total=total,
                analyzed=0,
                skipped=0,
                pending=0,
                segments=0,
                errors=0,
            ),
        )
    report_every = min(progress_interval(total), _PROGRESS_MAX_INTERVAL)

    summary = SimilarityCrawlSummary(total_files=len(rows))

    def report_progress(completed: int, current: str, *, force: bool = False) -> None:
        if progress_callback is None:
            return
        if force or completed % report_every == 0 or completed == total:
            progress_callback(
                "crawling",
                completed,
                total,
                _similarity_crawl_progress_message(
                    processed=completed,
                    total=total,
                    analyzed=summary.analyzed,
                    skipped=summary.skipped,
                    pending=summary.pending,
                    segments=summary.segments_detected,
                    errors=summary.errors,
                    current=current,
                ),
            )

    descriptors: list[SimilarityDescriptor] = []
    pending = 0
    status = "completed"
    stop_reason: str | None = None

    try:
        for processed, row in enumerate(rows, start=1):
            if cancel_requested is not None and cancel_requested():
                status = "cancelled"
                stop_reason = "cancelled"
                summary.pending += total - processed + 1
                break
            existing = conn.execute(
                """
                SELECT size_bytes, mtime, md5, max_duration_s, error, spectral_centroid,
                       spectral_bandwidth, spectral_rolloff, spectral_flatness,
                       segment_method, backend_version, parameters_hash
                FROM audio_descriptors
                WHERE file_id = ? AND backend = ?
                """,
                (row["id"], DETERMINISTIC_BACKEND),
            ).fetchone()
            if not force and _existing_descriptor_is_current(
                row, existing, max_duration_s=max_duration_s, parameters_hash=parameters_hash
            ):
                summary.skipped += 1
                report_progress(processed, row["filename"])
                continue

            if max_files is not None and summary.analyzed >= max_files:
                summary.pending += 1
                report_progress(processed, row["filename"])
                continue

            path = Path(row["path"])
            generated_at = _utc_now()
            report_progress(processed - 1, row["filename"], force=processed == 1)
            if not path.exists():
                metrics = {"error": "file not found"}
                segments = []
            else:
                metrics, segments = _compute_audio_analysis(path, max_duration_s=max_duration_s)

            descriptor = _descriptor_from_row(
                row,
                backend=DETERMINISTIC_BACKEND,
                generated_at=generated_at,
                max_duration_s=max_duration_s,
                parameters_hash=parameters_hash,
                metrics=metrics,
            )
            _write_descriptor(conn, descriptor)
            _write_segments(
                conn,
                file_id=row["id"],
                path=row["path"],
                backend=DETERMINISTIC_BACKEND,
                backend_version=DETERMINISTIC_BACKEND_VERSION,
                parameters_hash=parameters_hash,
                max_duration_s=max_duration_s,
                generated_at=generated_at,
                segments=segments,
            )
            summary.analyzed += 1
            summary.segments_detected += len(segments)
            if descriptor.error is not None:
                summary.errors += 1
            if limit <= 0 or len(descriptors) < limit:
                descriptors.append(descriptor)
            pending += 1
            if pending >= _COMMIT_BATCH:
                conn.commit()
                pending = 0
            if throttle_ms:
                time.sleep(throttle_ms / 1000.0)
            report_progress(processed, row["filename"])
    except KeyboardInterrupt:
        status = "interrupted"
        stop_reason = "keyboard_interrupt"
    if summary.pending:
        status = "partial" if status == "completed" else status
        stop_reason = stop_reason or "max_files"
    summary.stale = max(0, summary.total_files - summary.skipped - summary.analyzed)

    finished_at = _utc_now()
    if progress_callback is not None:
        progress_callback(
            "updating_index", summary.analyzed + summary.skipped, total, "Recording similarity run status"
        )
    conn.execute(
        """
        UPDATE analysis_runs
        SET finished_at = ?, status = ?, status_reason = ?, total_files = ?, analyzed = ?, skipped = ?, errors = ?
        WHERE id = ?
        """,
        (
            finished_at,
            status,
            stop_reason,
            summary.total_files,
            summary.analyzed,
            summary.skipped,
            summary.errors,
            run_id,
        ),
    )
    conn.commit()
    conn.close()

    report = SimilarityCrawlReport(
        generated_at=finished_at,
        tool_version=__version__,
        run_id=run_id,
        backend=DETERMINISTIC_BACKEND,
        backend_version=DETERMINISTIC_BACKEND_VERSION,
        segment_method=SEGMENT_METHOD,
        parameters_hash=parameters_hash,
        root=str(root),
        db_path=str(db_path),
        cache_path=str(cache_path) if cache_path else None,
        max_duration_s=max_duration_s,
        max_files=max_files,
        force=force,
        status=status,
        stop_reason=stop_reason,
        summary=summary,
        descriptors=descriptors,
    )
    if cache_path is not None:
        report_path = cache_path / f"similarity_crawl_{run_id}.json"
        if progress_callback is not None:
            progress_callback("writing_report", 0, None, f"Writing similarity crawl report to {report_path.name}")
        atomic_write_json(report_path, report)
    if progress_callback is not None:
        completed_for_progress = summary.skipped + summary.analyzed + summary.pending
        progress_callback(
            "cancelled" if status == "cancelled" else "complete",
            min(total, completed_for_progress),
            total,
            _similarity_crawl_progress_message(
                processed=min(total, completed_for_progress),
                total=total,
                analyzed=summary.analyzed,
                skipped=summary.skipped,
                pending=summary.pending,
                segments=summary.segments_detected,
                errors=summary.errors,
            ),
        )
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
    return [row for row in rows if is_scoped_path(row["path"], root)]


def _segment_rows(conn, *, root: Path | None, max_duration_s: float | None):
    rows = conn.execute(
        """
        SELECT s.file_id, s.path, f.filename, f.md5, f.sample_rate,
               f.bit_depth, f.channels, f.duration_s AS file_duration_s,
               s.segment_index, s.start_s, s.end_s, s.duration_s,
               s.peak, s.rms, s.crest_factor, s.silence_ratio,
               s.zero_crossing_rate, s.spectral_centroid, s.spectral_bandwidth,
               s.spectral_rolloff, s.spectral_flatness, s.confidence, s.method
        FROM audio_segments s
        JOIN files f ON f.id = s.file_id
        WHERE s.backend = ?
          AND s.method = ?
          AND ((? IS NULL AND s.max_duration_s IS NULL) OR s.max_duration_s = ?)
        ORDER BY s.path, s.segment_index
        """,
        (DETERMINISTIC_BACKEND, SEGMENT_METHOD, max_duration_s, max_duration_s),
    ).fetchall()
    if root is None:
        return rows
    return [row for row in rows if is_scoped_path(row["path"], root)]


def _normalize_scope(scope: str) -> str:
    normalized = scope.lower()
    if normalized not in {"file", "segment"}:
        raise ValueError("scope must be 'file' or 'segment'")
    return normalized


def _normalize_feedback_state(state: str) -> str:
    normalized = state.lower()
    if normalized not in FEEDBACK_STATES:
        allowed = ", ".join(sorted(FEEDBACK_STATES))
        raise ValueError(f"state must be one of: {allowed}")
    return normalized


def _resolve_file_row(conn, path: Path):
    resolved = path.expanduser().resolve()
    row = conn.execute(
        "SELECT id, path, filename FROM files WHERE path = ?",
        (str(resolved),),
    ).fetchone()
    if row is None:
        raise ValueError(f"file is not indexed: {resolved}")
    return row


def _validate_feedback_segments(
    conn,
    *,
    left_file_id: int,
    right_file_id: int,
    left_segment_index: int | None,
    right_segment_index: int | None,
    max_duration_s: float | None,
) -> tuple[int, int]:
    if left_segment_index is None or right_segment_index is None:
        raise ValueError("--left-segment and --right-segment are required for segment feedback")
    for file_id, segment_index in (
        (left_file_id, left_segment_index),
        (right_file_id, right_segment_index),
    ):
        row = conn.execute(
            """
            SELECT 1
            FROM audio_segments
            WHERE file_id = ? AND backend = ? AND method = ? AND segment_index = ?
              AND ((? IS NULL AND max_duration_s IS NULL) OR max_duration_s = ?)
            """,
            (file_id, DETERMINISTIC_BACKEND, SEGMENT_METHOD, segment_index, max_duration_s, max_duration_s),
        ).fetchone()
        if row is None:
            raise ValueError(f"segment {segment_index} is not cached for indexed file id {file_id}")
    return left_segment_index, right_segment_index


def _normalized_feedback_pair(
    *,
    left_file_id: int,
    right_file_id: int,
    left_segment_index: int,
    right_segment_index: int,
) -> tuple[int, int, int, int]:
    left_key = (left_file_id, left_segment_index)
    right_key = (right_file_id, right_segment_index)
    if left_key == right_key:
        raise ValueError("feedback requires two different files or segments")
    if right_key < left_key:
        return right_file_id, left_file_id, right_segment_index, left_segment_index
    return left_file_id, right_file_id, left_segment_index, right_segment_index


def _feedback_entry_from_row(row) -> SimilarityFeedbackEntry:
    left_segment_index = row["left_segment_index"]
    right_segment_index = row["right_segment_index"]
    return SimilarityFeedbackEntry(
        id=row["id"],
        backend=row["backend"],
        scope=row["scope"],
        state=row["state"],
        left_file_id=row["left_file_id"],
        right_file_id=row["right_file_id"],
        left_path=row["left_path"],
        right_path=row["right_path"],
        left_filename=row["left_filename"],
        right_filename=row["right_filename"],
        left_segment_index=None if left_segment_index < 0 else left_segment_index,
        right_segment_index=None if right_segment_index < 0 else right_segment_index,
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _feedback_select_sql(where_sql: str = "") -> str:
    return f"""
        SELECT fb.id, fb.backend, fb.scope, fb.state,
               fb.left_file_id, fb.right_file_id,
               fb.left_segment_index, fb.right_segment_index,
               fb.note, fb.created_at, fb.updated_at,
               lf.path AS left_path, rf.path AS right_path,
               lf.filename AS left_filename, rf.filename AS right_filename
        FROM similarity_feedback fb
        JOIN files lf ON lf.id = fb.left_file_id
        JOIN files rf ON rf.id = fb.right_file_id
        {where_sql}
        ORDER BY fb.updated_at DESC, fb.id DESC
    """


def similarity_backends_report() -> SimilarityBackendsReport:
    """Describe similarity analysis backends without running analysis."""
    return SimilarityBackendsReport(
        generated_at=_utc_now(),
        tool_version=__version__,
        default_backend=DETERMINISTIC_BACKEND,
        capabilities=[
            SimilarityBackendCapability(
                backend=DETERMINISTIC_BACKEND,
                backend_version=DETERMINISTIC_BACKEND_VERSION,
                status="available",
                scope=["file", "segment"],
                model_version="none",
                parameters=_analysis_parameters(max_duration_s=30.0),
                notes=[
                    "Deterministic local descriptor backend; no audio leaves disk.",
                    "Report-only search and audit evidence, not cleanup proof.",
                ],
            ),
            SimilarityBackendCapability(
                backend="fingerprint_optional",
                backend_version="deferred",
                status="not_configured",
                scope=["file"],
                notes=[
                    "Reserved for a future perceptual fingerprint backend after dependency and license review.",
                ],
            ),
            SimilarityBackendCapability(
                backend="embedding_optional",
                backend_version="deferred",
                status="not_configured",
                scope=["file", "segment"],
                model_version="unselected",
                notes=[
                    "Schema is reserved in audio_embeddings; no embedding model is bundled or run by default.",
                ],
            ),
        ],
    )


def _feedback_entry_by_id(conn, feedback_id: int) -> SimilarityFeedbackEntry:
    row = conn.execute(_feedback_select_sql("WHERE fb.id = ?"), (feedback_id,)).fetchone()
    if row is None:
        raise ValueError(f"feedback row not found: {feedback_id}")
    return _feedback_entry_from_row(row)


def search_similarity_descriptors(
    query_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    max_duration_s: float | None = 30.0,
    limit: int = 20,
    scope: str = "file",
    quiet: bool = False,
) -> SimilaritySearchReport:
    """Search cached deterministic descriptors using a query audio file."""
    query_path = query_path.expanduser().resolve()
    if not query_path.exists():
        raise ValueError(f"query file not found: {query_path}")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if scope not in {"file", "segment"}:
        raise ValueError("scope must be 'file' or 'segment'")

    generated_at = _utc_now()
    parameters = _analysis_parameters(max_duration_s=max_duration_s)
    parameters_hash = _parameters_hash(parameters)
    query_metrics = _compute_audio_descriptor(query_path, max_duration_s=max_duration_s)
    query_descriptor = _descriptor_from_metrics(
        query_path,
        backend=DETERMINISTIC_BACKEND,
        generated_at=generated_at,
        max_duration_s=max_duration_s,
        parameters_hash=parameters_hash,
        metrics=query_metrics,
    )
    query_values = query_descriptor.model_dump()
    query_vector = _segment_vector(query_values) if scope == "segment" else _descriptor_vector(query_values)
    if query_vector is None:
        raise ValueError(f"could not analyze query file: {query_descriptor.error}")

    conn = get_connection(db_path)
    if scope == "segment":
        rows = _segment_rows(conn, root=None, max_duration_s=max_duration_s)
    else:
        rows = _descriptor_rows(conn, root=None, max_duration_s=max_duration_s)
    conn.close()

    scored: list[SimilaritySearchResult] = []
    for row in rows:
        candidate_values = dict(row)
        candidate_vector = (
            _segment_vector(candidate_values) if scope == "segment" else _descriptor_vector(candidate_values)
        )
        if candidate_vector is None:
            continue
        distance = _distance(query_vector, candidate_vector)
        segment_kwargs = {}
        if scope == "segment":
            segment_kwargs = {
                "segment_index": row["segment_index"],
                "segment_start_s": row["start_s"],
                "segment_end_s": row["end_s"],
                "segment_duration_s": row["duration_s"],
                "segment_confidence": row["confidence"],
                "segment_method": row["method"],
            }
        scored.append(
            SimilaritySearchResult(
                scope=scope,
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                distance=distance,
                score=_score(distance),
                duration_s=row["file_duration_s"] if scope == "segment" else row["duration_s"],
                sample_rate=row["sample_rate"],
                bit_depth=row["bit_depth"],
                channels=row["channels"],
                peak=row["peak"],
                rms=row["rms"],
                crest_factor=row["crest_factor"],
                silence_ratio=row["silence_ratio"],
                clipping_count=0 if scope == "segment" else row["clipping_count"],
                zero_crossing_rate=row["zero_crossing_rate"],
                transient_density=0.0 if scope == "segment" else row["transient_density"],
                spectral_centroid=row["spectral_centroid"],
                spectral_bandwidth=row["spectral_bandwidth"],
                spectral_rolloff=row["spectral_rolloff"],
                spectral_flatness=row["spectral_flatness"],
                duration_bucket=_duration_bucket(row["duration_s"]) if scope == "segment" else row["duration_bucket"],
                **segment_kwargs,
            )
        )

    scored.sort(key=lambda result: (result.distance, result.path, result.segment_index or -1))
    report = SimilaritySearchReport(
        generated_at=generated_at,
        tool_version=__version__,
        backend=DETERMINISTIC_BACKEND,
        query_path=str(query_path),
        db_path=str(db_path),
        scope=scope,
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
    scope: str = "file",
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
    if scope not in {"file", "segment"}:
        raise ValueError("scope must be 'file' or 'segment'")

    conn = get_connection(db_path)
    if scope == "segment":
        raw_rows = _segment_rows(conn, root=root, max_duration_s=max_duration_s)
        rows = []
        for unit_id, row in enumerate(raw_rows):
            values = dict(row)
            values["unit_id"] = unit_id
            values["duration_bucket"] = _duration_bucket(row["duration_s"])
            rows.append(values)
    else:
        rows = [dict(row) for row in _descriptor_rows(conn, root=root, max_duration_s=max_duration_s)]
        for row in rows:
            row["unit_id"] = row["file_id"]
    conn.close()

    vectors: dict[int, tuple[float, ...]] = {}
    by_id = {int(row["unit_id"]): row for row in rows}
    file_row_by_id: dict[int, dict] = {}
    for row in rows:
        file_row_by_id.setdefault(int(row["file_id"]), row)
    for row in rows:
        vector = _segment_vector(row) if scope == "segment" else _descriptor_vector(row)
        if vector is not None:
            vectors[int(row["unit_id"])] = vector

    parent: dict[int, int] = {unit_id: unit_id for unit_id in vectors}

    def find(unit_id: int) -> int:
        while parent[unit_id] != unit_id:
            parent[unit_id] = parent[parent[unit_id]]
            unit_id = parent[unit_id]
        return unit_id

    def union(left_unit_id: int, right_unit_id: int) -> None:
        left_root = find(left_unit_id)
        right_root = find(right_unit_id)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    pair_units: list[tuple[int, int, SimilarityAuditPair]] = []
    exact_md5_pairs_excluded = 0
    unit_ids = sorted(vectors)
    candidate_unit_pairs = _audit_candidate_unit_pairs(unit_ids, by_id, scope=scope)
    for left_id, right_id in candidate_unit_pairs:
        left = by_id[left_id]
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
            scope=scope,
            left_file_id=left["file_id"],
            right_file_id=right["file_id"],
            left_path=left["path"],
            right_path=right["path"],
            left_segment_index=left.get("segment_index"),
            left_segment_start_s=left.get("start_s"),
            left_segment_end_s=left.get("end_s"),
            right_segment_index=right.get("segment_index"),
            right_segment_start_s=right.get("start_s"),
            right_segment_end_s=right.get("end_s"),
            distance=distance,
            score=score,
            shared_duration_bucket=left["duration_bucket"] == right["duration_bucket"],
        )
        pair_units.append((left_id, right_id, pair))
        union(left_id, right_id)

    group_pairs: dict[int, list[SimilarityAuditPair]] = {}
    group_file_ids: dict[int, set[int]] = {}
    for left_unit_id, _right_unit_id, pair in pair_units:
        root_id = find(left_unit_id)
        group_pairs.setdefault(root_id, []).append(pair)
        group_file_ids.setdefault(root_id, set()).update({pair.left_file_id, pair.right_file_id})

    groups: list[SimilarityAuditGroup] = []
    for group_index, root_id in enumerate(sorted(group_pairs), start=1):
        group_pair_list = sorted(group_pairs[root_id], key=lambda pair: (-pair.score, pair.left_path, pair.right_path))
        file_rows = [
            file_row_by_id[file_id]
            for file_id in sorted(
                group_file_ids[root_id],
                key=lambda file_id: file_row_by_id[file_id]["path"],
            )
        ]
        files = [
            SimilarityAuditFile(
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                md5=row["md5"],
                duration_s=row["file_duration_s"] if scope == "segment" else row["duration_s"],
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
        scope=scope,
        threshold=threshold,
        max_duration_s=max_duration_s,
        exclude_exact_md5=exclude_exact_md5,
        limit=limit,
        summary=SimilarityAuditSummary(
            descriptors_considered=len(vectors),
            candidate_comparisons=len(candidate_unit_pairs),
            candidate_pairs=len(pair_units),
            exact_md5_pairs_excluded=exact_md5_pairs_excluded,
            candidate_groups=len(groups),
            reported_groups=len(reported_groups),
        ),
        groups=reported_groups,
    )
    if output_path is not None:
        atomic_write_json(output_path, report)
    if not quiet:
        show_similarity_audit_report(report)
    return report


def list_similarity_segments(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    max_duration_s: float | None = 30.0,
    limit: int = 200,
    quiet: bool = False,
) -> SimilaritySegmentsReport:
    """List cached event-like segment windows from the deterministic crawler."""
    root = root.expanduser().resolve()
    if not root.exists():
        raise ValueError(f"path not found: {root}")
    if limit < 0:
        raise ValueError("limit must be 0 or greater")

    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT s.file_id, s.path, f.filename, s.backend, s.max_duration_s,
               s.segment_index, s.start_s, s.end_s, s.duration_s, s.peak,
               s.rms, s.crest_factor, s.silence_ratio, s.zero_crossing_rate,
               s.spectral_centroid, s.spectral_bandwidth, s.spectral_rolloff,
               s.spectral_flatness, s.confidence, s.method, s.generated_at
        FROM audio_segments s
        JOIN files f ON f.id = s.file_id
        WHERE s.backend = ?
          AND ((? IS NULL AND s.max_duration_s IS NULL) OR s.max_duration_s = ?)
        ORDER BY s.path, s.segment_index
        """,
        (DETERMINISTIC_BACKEND, max_duration_s, max_duration_s),
    ).fetchall()
    conn.close()
    rows = [row for row in rows if is_scoped_path(row["path"], root)]

    reported_rows = rows if limit == 0 else rows[:limit]
    segments = [
        SimilaritySegment(
            file_id=row["file_id"],
            path=row["path"],
            filename=row["filename"],
            backend=row["backend"],
            max_duration_s=row["max_duration_s"],
            segment_index=row["segment_index"],
            start_s=row["start_s"],
            end_s=row["end_s"],
            duration_s=row["duration_s"],
            peak=row["peak"],
            rms=row["rms"],
            crest_factor=row["crest_factor"],
            silence_ratio=row["silence_ratio"],
            zero_crossing_rate=row["zero_crossing_rate"],
            spectral_centroid=row["spectral_centroid"],
            spectral_bandwidth=row["spectral_bandwidth"],
            spectral_rolloff=row["spectral_rolloff"],
            spectral_flatness=row["spectral_flatness"],
            confidence=row["confidence"],
            method=row["method"],
            generated_at=row["generated_at"],
        )
        for row in reported_rows
    ]
    report = SimilaritySegmentsReport(
        generated_at=_utc_now(),
        tool_version=__version__,
        backend=DETERMINISTIC_BACKEND,
        root=str(root),
        db_path=str(db_path),
        max_duration_s=max_duration_s,
        limit=limit,
        summary=SimilaritySegmentsSummary(
            files_with_segments=len({row["file_id"] for row in rows}),
            segments=len(rows),
        ),
        segments=segments,
    )
    if not quiet:
        show_similarity_segments_report(report)
    return report


def set_similarity_feedback(
    *,
    left_path: Path,
    right_path: Path,
    state: str,
    db_path: Path = DEFAULT_DB_PATH,
    scope: str = "file",
    left_segment_index: int | None = None,
    right_segment_index: int | None = None,
    max_duration_s: float | None = 30.0,
    note: str | None = None,
    quiet: bool = False,
) -> SimilarityFeedbackChange:
    """Store a DB-only review state for a similarity relationship."""
    scope = _normalize_scope(scope)
    state = _normalize_feedback_state(state)
    conn = get_connection(db_path)
    left_row = _resolve_file_row(conn, left_path)
    right_row = _resolve_file_row(conn, right_path)
    if scope == "segment":
        left_segment, right_segment = _validate_feedback_segments(
            conn,
            left_file_id=left_row["id"],
            right_file_id=right_row["id"],
            left_segment_index=left_segment_index,
            right_segment_index=right_segment_index,
            max_duration_s=max_duration_s,
        )
    else:
        if left_segment_index is not None or right_segment_index is not None:
            raise ValueError("segment indexes are only valid with --scope segment")
        left_segment = -1
        right_segment = -1

    left_file_id, right_file_id, left_segment, right_segment = _normalized_feedback_pair(
        left_file_id=left_row["id"],
        right_file_id=right_row["id"],
        left_segment_index=left_segment,
        right_segment_index=right_segment,
    )
    now = _utc_now()
    row = conn.execute(
        """
        INSERT INTO similarity_feedback (
            backend, scope, left_file_id, right_file_id,
            left_segment_index, right_segment_index, state, note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (
            backend, scope, left_file_id, right_file_id,
            left_segment_index, right_segment_index
        ) DO UPDATE SET
            state = excluded.state,
            note = excluded.note,
            updated_at = excluded.updated_at
        RETURNING id
        """,
        (
            DETERMINISTIC_BACKEND,
            scope,
            left_file_id,
            right_file_id,
            left_segment,
            right_segment,
            state,
            note,
            now,
            now,
        ),
    ).fetchone()
    conn.commit()
    entry = _feedback_entry_by_id(conn, int(row["id"]))
    conn.close()
    result = SimilarityFeedbackChange(
        generated_at=now,
        tool_version=__version__,
        db_path=str(db_path),
        backend=DETERMINISTIC_BACKEND,
        action="set",
        entry=entry,
    )
    if not quiet:
        show_similarity_feedback_change(result)
    return result


def clear_similarity_feedback(
    *,
    left_path: Path,
    right_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    scope: str = "file",
    left_segment_index: int | None = None,
    right_segment_index: int | None = None,
    max_duration_s: float | None = 30.0,
    state: str | None = None,
    quiet: bool = False,
) -> SimilarityFeedbackChange:
    """Remove a DB-only review state for a similarity relationship."""
    scope = _normalize_scope(scope)
    normalized_state = _normalize_feedback_state(state) if state is not None else None
    conn = get_connection(db_path)
    left_row = _resolve_file_row(conn, left_path)
    right_row = _resolve_file_row(conn, right_path)
    if scope == "segment":
        left_segment, right_segment = _validate_feedback_segments(
            conn,
            left_file_id=left_row["id"],
            right_file_id=right_row["id"],
            left_segment_index=left_segment_index,
            right_segment_index=right_segment_index,
            max_duration_s=max_duration_s,
        )
    else:
        if left_segment_index is not None or right_segment_index is not None:
            raise ValueError("segment indexes are only valid with --scope segment")
        left_segment = -1
        right_segment = -1

    left_file_id, right_file_id, left_segment, right_segment = _normalized_feedback_pair(
        left_file_id=left_row["id"],
        right_file_id=right_row["id"],
        left_segment_index=left_segment,
        right_segment_index=right_segment,
    )
    params: list[object] = [
        DETERMINISTIC_BACKEND,
        scope,
        left_file_id,
        right_file_id,
        left_segment,
        right_segment,
    ]
    state_sql = ""
    if normalized_state is not None:
        state_sql = " AND state = ?"
        params.append(normalized_state)
    cursor = conn.execute(
        f"""
        DELETE FROM similarity_feedback
        WHERE backend = ? AND scope = ? AND left_file_id = ? AND right_file_id = ?
          AND left_segment_index = ? AND right_segment_index = ?
          {state_sql}
        """,
        params,
    )
    conn.commit()
    conn.close()
    result = SimilarityFeedbackChange(
        generated_at=_utc_now(),
        tool_version=__version__,
        db_path=str(db_path),
        backend=DETERMINISTIC_BACKEND,
        action="clear",
        removed=cursor.rowcount,
    )
    if not quiet:
        show_similarity_feedback_change(result)
    return result


def list_similarity_feedback(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    scope: str | None = None,
    state: str | None = None,
    limit: int = 200,
    quiet: bool = False,
) -> SimilarityFeedbackReport:
    """List DB-only similarity review feedback."""
    if limit < 0:
        raise ValueError("limit must be 0 or greater")
    normalized_scope = _normalize_scope(scope) if scope is not None else None
    normalized_state = _normalize_feedback_state(state) if state is not None else None
    where: list[str] = ["fb.backend = ?"]
    params: list[object] = [DETERMINISTIC_BACKEND]
    if normalized_scope is not None:
        where.append("fb.scope = ?")
        params.append(normalized_scope)
    if normalized_state is not None:
        where.append("fb.state = ?")
        params.append(normalized_state)
    where_sql = "WHERE " + " AND ".join(where)

    conn = get_connection(db_path)
    rows = conn.execute(_feedback_select_sql(where_sql), params).fetchall()
    conn.close()
    by_state: dict[str, int] = {}
    for row in rows:
        by_state[row["state"]] = by_state.get(row["state"], 0) + 1
    reported_rows = rows if limit == 0 else rows[:limit]
    report = SimilarityFeedbackReport(
        generated_at=_utc_now(),
        tool_version=__version__,
        db_path=str(db_path),
        backend=DETERMINISTIC_BACKEND,
        scope=normalized_scope,
        state=normalized_state,
        limit=limit,
        summary=SimilarityFeedbackSummary(total=len(rows), by_state=by_state),
        entries=[_feedback_entry_from_row(row) for row in reported_rows],
    )
    if not quiet:
        show_similarity_feedback_report(report)
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
    table.add_row("Segments detected", f"{report.summary.segments_detected:,}")
    table.add_row("Cache", report.cache_path or "SQLite only")
    console.print(table)


def show_similarity_search_report(report: SimilaritySearchReport) -> None:
    table = Table(title="Similarity search", show_lines=False)
    table.add_column("Score", justify="right")
    table.add_column("Distance", justify="right")
    table.add_column("Scope")
    table.add_column("Filename")
    table.add_column("Segment")
    table.add_column("Path")
    for result in report.results:
        segment = ""
        if result.scope == "segment" and result.segment_start_s is not None and result.segment_end_s is not None:
            segment = f"{result.segment_start_s:.2f}-{result.segment_end_s:.2f}s"
        table.add_row(
            f"{result.score:.3f}", f"{result.distance:.4f}", result.scope, result.filename, segment, result.path
        )
    console.print(table)


def show_similarity_audit_report(report: SimilarityAuditReport) -> None:
    table = Table(title="Similarity near-duplicate audit", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Scope", report.scope)
    table.add_row("Descriptors considered", f"{report.summary.descriptors_considered:,}")
    table.add_row("Candidate comparisons", f"{report.summary.candidate_comparisons:,}")
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


def show_similarity_segments_report(report: SimilaritySegmentsReport) -> None:
    table = Table(title="Similarity segments", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Files with segments", f"{report.summary.files_with_segments:,}")
    table.add_row("Segments", f"{report.summary.segments:,}")
    table.add_row("Reported", f"{len(report.segments):,}")
    console.print(table)
    if not report.segments:
        return

    segment_table = Table(title="Cached segment windows", show_lines=False)
    segment_table.add_column("File")
    segment_table.add_column("Index", justify="right")
    segment_table.add_column("Start", justify="right")
    segment_table.add_column("End", justify="right")
    segment_table.add_column("Confidence", justify="right")
    for segment in report.segments[:20]:
        segment_table.add_row(
            segment.filename or Path(segment.path).name,
            str(segment.segment_index),
            f"{segment.start_s:.2f}s",
            f"{segment.end_s:.2f}s",
            f"{segment.confidence or 0.0:.2f}",
        )
    console.print(segment_table)


def show_similarity_feedback_report(report: SimilarityFeedbackReport) -> None:
    table = Table(title="Similarity feedback", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total", f"{report.summary.total:,}")
    if report.scope:
        table.add_row("Scope", report.scope)
    if report.state:
        table.add_row("State", report.state)
    for state, count in sorted(report.summary.by_state.items()):
        table.add_row(state, f"{count:,}")
    console.print(table)
    if not report.entries:
        return

    entries_table = Table(title="Review states", show_lines=False)
    entries_table.add_column("State")
    entries_table.add_column("Scope")
    entries_table.add_column("Left")
    entries_table.add_column("Right")
    entries_table.add_column("Note")
    for entry in report.entries[:20]:
        left = entry.left_filename
        right = entry.right_filename
        if entry.scope == "segment":
            left = f"{left}#{entry.left_segment_index}"
            right = f"{right}#{entry.right_segment_index}"
        entries_table.add_row(entry.state, entry.scope, left, right, entry.note or "")
    console.print(entries_table)


def show_similarity_feedback_change(result: SimilarityFeedbackChange) -> None:
    table = Table(title="Similarity feedback change", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Action", result.action)
    if result.action == "clear":
        table.add_row("Removed", f"{result.removed:,}")
    if result.entry is not None:
        table.add_row("State", result.entry.state)
        table.add_row("Scope", result.entry.scope)
        table.add_row("Left", result.entry.left_path)
        table.add_row("Right", result.entry.right_path)
    console.print(table)
