"""Tests for report-only metadata hygiene audits."""

import json
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.metadata_audit import build_metadata_audit_report, write_metadata_audit_report


def _insert_file(tmp_db: Path, path: Path, **overrides) -> None:
    values = {
        "path": str(path),
        "filename": path.name,
        "stem": path.stem,
        "extension": path.suffix.lower(),
        "size_bytes": 10,
        "mtime": 0.0,
        "sample_rate": 48000,
        "bit_depth": 24,
        "channels": 2,
        "duration_s": 1.0,
        "has_bext": 0,
        "has_ixml": 0,
        "has_riff_info": 0,
        "has_adm": 0,
        "has_cue_markers": 0,
        "has_sampler": 0,
        "metadata_sources": json.dumps(["soundfile"]),
        "scanned_at": "2026",
    }
    values.update(overrides)

    conn = get_connection(tmp_db)
    conn.execute(
        """
        INSERT INTO files (
            path, filename, stem, extension, size_bytes, mtime, sample_rate,
            bit_depth, channels, duration_s, has_bext, has_ixml, has_riff_info,
            has_adm, has_cue_markers, has_sampler, metadata_sources, scanned_at
        )
        VALUES (
            :path, :filename, :stem, :extension, :size_bytes, :mtime, :sample_rate,
            :bit_depth, :channels, :duration_s, :has_bext, :has_ixml, :has_riff_info,
            :has_adm, :has_cue_markers, :has_sampler, :metadata_sources, :scanned_at
        )
        """,
        values,
    )
    conn.commit()
    conn.close()


def test_metadata_audit_reports_missing_metadata_and_unusual_rates(tmp_db: Path, tmp_path: Path) -> None:
    _insert_file(tmp_db, tmp_path / "plain.wav")
    _insert_file(tmp_db, tmp_path / "tagged.wav", has_bext=1)
    _insert_file(tmp_db, tmp_path / "odd.wav", sample_rate=11025, has_ixml=1)

    report = build_metadata_audit_report(tmp_db)

    assert report.summary.total_files == 3
    assert report.summary.missing_metadata == 1
    assert report.summary.unusual_sample_rate_files == 1
    assert report.missing_metadata[0].filename == "plain.wav"
    assert report.missing_metadata[0].reasons == ["missing_bext_ixml"]
    assert report.unusual_sample_rates[0].filename == "odd.wav"
    assert report.unusual_sample_rates[0].sample_rate == 11025
    assert report.unusual_sample_rates[0].reasons == ["unusual_sample_rate"]


def test_metadata_audit_limit_controls_reported_rows(tmp_db: Path, tmp_path: Path) -> None:
    _insert_file(tmp_db, tmp_path / "a.wav")
    _insert_file(tmp_db, tmp_path / "b.wav")

    limited = build_metadata_audit_report(tmp_db, limit=1)
    unlimited = build_metadata_audit_report(tmp_db, limit=0)

    assert limited.summary.missing_metadata == 2
    assert limited.summary.reported_missing_metadata == 1
    assert len(limited.missing_metadata) == 1
    assert unlimited.summary.reported_missing_metadata == 2
    assert len(unlimited.missing_metadata) == 2


def test_write_metadata_audit_report(tmp_db: Path, tmp_path: Path) -> None:
    _insert_file(tmp_db, tmp_path / "plain.wav")
    report = build_metadata_audit_report(tmp_db)
    output = tmp_path / "metadata_report.json"

    write_metadata_audit_report(report, output, quiet=True)

    payload = json.loads(output.read_text())
    assert payload["schema_version"] == 1
    assert payload["summary"]["missing_metadata"] == 1
