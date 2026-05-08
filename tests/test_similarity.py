import json
import math
import struct
import wave
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.scan import scan_library
from wavwarden.similarity import crawl_similarity_descriptors, search_similarity_descriptors


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
    row = conn.execute("SELECT peak, rms, error FROM audio_descriptors").fetchone()
    run_count = conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0]
    conn.close()

    assert row["peak"] > 0
    assert row["rms"] > 0
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


def test_similarity_search_returns_nearest_cached_descriptors(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    low = _make_tone(root / "low.wav", frequency=220.0)
    high = _make_tone(root / "high.wav", frequency=1760.0)
    query = _make_tone(tmp_path / "query.wav", frequency=220.0)
    scan_library(root, tmp_db, skip_hash=False, quiet=True)
    crawl_similarity_descriptors(root, db_path=tmp_db, cache_path=None, quiet=True)

    report = search_similarity_descriptors(query, db_path=tmp_db, limit=2, quiet=True)

    assert report.candidates_considered == 2
    assert [result.path for result in report.results] == [str(low), str(high)]
    assert report.results[0].score > report.results[1].score
    assert report.results[0].distance < report.results[1].distance
    assert report.query_descriptor.file_id == 0
    assert report.query_descriptor.path == str(query.resolve())


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
