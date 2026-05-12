"""Tests for report-only evidence-fusion tag proposals."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.models import UcsCatalog, UcsCatalogProvenance, UcsEntry
from sfxworkbench.tag_propose import build_tag_proposal_report


def _catalog(path: Path, entries: list[UcsEntry] | None = None) -> None:
    catalog_entries = entries or [UcsEntry(cat_short="AMB", category="AMBIENCE", subcategory="RAIN", cat_id="AMBRain")]
    catalog = UcsCatalog(
        tool_version="test",
        provenance=UcsCatalogProvenance(
            source_url="https://universalcategorysystem.com/",
            source_path="/tmp/_categorylist.csv",
            source_format="soundminer_csv",
            release_version="v8.2.1",
            imported_at="2026-01-01T00:00:00+00:00",
            attribution="test",
            entry_count=len(catalog_entries),
        ),
        entries=catalog_entries,
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


def test_tag_propose_embedded_metadata_opens_when_category_and_subcategory_agree(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Take 01.wav"
    _write_wav_with_bext_description(audio, "Ambience rain steady shower")
    _seed_file(tmp_db, audio)
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(catalog)

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog, min_confidence=0.6)

    assert report.summary.files_with_proposals == 1
    proposal = report.entries[0].proposals[0]
    assert proposal.category == "AMBIENCE"
    assert proposal.subcategory == "RAIN"
    evidence = {item.source: item.value for item in proposal.evidence}
    assert evidence["embedded_metadata"] == "ambience, rain"


def test_tag_propose_uses_indexed_metadata_fields_as_evidence(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Take 01.wav"
    audio.write_bytes(b"placeholder")
    _seed_file(tmp_db, audio)
    conn = get_connection(tmp_db)
    conn.execute(
        """
        INSERT INTO metadata_fields (
            file_id, namespace, key, value, source, updated_at
        )
        VALUES (1, ?, ?, ?, ?, ?)
        """,
        ("bext", "Description", "Ambience rain steady shower", "riff", "2026"),
    )
    conn.commit()
    conn.close()
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(catalog)

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog, min_confidence=0.6)

    assert report.summary.files_with_proposals == 1
    proposal = report.entries[0].proposals[0]
    evidence = {item.source: item.value for item in proposal.evidence}
    assert evidence["embedded_metadata"] == "ambience, rain"


def test_tag_propose_includes_similarity_descriptor_as_review_support(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Rain 01.wav"
    _write_wav_with_bext_description(audio, "Ambience rain steady shower")
    _seed_file(tmp_db, audio)
    conn = get_connection(tmp_db)
    conn.execute(
        """
        INSERT INTO audio_descriptors (
            file_id, backend, backend_version, parameters_hash, path, size_bytes,
            mtime, md5, max_duration_s, analyzed_duration_s, peak, rms,
            spectral_centroid, spectral_rolloff, transient_density,
            segment_count, segment_method, duration_bucket, generated_at
        )
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "deterministic_v1",
            "1.1",
            "abc123",
            str(audio),
            audio.stat().st_size,
            audio.stat().st_mtime,
            "abc123",
            30.0,
            1.0,
            0.8,
            0.2,
            440.0,
            1200.0,
            0.5,
            2,
            "rms_event_v2",
            "short",
            "2026",
        ),
    )
    conn.commit()
    conn.close()
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(catalog)

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog, min_confidence=0.6)

    evidence = {item.source: item for item in report.entries[0].proposals[0].evidence}
    assert "similarity_descriptor" in evidence
    assert "duration_bucket=short" in evidence["similarity_descriptor"].value
    assert evidence["similarity_descriptor"].detail.endswith("not semantic proof")


def test_tag_propose_embedded_metadata_does_not_open_noisy_subcategory_terms(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Metal Tonal 01.wav"
    _write_wav_with_bext_description(audio, "metal tonal texture")
    _seed_file(tmp_db, audio)
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(
        catalog,
        entries=[
            UcsEntry(cat_short="MAT", category="MATERIALS", subcategory="METAL", cat_id="MATMetal"),
            UcsEntry(cat_short="MUSC", category="MUSICAL", subcategory="TONAL", cat_id="MUSCTonal"),
        ],
    )

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog, min_confidence=0.6)

    assert report.summary.files_considered == 1
    assert report.summary.files_with_proposals == 0
    assert report.summary.total_proposals == 0


def test_tag_propose_ambiguous_path_terms_need_category_context(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Cinematic Metal Impacts"
    folder.mkdir(parents=True)
    audio = folder / "Impact 01.wav"
    _write_wav_with_bext_description(audio, "metal clang")
    _seed_file(tmp_db, audio)
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(
        catalog,
        entries=[
            UcsEntry(cat_short="DOOR", category="DOORS", subcategory="METAL", cat_id="DOORMetl"),
            UcsEntry(cat_short="DRWR", category="DRAWERS", subcategory="METAL", cat_id="DRWRMetl"),
            UcsEntry(cat_short="RAIN", category="RAIN", subcategory="METAL", cat_id="RAINMetl"),
            UcsEntry(cat_short="WNDW", category="WINDOWS", subcategory="METAL", cat_id="WNDWMetl"),
        ],
    )

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog, min_confidence=0.6)

    assert report.summary.files_considered == 1
    assert report.summary.files_with_proposals == 0
    assert report.summary.total_proposals == 0


def test_tag_propose_broad_path_tokens_do_not_open_without_category_context(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Room Walla Sea Loop"
    folder.mkdir(parents=True)
    audio = folder / "Take 01.wav"
    _write_wav_with_bext_description(audio, "neutral ambience")
    _seed_file(tmp_db, audio)
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(
        catalog,
        entries=[
            UcsEntry(cat_short="AMB", category="AMBIENCE", subcategory="ROOM TONE", cat_id="AMBRoom"),
            UcsEntry(cat_short="HUMN", category="HUMAN", subcategory="WALLA", cat_id="HUMNWalla"),
            UcsEntry(cat_short="WATR", category="WATER", subcategory="SEA", cat_id="WATRSea"),
            UcsEntry(cat_short="MUSC", category="MUSICAL", subcategory="LOOP", cat_id="MUSCLoop"),
        ],
    )

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog)

    assert report.summary.files_considered == 1
    assert report.summary.files_with_proposals == 0
    assert report.summary.total_proposals == 0
    blocked = {(item["source"], item["token"]): item for item in report.summary.top_blocked_tokens}
    assert blocked[("path", "room")]["blocked_candidates"] == 1
    assert blocked[("path", "walla")]["blocked_candidates"] == 1
    assert blocked[("path", "sea")]["blocked_candidates"] == 1
    assert blocked[("path", "loop")]["blocked_candidates"] == 1


def test_tag_propose_broad_path_tokens_can_open_with_category_context(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "Ambience Room Tone"
    folder.mkdir(parents=True)
    audio = folder / "Take 01.wav"
    _write_wav_with_bext_description(audio, "neutral ambience")
    _seed_file(tmp_db, audio)
    catalog = tmp_path / "ucs_catalog.json"
    _catalog(
        catalog,
        entries=[UcsEntry(cat_short="AMB", category="AMBIENCE", subcategory="ROOM TONE", cat_id="AMBRoom")],
    )

    report = build_tag_proposal_report(root, db_path=tmp_db, catalog_path=catalog, min_confidence=0.6)

    assert report.summary.files_with_proposals == 1
    proposal = report.entries[0].proposals[0]
    assert proposal.category == "AMBIENCE"
    assert proposal.subcategory == "ROOM TONE"
    assert proposal.strength == "strong"
    opened = {(item["source"], item["token"]): item for item in report.summary.top_opening_tokens}
    assert opened[("path", "room")]["catalog_matches"] == 1
    assert opened[("path", "room")]["opened_candidates"] == 1
