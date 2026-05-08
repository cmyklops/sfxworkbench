import json
import math
import struct
import wave
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.scan import scan_library
from wavwarden.similarity import (
    audit_similarity_descriptors,
    crawl_similarity_descriptors,
    list_similarity_segments,
    search_similarity_descriptors,
)


def _make_tone(path: Path, *, sample_rate: int = 44100, frequency: float = 440.0, frames: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        payload = bytearray()
        for i in range(frames):
            sample = int(12000 * math.sin(2 * math.pi * frequency * i / sample_rate))
            payload.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(payload))
    return path


def _make_pulses(path: Path, *, sample_rate: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    regions = [
        (0.20, 0.0),
        (0.20, 440.0),
        (0.35, 0.0),
        (0.25, 660.0),
        (0.20, 0.0),
    ]
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        payload = bytearray()
        frame_offset = 0
        for duration_s, frequency in regions:
            frames = int(duration_s * sample_rate)
            for i in range(frames):
                sample = 0
                if frequency:
                    sample = int(12000 * math.sin(2 * math.pi * frequency * (frame_offset + i) / sample_rate))
                payload.extend(struct.pack("<h", sample))
            frame_offset += frames
        wav.writeframes(bytes(payload))
    return path


def test_similarity_crawl_writes_descriptors_and_skips_current_rows(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    wav = _make_tone(root / "tone.wav")
    scan_library(root, tmp_db, skip_hash=False, quiet=True)

    first = crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=tmp_path / "cache", quiet=True)

    assert first.summary.total_files == 1
    assert first.summary.analyzed == 1
    assert first.summary.skipped == 0
    assert first.summary.errors == 0
    assert first.descriptors[0].path == str(wav)
    assert first.descriptors[0].peak is not None
    assert first.descriptors[0].peak > 0
    assert first.descriptors[0].rms is not None
    assert first.descriptors[0].rms > 0
    assert first.descriptors[0].duration_bucket == "short"
    assert (tmp_path / "cache" / f"similarity_crawl_{first.run_id}.json").exists()

    conn = get_connection(tmp_db)
    row = conn.execute(
        """
        SELECT peak, rms, spectral_centroid, spectral_bandwidth, spectral_rolloff,
               spectral_flatness, segment_count, segment_method, error
        FROM audio_descriptors
        """
    ).fetchone()
    segment_count = conn.execute("SELECT COUNT(*) FROM audio_segments").fetchone()[0]
    run_count = conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0]
    conn.close()

    assert row["peak"] > 0
    assert row["rms"] > 0
    assert row["spectral_centroid"] > 0
    assert row["spectral_bandwidth"] > 0
    assert row["spectral_rolloff"] > 0
    assert row["spectral_flatness"] >= 0
    assert row["segment_count"] == 1
    assert row["segment_method"] == "rms_event_v2"
    assert segment_count == 1
    assert row["error"] is None
    assert run_count == 1

    second = crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=tmp_path / "cache", quiet=True)

    assert second.summary.total_files == 1
    assert second.summary.analyzed == 0
    assert second.summary.skipped == 1
    assert second.summary.errors == 0

    third = crawl_similarity_descriptors(
        root, db_path=tmp_db, cache_path=tmp_path / "cache", max_duration_s=0.5, quiet=True
    )

    assert third.summary.analyzed == 1
    assert third.summary.skipped == 0
    assert third.descriptors[0].max_duration_s == 0.5
    assert third.descriptors[0].analyzed_duration_s is not None
    assert 0.49 <= third.descriptors[0].analyzed_duration_s <= 0.51


def test_similarity_crawl_records_missing_file_errors(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    wav = _make_tone(root / "missing.wav")
    scan_library(root, tmp_db, skip_hash=False, quiet=True)
    wav.unlink()

    report = crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)

    assert report.summary.total_files == 1
    assert report.summary.analyzed == 1
    assert report.summary.errors == 1
    assert report.descriptors[0].error == "file not found"

    conn = get_connection(tmp_db)
    row = conn.execute("SELECT error FROM audio_descriptors").fetchone()
    conn.close()

    assert row["error"] == "file not found"


def test_similarity_crawl_respects_json_descriptor_limit(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    _make_tone(root / "one.wav")
    _make_tone(root / "two.wav")
    scan_library(root, tmp_db, skip_hash=False, quiet=True)

    report = crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=tmp_path / "cache", limit=1, quiet=True)

    assert report.summary.total_files == 2
    assert report.summary.analyzed == 2
    assert len(report.descriptors) == 1
    payload = json.loads((tmp_path / "cache" / f"similarity_crawl_{report.run_id}.json").read_text())
    assert payload["summary"]["total_files"] == 2
    assert len(payload["descriptors"]) == 1


def test_similarity_descriptors_capture_spectral_difference(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    low = _make_tone(root / "low.wav", frequency=220.0)
    high = _make_tone(root / "high.wav", frequency=1760.0)
    scan_library(root, tmp_db, skip_hash=False, quiet=True)

    crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)

    conn = get_connection(tmp_db)
    rows = conn.execute(
        """
        SELECT path, spectral_centroid, spectral_rolloff
        FROM audio_descriptors
        ORDER BY path
        """
    ).fetchall()
    conn.close()
    by_path = {row["path"]: row for row in rows}

    assert by_path[str(high)]["spectral_centroid"] > by_path[str(low)]["spectral_centroid"]
    assert by_path[str(high)]["spectral_rolloff"] > by_path[str(low)]["spectral_rolloff"]


def test_similarity_crawl_detects_multiple_event_segments(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    pulses = _make_pulses(root / "pulses.wav")
    scan_library(root, tmp_db, skip_hash=False, quiet=True)

    crawl = crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)
    report = list_similarity_segments(root, db_path=tmp_db, quiet=True)

    assert crawl.summary.segments_detected == 2
    assert report.summary.files_with_segments == 1
    assert report.summary.segments == 2
    assert [segment.path for segment in report.segments] == [str(pulses), str(pulses)]
    assert [segment.segment_index for segment in report.segments] == [0, 1]
    assert 0.15 <= report.segments[0].start_s <= 0.25
    assert 0.35 <= report.segments[0].end_s <= 0.45
    assert 0.70 <= report.segments[1].start_s <= 0.80
    assert 0.95 <= report.segments[1].end_s <= 1.05


def test_similarity_search_can_rank_cached_segments(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    pulses = _make_pulses(root / "pulses.wav")
    query = _make_tone(tmp_path / "query_660.wav", frequency=660.0)
    scan_library(root, tmp_db, skip_hash=False, quiet=True)
    crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)

    report = search_similarity_descriptors(query, db_path=tmp_db, scope="segment", limit=2, quiet=True)

    assert report.scope == "segment"
    assert report.candidates_considered == 2
    assert [result.scope for result in report.results] == ["segment", "segment"]
    assert report.results[0].path == str(pulses)
    assert report.results[0].segment_index == 1
    assert report.results[0].segment_start_s is not None
    assert report.results[0].segment_end_s is not None
    assert report.results[0].segment_method == "rms_event_v2"
    assert report.results[0].spectral_centroid is not None
    assert report.results[0].distance < report.results[1].distance


def test_similarity_search_returns_nearest_cached_descriptors(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    low = _make_tone(root / "low.wav", frequency=220.0)
    high = _make_tone(root / "high.wav", frequency=1760.0)
    query = _make_tone(tmp_path / "query.wav", frequency=220.0)
    scan_library(root, tmp_db, skip_hash=False, quiet=True)
    crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)

    report = search_similarity_descriptors(query, db_path=tmp_db, limit=2, quiet=True)

    assert report.scope == "file"
    assert report.candidates_considered == 2
    assert [result.path for result in report.results] == [str(low), str(high)]
    assert report.results[0].score > report.results[1].score
    assert report.results[0].distance < report.results[1].distance
    assert report.query_descriptor.file_id == 0
    assert report.query_descriptor.path == str(query.resolve())
    assert report.query_descriptor.spectral_centroid is not None
    assert report.results[0].spectral_centroid is not None


def test_similarity_search_requires_matching_analysis_window(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    _make_tone(root / "tone.wav")
    query = _make_tone(tmp_path / "query.wav")
    scan_library(root, tmp_db, skip_hash=False, quiet=True)
    crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, max_duration_s=0.5, quiet=True)

    default_window = search_similarity_descriptors(query, db_path=tmp_db, quiet=True)
    matching_window = search_similarity_descriptors(query, db_path=tmp_db, max_duration_s=0.5, quiet=True)

    assert default_window.candidates_considered == 0
    assert matching_window.candidates_considered == 1


def test_similarity_audit_reports_groups_and_excludes_exact_md5_pairs(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    original = _make_tone(root / "tone_a.wav", frequency=220.0)
    near = _make_tone(root / "tone_b.wav", frequency=221.0)
    exact_copy = root / "tone_copy.wav"
    exact_copy.write_bytes(original.read_bytes())
    scan_library(root, tmp_db, skip_hash=False, quiet=True)
    crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)

    report = audit_similarity_descriptors(root, db_path=tmp_db, threshold=0.95, quiet=True)

    assert report.summary.descriptors_considered == 3
    assert report.summary.exact_md5_pairs_excluded == 1
    assert report.summary.candidate_pairs == 2
    assert report.summary.candidate_groups == 1
    assert report.groups[0].file_count == 3
    assert {file.path for file in report.groups[0].files} == {str(original), str(near), str(exact_copy)}
    assert all(pair.score >= 0.95 for pair in report.groups[0].pairs)

    with_exact = audit_similarity_descriptors(root, db_path=tmp_db, threshold=0.95, exclude_exact_md5=False, quiet=True)
    assert with_exact.summary.exact_md5_pairs_excluded == 0
    assert with_exact.summary.candidate_pairs == 3


def test_similarity_audit_writes_limited_report(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    _make_tone(root / "one.wav", frequency=220.0)
    _make_tone(root / "two.wav", frequency=221.0)
    _make_tone(root / "three.wav", frequency=880.0)
    _make_tone(root / "four.wav", frequency=881.0)
    scan_library(root, tmp_db, skip_hash=False, quiet=True)
    crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)
    out = tmp_path / "reports" / "similarity_audit.json"

    report = audit_similarity_descriptors(root, db_path=tmp_db, threshold=0.95, limit=1, output_path=out, quiet=True)

    assert report.summary.candidate_groups == 2
    assert report.summary.reported_groups == 1
    payload = json.loads(out.read_text())
    assert payload["summary"]["candidate_groups"] == 2
    assert len(payload["groups"]) == 1
