"""Tests for per-file metadata view."""

from __future__ import annotations

import json
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.metadata_view import build_metadata_view_report
from sfxworkbench.models import UcsCatalog, UcsCatalogProvenance, UcsEntry


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
        entries=[UcsEntry(cat_short="FIRE", category="FIRE", subcategory="BURST", cat_id="FireBurst")],
    )
    path.write_text(json.dumps(catalog.model_dump()), encoding="utf-8")


def _seed_file(tmp_db: Path, path: Path) -> None:
    conn = get_connection(tmp_db)
    conn.execute(
        """
        INSERT INTO files (
            path, filename, stem, extension, size_bytes, mtime, md5,
            sample_rate, bit_depth, channels, duration_s, subtype,
            has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
            has_sampler, metadata_sources, is_ucs, scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path),
            path.name,
            path.stem,
            path.suffix.lower(),
            123,
            0.0,
            "abc",
            48000,
            24,
            2,
            1.25,
            "PCM_24",
            1,
            0,
            1,
            0,
            0,
            0,
            json.dumps(["soundfile", "wavinfo"]),
            1,
            "2026",
        ),
    )
    conn.execute(
        """
        INSERT INTO accepted_tags (
            file_id, field, value, source, method, confidence, evidence,
            created_at, updated_at
        )
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ucs_category",
            "FIRE",
            "ucs_catalog",
            "ucs_catalog_match",
            0.95,
            json.dumps(["FIRE_BURST_SmallBurst_01"]),
            "2026",
            "2026",
        ),
    )
    conn.execute(
        """
        INSERT INTO metadata_fields (
            file_id, namespace, key, value, source, updated_at
        )
        VALUES (1, ?, ?, ?, ?, ?)
        """,
        ("bext", "Description", "Small fire burst", "riff", "2026"),
    )
    conn.commit()
    conn.close()


def test_metadata_view_reports_indexed_metadata_tags_and_ucs_catalog(tmp_path: Path, tmp_db: Path) -> None:
    audio = tmp_path / "library" / "FIRE_BURST_SmallBurst_01.wav"
    audio.parent.mkdir()
    _seed_file(tmp_db, audio)
    catalog_path = tmp_path / "ucs_catalog.json"
    _catalog(catalog_path)

    report = build_metadata_view_report("SmallBurst", db_path=tmp_db, catalog_path=catalog_path)

    assert report.match_count == 1
    viewed = report.files[0]
    assert viewed.filename == "FIRE_BURST_SmallBurst_01.wav"
    assert viewed.sample_rate == 48000
    assert viewed.has_bext is True
    assert viewed.has_riff_info is True
    assert viewed.metadata_sources == ["soundfile", "wavinfo"]
    assert viewed.embedded_fields[0].namespace == "bext"
    assert viewed.embedded_fields[0].key == "Description"
    assert viewed.embedded_fields[0].value == "Small fire burst"
    assert viewed.ucs is not None
    assert viewed.ucs.catalog_match is True
    assert viewed.ucs.catalog_cat_id == "FireBurst"
    assert viewed.accepted_tags[0].field == "ucs_category"


def test_metadata_view_limit_must_be_positive(tmp_db: Path) -> None:
    try:
        build_metadata_view_report("anything", db_path=tmp_db, limit=0)
    except ValueError as e:
        assert "--limit must be greater than 0" in str(e)
    else:
        raise AssertionError("expected ValueError")
