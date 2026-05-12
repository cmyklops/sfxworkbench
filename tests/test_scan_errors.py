"""Tests for scan-error review/quarantine plans."""

import json
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.scan_errors import apply_scan_error_plan, build_scan_error_plan, classify_scan_error


def _seed_scan_error(tmp_db: Path, path: Path, scan_error: str) -> None:
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scan_error, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(path),
            path.name,
            path.stem,
            path.suffix.lower(),
            path.stat().st_size,
            0.0,
            None,
            scan_error,
            "2026-01-01T00:00:00",
        ),
    )
    conn.commit()
    conn.close()


def test_classify_scan_error_appledouble(tmp_path: Path) -> None:
    path = tmp_path / "artifact.wav"
    path.write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 32)

    assert classify_scan_error(path, "Format not recognised.") == "appledouble"


def test_classify_scan_error_all_zero(tmp_path: Path) -> None:
    path = tmp_path / "silent_blob.wav"
    path.write_bytes(b"\x00" * 4096)

    assert classify_scan_error(path, "Format not recognised.") == "all_zero"


def test_build_scan_error_plan_marks_only_obvious_artifacts(tmp_db: Path, tmp_path: Path) -> None:
    all_zero = tmp_path / "zero.wav"
    all_zero.write_bytes(b"\x00" * 128)
    broken_riff = tmp_path / "broken.wav"
    broken_riff.write_bytes(b"RIFF\x00\x00\x00\x00WAVEbext")
    _seed_scan_error(tmp_db, all_zero, "Format not recognised.")
    _seed_scan_error(tmp_db, broken_riff, "Error in WAV file. No 'data' chunk marker.")

    plan = build_scan_error_plan(tmp_db)
    by_name = {Path(entry.path).name: entry for entry in plan.entries}

    assert by_name["zero.wav"].classification == "all_zero"
    assert by_name["zero.wav"].action == "quarantine"
    assert by_name["broken.wav"].classification == "riff_missing_data"
    assert by_name["broken.wav"].action == "review"


def test_apply_scan_error_plan_quarantines_and_updates_db(tmp_db: Path, tmp_path: Path) -> None:
    all_zero = tmp_path / "zero.wav"
    all_zero.write_bytes(b"\x00" * 128)
    broken_riff = tmp_path / "broken.wav"
    broken_riff.write_bytes(b"RIFF\x00\x00\x00\x00WAVEbext")
    _seed_scan_error(tmp_db, all_zero, "Format not recognised.")
    _seed_scan_error(tmp_db, broken_riff, "Error in WAV file. No 'data' chunk marker.")

    plan = build_scan_error_plan(tmp_db)
    plan_path = tmp_path / "scan_error_plan.json"
    plan_path.write_text(json.dumps(plan.model_dump(), indent=2))

    quarantine = tmp_path / "q"
    result = apply_scan_error_plan(plan_path, db_path=tmp_db, quarantine_dir=quarantine, dry_run=False)

    assert result.quarantined == 1
    assert not all_zero.exists()
    assert broken_riff.exists()
    assert any(path.name == "zero.wav" for path in quarantine.rglob("*"))

    conn = get_connection(tmp_db)
    paths = [row["path"] for row in conn.execute("SELECT path FROM files").fetchall()]
    conn.close()
    assert str(all_zero) not in paths
    assert str(broken_riff) in paths
