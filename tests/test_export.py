"""Tests for sfxworkbench.export."""

import csv
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.export import export_csv
from sfxworkbench.scan import scan_library


def test_export_empty_db_writes_empty_file(tmp_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    count = export_csv(tmp_db, out)
    assert count == 0
    assert out.exists()


def test_export_writes_csv_with_header(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True)
    out = tmp_path / "out.csv"
    count = export_csv(tmp_db, out)

    assert count > 0
    with open(out, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert "path" in header
    assert "filename" in header
    assert "is_ucs" in header
    assert "has_riff_info" in header
    assert "metadata_sources" in header
    assert "accepted_tags" in header
    assert len(rows) == count


def test_export_includes_db_only_accepted_tags(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True)
    conn = get_connection(tmp_db)
    row = conn.execute("SELECT id FROM files WHERE filename = ?", ("AMB_RAIN_01.wav",)).fetchone()
    conn.execute(
        """
        INSERT INTO accepted_tags (
            file_id, field, value, source, method, confidence, evidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (row["id"], "category", "AMB", "test", "manual", 1.0, "[]", "2026", "2026"),
    )
    conn.commit()
    conn.close()

    out = tmp_path / "out.csv"
    export_csv(tmp_db, out)

    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))

    tagged = next(row for row in rows if row["filename"] == "AMB_RAIN_01.wav")
    assert '"field": "category"' in tagged["accepted_tags"]
    assert '"value": "AMB"' in tagged["accepted_tags"]
