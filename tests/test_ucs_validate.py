"""Tests for UCS catalog validation against indexed files."""

from __future__ import annotations

import json
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.models import UcsCatalog, UcsCatalogProvenance, UcsEntry
from wavwarden.ucs_validate import build_ucs_validation_report, write_ucs_validation_report


def _catalog(path: Path) -> None:
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://universalcategorysystem.com/",
            source_path="/tmp/_categorylist.csv",
            source_format="soundminer_csv",
            release_version="v8.2.1",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=1,
        ),
        entries=[UcsEntry(cat_short="AMB", category="AMBIENCE", subcategory="RAIN", cat_id="AMBRain")],
    )
    path.write_text(json.dumps(catalog.model_dump()), encoding="utf-8")


def _seed(tmp_db: Path, paths: list[str]) -> None:
    conn = get_connection(tmp_db)
    for raw in paths:
        path = Path(raw)
        conn.execute(
            """
            INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, scanned_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(path), path.name, path.stem, path.suffix.lower(), 100, 0.0, "2026"),
        )
    conn.commit()
    conn.close()


def test_ucs_validation_counts_catalog_matches_and_misses(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed(
        tmp_db,
        [
            str(root / "AMB_RAIN_01.wav"),
            str(root / "AMB_FAKE_01.wav"),
            str(root / "Metal Hit.wav"),
        ],
    )
    catalog_path = tmp_path / "ucs_catalog.json"
    _catalog(catalog_path)

    report = build_ucs_validation_report(tmp_db, root=root, catalog_path=catalog_path)

    assert report.catalog_path == str(catalog_path.resolve())
    assert report.catalog_release_version == "v8.2.1"
    assert report.summary.files_considered == 3
    assert report.summary.ucs_looking == 2
    assert report.summary.catalog_matches == 1
    assert report.summary.catalog_misses == 1
    assert report.summary.non_ucs == 1
    assert report.issues[0].filename == "AMB_FAKE_01.wav"
    assert report.issues[0].reason == "cat_short_subcategory_not_found"


def test_write_ucs_validation_report_round_trip(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed(tmp_db, [str(root / "AMB_FAKE_01.wav")])
    catalog_path = tmp_path / "ucs_catalog.json"
    _catalog(catalog_path)

    report = build_ucs_validation_report(tmp_db, root=root, catalog_path=catalog_path)
    out = tmp_path / "ucs_validation.json"
    write_ucs_validation_report(report, out, quiet=True)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["summary"]["catalog_misses"] == 1
    assert payload["issues"][0]["cat_short"] == "AMB"
