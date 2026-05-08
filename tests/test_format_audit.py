"""Tests for report-only audio format consistency audits."""

import json
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.format_audit import build_format_audit_report, write_format_audit_report


def _seed_files(tmp_db: Path, files: list[dict]) -> None:
    conn = get_connection(tmp_db)
    for item in files:
        path = Path(item["path"])
        conn.execute(
            """
            INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, md5,
                sample_rate, bit_depth, channels, duration_s, scanned_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                path.name,
                path.stem,
                path.suffix.lower(),
                item.get("size", 10),
                0.0,
                item.get("md5"),
                item.get("sample_rate", 48000),
                item.get("bit_depth", 24),
                item.get("channels", 2),
                item.get("duration_s", 1.0),
                "2026",
            ),
        )
    conn.commit()
    conn.close()


def test_format_audit_reports_mixed_sample_rates(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "Metal Hit 01.wav", "sample_rate": 48000},
            {"path": folder / "Metal Hit 02.wav", "sample_rate": 44100},
            {"path": folder / "Metal Hit 03.wav", "sample_rate": 48000},
        ],
    )

    report = build_format_audit_report(root, tmp_db)

    assert report.summary.related_groups_considered == 1
    assert report.summary.inconsistent_groups == 1
    assert report.summary.sample_rate_groups == 1
    group = report.groups[0]
    assert group.action == "review_only"
    assert group.inferred_stem == "Metal Hit"
    assert group.inconsistencies[0].field == "sample_rate"
    assert group.inconsistencies[0].values == [44100, 48000]


def test_format_audit_reports_mixed_bit_depth_and_channels(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambiences"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "Forest L.wav", "bit_depth": 24, "channels": 1},
            {"path": folder / "Forest R.wav", "bit_depth": 16, "channels": 2},
        ],
    )

    report = build_format_audit_report(root, tmp_db)

    fields = {issue.field for issue in report.groups[0].inconsistencies}
    assert fields == {"bit_depth", "channels"}
    assert report.summary.bit_depth_groups == 1
    assert report.summary.channel_layout_groups == 1


def test_format_audit_ignores_consistent_related_groups(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "Metal Hit 01.wav"},
            {"path": folder / "Metal Hit 02.wav"},
        ],
    )

    report = build_format_audit_report(root, tmp_db)

    assert report.summary.related_groups_considered == 1
    assert report.summary.inconsistent_groups == 0
    assert report.groups == []


def test_format_audit_limit_controls_reported_groups(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "A" / "Alpha 01.wav", "sample_rate": 44100},
            {"path": root / "A" / "Alpha 02.wav", "sample_rate": 48000},
            {"path": root / "B" / "Beta 01.wav", "sample_rate": 44100},
            {"path": root / "B" / "Beta 02.wav", "sample_rate": 48000},
        ],
    )

    limited = build_format_audit_report(root, tmp_db, limit=1)
    unlimited = build_format_audit_report(root, tmp_db, limit=0)

    assert limited.summary.inconsistent_groups == 2
    assert limited.summary.reported_groups == 1
    assert len(limited.groups) == 1
    assert unlimited.summary.reported_groups == 2
    assert len(unlimited.groups) == 2


def test_write_format_audit_report(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    report = build_format_audit_report(root, tmp_db)
    out = tmp_path / "reports" / "format.json"

    write_format_audit_report(report, out, quiet=True)

    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["summary"]["inconsistent_groups"] == 0
