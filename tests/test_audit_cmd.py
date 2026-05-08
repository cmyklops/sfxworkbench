"""Tests for wavwarden.audit_cmd."""

from pathlib import Path

from wavwarden.audit_cmd import run_audit
from wavwarden.db import get_connection
from wavwarden.scan import scan_library


def _seed_simple(tmp_db: Path, rows: list[dict]) -> None:
    conn = get_connection(tmp_db)
    for r in rows:
        conn.execute(
            """INSERT INTO files
                 (path, filename, stem, extension, size_bytes, mtime,
                  sample_rate, bit_depth, has_bext, has_ixml, is_ucs,
                  scan_error, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["path"],
                Path(r["path"]).name,
                Path(r["path"]).stem,
                Path(r["path"]).suffix,
                1024,
                0.0,
                r.get("sample_rate"),
                r.get("bit_depth"),
                r.get("has_bext", 0),
                r.get("has_ixml", 0),
                r.get("is_ucs", 0),
                r.get("scan_error"),
                "2026-01-01T00:00:00",
            ),
        )
    conn.commit()
    conn.close()


def test_audit_empty_db(tmp_db: Path) -> None:
    result = run_audit(tmp_db)
    assert result.total_files == 0
    assert result.scan_errors == 0
    assert result.fn_issues_total == 0


def test_audit_counts_scan_errors(tmp_db: Path) -> None:
    _seed_simple(
        tmp_db,
        [
            {"path": "/a.wav", "scan_error": "could not read"},
            {"path": "/b.wav"},
        ],
    )
    result = run_audit(tmp_db)
    assert result.total_files == 2
    assert result.scan_errors == 1
    assert len(result.errors) == 1


def test_audit_metadata_counts(tmp_db: Path) -> None:
    _seed_simple(
        tmp_db,
        [
            {"path": "/a.wav", "has_bext": 1, "has_ixml": 0},
            {"path": "/b.wav", "has_bext": 0, "has_ixml": 1},
            {"path": "/c.wav", "has_bext": 0, "has_ixml": 0},
        ],
    )
    result = run_audit(tmp_db)
    assert result.has_bext == 1
    assert result.has_ixml == 1
    assert result.missing_metadata == 1


def test_audit_ucs_count(tmp_db: Path) -> None:
    _seed_simple(
        tmp_db,
        [
            {"path": "/AMB_RAIN.wav", "is_ucs": 1},
            {"path": "/random.wav", "is_ucs": 0},
        ],
    )
    result = run_audit(tmp_db)
    assert result.ucs_named == 1


def test_audit_unusual_sample_rates(tmp_db: Path) -> None:
    _seed_simple(
        tmp_db,
        [
            {"path": "/a.wav", "sample_rate": 48000},
            {"path": "/b.wav", "sample_rate": 11025},  # unusual
            {"path": "/c.wav", "sample_rate": 96000},
        ],
    )
    result = run_audit(tmp_db)
    rates = [u["sample_rate"] for u in result.unusual_sample_rates]
    assert 11025 in rates
    assert 48000 not in rates


def test_audit_via_real_scan(tmp_library: Path, tmp_db: Path) -> None:
    """End-to-end: scan a real fixture, then audit the index."""
    scan_library(tmp_library, tmp_db, skip_hash=True)
    result = run_audit(tmp_db)
    assert result.total_files > 0
    assert result.fn_issues_total > 0  # tmp_library has illegal-char and NFD names
