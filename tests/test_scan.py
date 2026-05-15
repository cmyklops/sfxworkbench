"""Tests for sfxworkbench.scan."""

import json
import struct
import time
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.models import AudioInfo
from sfxworkbench.scan import scan_library


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    return chunk_id + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")


def _padded_ascii(value: str, size: int) -> bytes:
    encoded = value.encode("ascii")
    return encoded + b"\x00" * (size - len(encoded))


def _write_wav_with_metadata(path: Path) -> None:
    fmt_chunk = _chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16))
    bext_payload = _padded_ascii("Ambience rain steady", 256) + b"\x00" * (602 - 256)
    bext_chunk = _chunk(b"bext", bext_payload)
    info_payload = b"INFO" + _chunk(b"IKEY", b"rain; ambience\x00")
    info_chunk = _chunk(b"LIST", info_payload)
    data_chunk = _chunk(b"data", b"\x00\x00")
    body = fmt_chunk + bext_chunk + info_chunk + data_chunk
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body)


def test_scan_indexes_audio_files(tmp_library: Path, tmp_db: Path) -> None:
    result = scan_library(tmp_library, tmp_db, skip_hash=True)
    assert result.total > 0
    assert result.scanned == result.total
    assert result.errors == 0


def test_scan_index_mode_skips_hash_audio_and_metadata(monkeypatch, tmp_library: Path, tmp_db: Path) -> None:
    def fail_read_audio_info(path: Path) -> AudioInfo:
        raise AssertionError(f"audio should not be read during index mode: {path}")

    monkeypatch.setattr("sfxworkbench.scan.audio_mod.read_audio_info", fail_read_audio_info)

    result = scan_library(tmp_library, tmp_db, mode="index")

    conn = get_connection(tmp_db)
    row = conn.execute(
        """
        SELECT md5, sample_rate, has_bext, has_ixml, metadata_sources,
               hash_scanned_at, audio_scanned_at, metadata_scanned_at
        FROM files
        WHERE filename = ?
        """,
        ("AMB_RAIN_01.wav",),
    ).fetchone()
    field_count = conn.execute("SELECT COUNT(*) FROM metadata_fields").fetchone()[0]
    conn.close()

    assert result.scanned == result.total
    assert row["md5"] is None
    assert row["sample_rate"] is None
    assert row["has_bext"] == 0
    assert row["has_ixml"] == 0
    assert row["metadata_sources"] is None
    assert row["hash_scanned_at"] is None
    assert row["audio_scanned_at"] is None
    assert row["metadata_scanned_at"] is None
    assert field_count == 0


def test_scan_index_mode_preserves_unchanged_enriched_fields(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=False)
    second = scan_library(tmp_library, tmp_db, mode="index")

    conn = get_connection(tmp_db)
    row = conn.execute(
        "SELECT md5, sample_rate, audio_scanned_at, metadata_scanned_at FROM files WHERE filename = ?",
        ("AMB_RAIN_01.wav",),
    ).fetchone()
    conn.close()

    assert second.scanned == 0
    assert row["md5"] is not None
    assert row["sample_rate"] is not None
    assert row["audio_scanned_at"] is not None
    assert row["metadata_scanned_at"] is not None


def test_scan_index_mode_marks_changed_derived_fields_stale(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=False)
    target = next(tmp_library.rglob("AMB_RAIN_01.wav"))
    new_time = time.time() + 100
    target.touch()
    import os

    os.utime(target, (new_time, new_time))

    scan_library(tmp_library, tmp_db, mode="index")

    conn = get_connection(tmp_db)
    row = conn.execute(
        """
        SELECT md5, sample_rate, metadata_sources, hash_scanned_at,
               audio_scanned_at, metadata_scanned_at
        FROM files
        WHERE filename = ?
        """,
        ("AMB_RAIN_01.wav",),
    ).fetchone()
    conn.close()

    assert row["md5"] is None
    assert row["sample_rate"] is None
    assert row["metadata_sources"] is None
    assert row["hash_scanned_at"] is None
    assert row["audio_scanned_at"] is None
    assert row["metadata_scanned_at"] is None


def test_scan_skips_junk_files(tmp_library: Path, tmp_db: Path) -> None:
    """._*, .DS_Store, _wfCache/* should never appear in the index."""
    scan_library(tmp_library, tmp_db, skip_hash=True)
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    paths = [row["path"] for row in rows]
    conn.close()

    assert not any(Path(p).name.startswith("._") for p in paths)
    assert not any(Path(p).name == ".DS_Store" for p in paths)
    assert not any("_wfCache" in Path(p).parts for p in paths)
    assert not any("__MACOSX" in Path(p).parts for p in paths)


def test_scan_is_incremental(tmp_library: Path, tmp_db: Path) -> None:
    """Re-running scan should skip unchanged files."""
    first = scan_library(tmp_library, tmp_db, skip_hash=True)
    second = scan_library(tmp_library, tmp_db, skip_hash=True)

    assert first.scanned > 0
    assert second.scanned == 0, "Nothing changed; nothing should be re-scanned"
    assert second.skipped == first.scanned


def test_scan_can_cancel_between_files(tmp_library: Path, tmp_db: Path) -> None:
    cancel = False
    events: list[tuple[str, int, int | None, str]] = []

    def progress(phase: str, completed: int, total: int | None, message: str) -> None:
        nonlocal cancel
        events.append((phase, completed, total, message))
        if phase == "scanning" and completed >= 1:
            cancel = True

    result = scan_library(
        tmp_library,
        tmp_db,
        skip_hash=True,
        quiet=True,
        progress_callback=progress,
        cancel_requested=lambda: cancel,
    )

    assert result.scanned == 1
    assert result.total > result.scanned
    assert events[-1][0] == "cancelled"


def test_scan_progress_reports_collection_and_scan_counts(tmp_library: Path, tmp_db: Path) -> None:
    events: list[tuple[str, int, int | None, str]] = []

    result = scan_library(
        tmp_library,
        tmp_db,
        skip_hash=True,
        quiet=True,
        progress_callback=lambda phase, completed, total, message: events.append(
            (phase, completed, total, message)
        ),
    )

    assert result.scanned == result.total
    assert any(
        phase == "collecting" and "Walked" in message and "audio candidate" in message
        for phase, _completed, _total, message in events
    )
    assert any(
        phase == "scanning" and "indexed" in message and "skipped" in message and "errors" in message
        for phase, _completed, _total, message in events
    )
    assert events[-1][0] == "complete"
    assert "Scan complete" in events[-1][3]


def test_scan_force_rescan(tmp_library: Path, tmp_db: Path) -> None:
    """--force re-scans even unchanged files."""
    scan_library(tmp_library, tmp_db, skip_hash=True)
    second = scan_library(tmp_library, tmp_db, skip_hash=True, force_rescan=True)
    assert second.scanned > 0
    assert second.skipped == 0


def test_scan_rescans_modified_files(tmp_library: Path, tmp_db: Path) -> None:
    """Touching a file's mtime should make it re-scan on the next pass."""
    scan_library(tmp_library, tmp_db, skip_hash=True)
    target = next(tmp_library.rglob("AMB_RAIN_01.wav"))
    new_time = time.time() + 100
    target.touch()
    import os

    os.utime(target, (new_time, new_time))

    second = scan_library(tmp_library, tmp_db, skip_hash=True)
    assert second.scanned >= 1


def test_scan_populates_fn_issues(tmp_library: Path, tmp_db: Path) -> None:
    """Filename health issues should be written to the fn_issues table."""
    scan_library(tmp_library, tmp_db, skip_hash=True)
    conn = get_connection(tmp_db)
    issues = conn.execute("SELECT issue FROM fn_issues").fetchall()
    issue_types = {row["issue"] for row in issues}
    conn.close()
    # tmp_library has bad!name.wav, which is portable but still risky.
    assert "risky_chars" in issue_types


def test_scan_ucs_detection(tmp_library: Path, tmp_db: Path) -> None:
    """UCS-named files should be flagged as is_ucs=1."""
    scan_library(tmp_library, tmp_db, skip_hash=True)
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT filename, is_ucs FROM files").fetchall()
    by_name = {row["filename"]: row["is_ucs"] for row in rows}
    conn.close()
    assert by_name.get("AMB_RAIN_01.wav") == 1
    assert by_name.get("SFX_GUNSHOT_01.wav") == 1
    assert by_name.get("BOOM.wav") == 0


def test_scan_stores_extended_metadata_flags(monkeypatch, tmp_library: Path, tmp_db: Path) -> None:
    """Optional metadata-reader flags should be persisted for export/TUI use."""

    def fake_read_audio_info(path: Path) -> AudioInfo:
        return AudioInfo(
            sample_rate=48000,
            channels=2,
            has_riff_info=path.name == "AMB_RAIN_01.wav",
            has_cue_markers=path.name == "AMB_RAIN_01.wav",
            metadata_sources=["soundfile", "wavinfo"],
        )

    monkeypatch.setattr("sfxworkbench.scan.audio_mod.read_audio_info", fake_read_audio_info)

    scan_library(tmp_library, tmp_db, skip_hash=True)
    conn = get_connection(tmp_db)
    row = conn.execute(
        "SELECT has_riff_info, has_cue_markers, metadata_sources FROM files WHERE filename = ?",
        ("AMB_RAIN_01.wav",),
    ).fetchone()
    conn.close()

    assert row["has_riff_info"] == 1
    assert row["has_cue_markers"] == 1
    assert json.loads(row["metadata_sources"]) == ["soundfile", "wavinfo"]


def test_scan_populates_normalized_metadata_fields(monkeypatch, tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Rain 01.wav"
    _write_wav_with_metadata(audio)

    def fake_read_audio_info(path: Path) -> AudioInfo:
        return AudioInfo(
            sample_rate=48000,
            channels=1,
            has_bext=path.name == "Rain 01.wav",
            has_riff_info=path.name == "Rain 01.wav",
            metadata_sources=["fixture"],
        )

    monkeypatch.setattr("sfxworkbench.scan.audio_mod.read_audio_info", fake_read_audio_info)

    scan_library(root, tmp_db, skip_hash=True)

    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT namespace, key, value, source FROM metadata_fields ORDER BY namespace, key").fetchall()
    conn.close()

    assert ("bext", "Description", "Ambience rain steady", "riff") in [
        (row["namespace"], row["key"], row["value"], row["source"]) for row in rows
    ]
    assert ("riff_info", "IKEY", "rain; ambience", "riff") in [
        (row["namespace"], row["key"], row["value"], row["source"]) for row in rows
    ]


def test_scan_md5_when_not_skipped(tmp_library: Path, tmp_db: Path) -> None:
    """MD5 should be populated when skip_hash=False."""
    scan_library(tmp_library, tmp_db, skip_hash=False)
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT md5 FROM files WHERE filename = ?", ("AMB_RAIN_01.wav",)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["md5"] is not None
    assert len(rows[0]["md5"]) == 32  # MD5 hex length


def test_scan_writes_meta(tmp_library: Path, tmp_db: Path) -> None:
    """scan_meta table should record the last scan."""
    scan_library(tmp_library, tmp_db, skip_hash=True)
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT key, value FROM scan_meta").fetchall()
    by_key = {row["key"]: row["value"] for row in rows}
    conn.close()
    assert "last_scan_root" in by_key
    assert "last_scan_at" in by_key
