"""Tests for wavwarden.export."""

import csv
from pathlib import Path

from wavwarden.export import export_csv
from wavwarden.scan import scan_library


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
    assert len(rows) == count
