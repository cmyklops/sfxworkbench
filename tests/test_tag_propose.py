"""Tests for report-only evidence-fusion tag proposals."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.models import UcsCatalog, UcsCatalogProvenance, UcsEntry
from wavwarden.tag_propose import build_tag_proposal_report


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


def _padded_ascii(value: str, size: int) -> bytes:
    encoded = value.encode("ascii")
    return encoded + b"\x00" * (size - len(encoded))


def _write_wav_with_bext_description(path: Path, description: str) -> None:
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16)
    bext_payload = _padded_ascii(description, 256) + b"\x00" * (602 - 256)
    bext_chunk = b"bext" + struct.pack("<I", len(bext_payload)) + bext_payload
    data_chunk = b"data" + struct.pack("<I", 2) + b"\x00\x00"
    body = fmt_chunk + bext_chunk + data_chunk
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body)


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
            path.stat().st_size,
            path.stat().st_mtime,
            "abc123",
            48000,
            24,
            2,
            1.0,
            "PCM_24",
            1,
            0,
            0,
            0,
            0,
            0,
            json.dumps(["fixture"]),
            0,
            "2026",
        ),
    )
    conn.commit()
    conn.close()


def test_tag_propose_uses_embedded_bext_description_as_evidence(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Rain 01.wav"
    _write_wav_with_bext_description(audio, "Ambience rain steady shower")
    _seed_file(tmp_db, audio)
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(catalog)

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog, min_confidence=0.6)

    assert report.summary.files_considered == 1
    assert report.summary.files_with_proposals == 1
    assert report.summary.total_proposals == 1
    proposal = report.entries[0].proposals[0]
    assert proposal.category == "AMBIENCE"
    assert proposal.subcategory == "RAIN"
    assert proposal.strength == "review"
    assert proposal.confidence == 0.68
    evidence = {item.source: item.value for item in proposal.evidence}
    assert evidence["filename"] == "rain"
    assert evidence["embedded_metadata"] == "ambience, rain"
