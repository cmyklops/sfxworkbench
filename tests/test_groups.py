"""Tests for related sound group reports."""

import json
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.groups import audit_related_groups, write_related_groups_report


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


def test_groups_audit_finds_numbered_sequences(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Impacts"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "Metal Hit 01.wav", "md5": "A"},
            {"path": folder / "Metal Hit 02.wav", "md5": "B"},
            {"path": folder / "Metal Hit 03.wav", "md5": "C"},
            {"path": folder / "Metal Hit 10.wav", "md5": "E"},
            {"path": folder / "Wood Hit 01.wav", "md5": "D"},
        ],
    )

    report = audit_related_groups(root, tmp_db)

    assert report.summary.candidate_groups == 1
    group = report.groups[0]
    assert group.reason == "numbered_sequence"
    assert group.inferred_stem == "Metal Hit"
    assert group.confidence == "high"
    assert group.file_count == 4
    assert group.markers == ["01", "02", "03", "10"]


def test_groups_audit_finds_channel_sets(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambiences"
    folder.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": folder / "Forest L.wav", "channels": 1},
            {"path": folder / "Forest R.wav", "channels": 1},
        ],
    )

    report = audit_related_groups(root, tmp_db)

    assert report.summary.channel_set_groups == 1
    group = report.groups[0]
    assert group.reason == "channel_set"
    assert group.confidence == "high"
    assert group.markers == ["L", "R"]


def test_groups_audit_reports_mixed_formats_and_filters_root(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "Cars" / "Car 01.wav", "sample_rate": 44100},
            {"path": root / "Cars" / "Car 02.wav", "sample_rate": 48000},
            {"path": other / "Cars" / "Car 03.wav", "sample_rate": 96000},
        ],
    )

    report = audit_related_groups(root, tmp_db)

    assert report.summary.indexed_files_considered == 2
    assert report.summary.candidate_groups == 1
    assert report.summary.mixed_format_groups == 1
    assert report.groups[0].sample_rates == [44100, 48000]


def test_groups_audit_limit_controls_reported_groups(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "A" / "Alpha 01.wav"},
            {"path": root / "A" / "Alpha 02.wav"},
            {"path": root / "B" / "Beta 01.wav"},
            {"path": root / "B" / "Beta 02.wav"},
        ],
    )

    limited = audit_related_groups(root, tmp_db, limit=1)
    unlimited = audit_related_groups(root, tmp_db, limit=0)

    assert limited.summary.candidate_groups == 2
    assert limited.summary.reported_groups == 1
    assert len(limited.groups) == 1
    assert unlimited.summary.reported_groups == 2
    assert len(unlimited.groups) == 2


def test_write_related_groups_report(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    report = audit_related_groups(root, tmp_db)
    out = tmp_path / "reports" / "groups.json"

    write_related_groups_report(report, out, quiet=True)

    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["summary"]["candidate_groups"] == 0
