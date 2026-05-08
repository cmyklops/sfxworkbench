"""Tests for wavwarden.scan."""

import json
import time
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.models import AudioInfo
from wavwarden.scan import scan_library


def test_scan_indexes_audio_files(tmp_library: Path, tmp_db: Path) -> None:
    result = scan_library(tmp_library, tmp_db, skip_hash=True)
    assert result.total > 0
    assert result.scanned == result.total
    assert result.errors == 0


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
    # tmp_library has bad:name.wav (illegal_chars) and an NFD-encoded filename
    assert "illegal_chars" in issue_types
    assert "unicode_normalization" in issue_types


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

    monkeypatch.setattr("wavwarden.scan.audio_mod.read_audio_info", fake_read_audio_info)

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
