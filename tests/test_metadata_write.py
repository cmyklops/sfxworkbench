"""Tests for dry-run embedded metadata write plans."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from sfxworkbench import metadata_backends, metadata_write
from sfxworkbench.db import get_connection
from sfxworkbench.metadata_write import (
    FIXTURE_MANIFEST_NAME,
    apply_metadata_write_plan,
    build_metadata_write_fixture_bundle,
    build_metadata_write_plan,
    compare_metadata_write_fixture_readback,
    preview_metadata_write_plan,
    read_bext_core_fields,
    read_riff_info_fields,
    review_metadata_write_plan,
    undo_metadata_write_apply_log,
    write_metadata_write_plan,
)


def _fake_bwfmetaedit(tmp_path: Path) -> Path:
    if sys.platform == "win32":
        executable = tmp_path / "bwfmetaedit.cmd"
        executable.write_text("@echo off\necho BWF MetaEdit 24.04\n", encoding="utf-8")
        return executable
    executable = tmp_path / "bwfmetaedit"
    executable.write_text("#!/bin/sh\necho 'BWF MetaEdit 24.04'\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def _md5(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def _padded_ascii(value: str, size: int) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > size:
        raise ValueError(value)
    return encoded + b"\x00" * (size - len(encoded))


def _write_wav_with_bext(path: Path, *, description: str, originator: str = "", originator_reference: str = "") -> None:
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16)
    bext_payload = (
        _padded_ascii(description, 256)
        + _padded_ascii(originator, 32)
        + _padded_ascii(originator_reference, 32)
        + b"\x00" * (602 - 320)
    )
    bext_chunk = b"bext" + struct.pack("<I", len(bext_payload)) + bext_payload
    data_chunk = b"data" + struct.pack("<I", 2) + b"\x00\x00"
    body = fmt_chunk + bext_chunk + data_chunk
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body)


def _write_wav_without_bext(path: Path) -> None:
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16)
    data_chunk = b"data" + struct.pack("<I", 2) + b"\x00\x00"
    body = fmt_chunk + data_chunk
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body)


def _write_wav_with_info(path: Path, *, info: dict[str, str], description: str = "") -> None:
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16)
    chunks = [fmt_chunk]
    if description:
        bext_payload = _padded_ascii(description, 256) + b"\x00" * (602 - 256)
        chunks.append(b"bext" + struct.pack("<I", len(bext_payload)) + bext_payload)
    info_payload = b"INFO"
    for key, value in info.items():
        encoded = value.encode("utf-8") + b"\x00"
        info_payload += key.encode("ascii") + struct.pack("<I", len(encoded)) + encoded
        if len(encoded) % 2:
            info_payload += b"\x00"
    chunks.append(b"LIST" + struct.pack("<I", len(info_payload)) + info_payload)
    data_chunk = b"data" + struct.pack("<I", 2) + b"\x00\x00"
    body = b"".join(chunks) + data_chunk
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body)


def _seed_file(tmp_db: Path, path: Path) -> None:
    file_id = _seed_indexed_file(tmp_db, path)
    conn = get_connection(tmp_db)
    conn.execute(
        """
        INSERT INTO accepted_tags (
            file_id, field, value, source, method, confidence, evidence,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            "description",
            "Metal Hit",
            "test",
            "manual",
            0.95,
            json.dumps(["fixture"]),
            "2026",
            "2026",
        ),
    )
    conn.execute(
        """
        INSERT INTO accepted_tags (
            file_id, field, value, source, method, confidence, evidence,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            "category",
            "SFX",
            "test",
            "manual",
            0.95,
            json.dumps(["fixture"]),
            "2026",
            "2026",
        ),
    )
    conn.commit()
    conn.close()


def _seed_indexed_file(tmp_db: Path, path: Path) -> int:
    conn = get_connection(tmp_db)
    cursor = conn.execute(
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
            path.stat().st_size,
            path.stat().st_mtime,
            _md5(path),
            48000,
            24,
            2,
            1.0,
            "2026",
        ),
    )
    file_id = int(cursor.lastrowid)
    conn.commit()
    conn.close()
    return file_id


def _write_real_tagged_audio_fixture(path: Path) -> None:
    sf = pytest.importorskip("soundfile")
    import numpy as np

    samples = np.zeros(2400, dtype="float32")
    extension = path.suffix.lower()
    if extension == ".flac":
        sf.write(path, samples, 24000, format="FLAC")
    elif extension == ".ogg":
        sf.write(path, samples, 24000, format="OGG", subtype="VORBIS")
    elif extension == ".opus":
        sf.write(path, samples, 24000, format="OGG", subtype="OPUS")
    elif extension in {".aif", ".aiff"}:
        sf.write(path, samples, 24000, format="AIFF", subtype="PCM_16")
    elif extension == ".mp3":
        sf.write(path, samples, 24000, format="MP3")
    elif extension == ".m4a":
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required to create a tiny M4A fixture")
        wav_path = path.with_suffix(".wav")
        sf.write(wav_path, samples, 24000, format="WAV")
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg could not create M4A fixture: {result.stderr.strip()}")
    else:
        raise ValueError(f"unsupported fixture extension: {extension}")


def _seed_keyword_tags(tmp_db: Path, values: list[str], *, file_id: int = 1) -> None:
    conn = get_connection(tmp_db)
    for value in values:
        conn.execute(
            """
            INSERT INTO accepted_tags (
                file_id, field, value, source, method, confidence, evidence,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                "keyword",
                value,
                "synonym",
                "controlled_synonym_map",
                0.62,
                json.dumps(["fixture"]),
                "2026",
                "2026",
            ),
        )
    conn.commit()
    conn.close()


def _seed_tag(tmp_db: Path, field: str, value: str, *, source: str = "test", file_id: int = 1) -> None:
    conn = get_connection(tmp_db)
    conn.execute(
        """
        INSERT INTO accepted_tags (
            file_id, field, value, source, method, confidence, evidence,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            field,
            value,
            source,
            "manual",
            0.95,
            json.dumps(["fixture"]),
            "2026",
            "2026",
        ),
    )
    conn.commit()
    conn.close()


def test_metadata_write_plan_maps_supported_and_unsupported_tags(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))

    assert plan.dry_run_only is True
    assert plan.backend.available is True
    assert plan.backend.version == "BWF MetaEdit 24.04"
    assert plan.summary.candidate_entries == 2
    assert plan.summary.supported_entries == 1
    assert plan.summary.unsupported_entries == 1
    by_field = {entry.field: entry for entry in plan.entries}
    assert by_field["description"].target_namespace == "bext"
    assert by_field["description"].target_key == "Description"
    assert by_field["description"].action == "write_bext"
    assert by_field["description"].supported is True
    assert by_field["category"].action == "unsupported_field"
    assert by_field["category"].supported is False


def test_metadata_write_plan_blocks_conflicting_single_value_targets(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)
    _seed_tag(tmp_db, "description", "Different Metal Hit", source="second_review")

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))

    description_entries = [entry for entry in plan.entries if entry.field == "description"]
    assert len(description_entries) == 2
    assert {entry.action for entry in description_entries} == {"conflict"}
    assert {entry.supported for entry in description_entries} == {False}
    assert plan.summary.conflict_entries == 2
    assert plan.summary.supported_entries == 0
    assert plan.summary.unsupported_entries == 3
    assert plan.errors == [
        {
            "path": str(audio),
            "backend": "bwfmetaedit",
            "target_namespace": "bext",
            "target_key": "Description",
            "entry_ids": [2, 3],
            "values": ["Different Metal Hit", "Metal Hit"],
            "error": "conflicting accepted tags for single-value metadata target",
        }
    ]

    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.would_write == 0
    assert preview.skipped == 3
    assert preview.commands == []
    assert preview.errors == plan.errors


def test_metadata_write_plan_skips_existing_bwf_values(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    _write_wav_with_bext(audio, description="Existing Vendor Description")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))

    by_field = {entry.field: entry for entry in plan.entries}
    assert plan.summary.candidate_entries == 2
    assert plan.summary.supported_entries == 0
    assert plan.summary.skip_existing_entries == 1
    assert by_field["description"].target_key == "Description"
    assert by_field["description"].action == "skip_existing"
    assert by_field["description"].supported is False
    assert by_field["description"].existing_value == "Existing Vendor Description"

    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.would_write == 0
    assert preview.skipped == 2
    assert preview.commands == []
    assert preview.errors == []


def test_metadata_write_plan_can_explicitly_replace_existing_bwf_values(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    _write_wav_with_bext(audio, description="Existing Vendor Description")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(
        tmp_db,
        root=root,
        backend="bwfmetaedit",
        bwfmetaedit=_fake_bwfmetaedit(tmp_path),
        replace_existing=True,
    )

    by_field = {entry.field: entry for entry in plan.entries}
    assert plan.replace_existing is True
    assert plan.summary.supported_entries == 1
    assert plan.summary.skip_existing_entries == 0
    assert plan.summary.replace_entries == 1
    assert by_field["description"].action == "replace_bext"
    assert by_field["description"].supported is True
    assert by_field["description"].existing_value == "Existing Vendor Description"

    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.would_write == 1
    assert preview.skipped == 1
    assert len(preview.commands) == 1
    command = preview.commands[0]
    assert command.allow_overwrite is True
    assert "--reject-overwrite" not in command.command
    assert command.fields == {"Description": "Metal Hit"}
    assert command.command == [
        str(tmp_path / "bwfmetaedit"),
        "--simulate",
        "--specialchars",
        "--Description=Metal Hit",
        str(audio),
    ]


def test_metadata_write_review_and_preview_is_dry_run(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review = review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    assert review.approved_entries == 2

    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.dry_run is True
    assert preview.planned == 2
    assert preview.would_write == 1
    assert preview.skipped == 1
    assert preview.errors == []
    assert len(preview.commands) == 1
    command = preview.commands[0]
    assert command.file_id == 1
    assert command.path == str(audio)
    assert command.fields == {"Description": "Metal Hit"}
    assert command.command == [
        str(tmp_path / "bwfmetaedit"),
        "--simulate",
        "--reject-overwrite",
        "--specialchars",
        "--Description=Metal Hit",
        str(audio),
    ]


def test_metadata_write_bwfmetaedit_maps_keywords_to_riff_info_ikey(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Car Crash 01.wav"
    _write_wav_without_bext(audio)
    _seed_file(tmp_db, audio)
    _seed_keyword_tags(tmp_db, ["vehicle impact", "auto collision", "wreck"])

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))

    keyword_entries = [entry for entry in plan.entries if entry.field == "keyword"]
    assert len(keyword_entries) == 3
    assert {entry.target_namespace for entry in keyword_entries} == {"riff_info"}
    assert {entry.target_key for entry in keyword_entries} == {"IKEY"}
    assert {entry.action for entry in keyword_entries} == {"write_riff_info"}
    assert plan.summary.conflict_entries == 0

    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.errors == []
    assert len(preview.commands) == 1
    command = preview.commands[0]
    assert command.fields == {
        "Description": "Metal Hit",
        "IKEY": ["auto collision", "vehicle impact", "wreck"],
    }
    assert command.command == [
        str(tmp_path / "bwfmetaedit"),
        "--simulate",
        "--reject-overwrite",
        "--specialchars",
        "--Description=Metal Hit",
        "--IKEY=auto collision; vehicle impact; wreck",
        str(audio),
    ]


def test_metadata_write_auto_routes_standard_tagged_formats_to_mutagen(
    tmp_path: Path, tmp_db: Path, monkeypatch
) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))

    assert plan.backend.name == "auto"
    assert {backend.name for backend in plan.backends} == {"bwfmetaedit", "mutagen"}
    assert plan.summary.candidate_entries == 2
    assert plan.summary.supported_entries == 2
    by_field = {entry.field: entry for entry in plan.entries}
    assert by_field["description"].backend == "mutagen"
    assert by_field["description"].target_namespace == "tag"
    assert by_field["description"].target_key == "description"
    assert by_field["description"].action == "write_tag"
    assert by_field["category"].backend == "mutagen"
    assert by_field["category"].target_key == "genre"

    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.would_write == 2
    assert preview.errors == []
    assert len(preview.commands) == 1
    assert preview.commands[0].fields == {"description": "Metal Hit", "genre": "SFX"}
    assert preview.commands[0].command == [
        "internal:mutagen",
        "--simulate",
        "--set=description=Metal Hit",
        "--set=genre=SFX",
        str(audio),
    ]


def test_metadata_write_mutagen_support_is_container_specific(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    root = tmp_path / "library"
    root.mkdir()
    fields = [
        "description",
        "originator",
        "originator_reference",
        "category",
        "subcategory",
        "ucs_category",
        "ucs_subcategory",
        "take_number",
        "channel_position",
        "keyword",
    ]
    expected_supported = {
        ".flac": set(fields),
        ".ogg": set(fields),
        ".opus": set(fields),
        ".mp3": {"originator", "originator_reference", "category"},
        ".m4a": {"description", "category"},
        ".aif": set(),
        ".aiff": set(),
    }

    for extension in expected_supported:
        audio = root / f"fixture{extension}"
        audio.write_bytes(b"not really audio")
        file_id = _seed_indexed_file(tmp_db, audio)
        for field in fields:
            _seed_tag(tmp_db, field, f"{field} value", file_id=file_id)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="mutagen", bwfmetaedit=_fake_bwfmetaedit(tmp_path))

    by_extension: dict[str, dict[str, str]] = {}
    for entry in plan.entries:
        by_extension.setdefault(Path(entry.path).suffix.lower(), {})[entry.field] = entry.action

    for extension, supported_fields in expected_supported.items():
        actions = by_extension[extension]
        assert {field for field, action in actions.items() if action == "write_tag"} == supported_fields
        assert {field for field, action in actions.items() if action == "unsupported_field"} == set(
            fields
        ) - supported_fields


def test_metadata_write_plan_skips_and_replaces_existing_mutagen_values(tmp_path: Path, tmp_db: Path) -> None:
    pytest.importorskip("mutagen")
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    _write_real_tagged_audio_fixture(audio)
    metadata_write.write_mutagen_fields(audio, {"description": "Existing Vendor Description"})
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="mutagen", bwfmetaedit=_fake_bwfmetaedit(tmp_path))

    by_field = {entry.field: entry for entry in plan.entries}
    assert plan.summary.supported_entries == 1
    assert plan.summary.skip_existing_entries == 1
    assert by_field["description"].action == "skip_existing"
    assert by_field["description"].supported is False
    assert by_field["description"].existing_value == "Existing Vendor Description"
    assert by_field["category"].action == "write_tag"

    replace_plan = build_metadata_write_plan(
        tmp_db,
        root=root,
        backend="mutagen",
        bwfmetaedit=_fake_bwfmetaedit(tmp_path),
        replace_existing=True,
    )

    by_field = {entry.field: entry for entry in replace_plan.entries}
    assert replace_plan.summary.supported_entries == 2
    assert replace_plan.summary.replace_entries == 1
    assert by_field["description"].action == "replace_tag"
    assert by_field["description"].supported is True

    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(replace_plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.errors == []
    assert preview.would_write == 2
    assert preview.commands[0].allow_overwrite is True
    assert preview.commands[0].fields == {"description": "Metal Hit", "genre": "SFX"}


def test_metadata_write_fixture_bundle_can_write_and_readback_mutagen_tags(
    tmp_path: Path, tmp_db: Path, monkeypatch
) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    tag_store: dict[str, dict[str, list[str]]] = {}

    class FakeMutagenFile(dict):
        def save(self) -> None:
            return None

    def fake_load_mutagen_file(path: Path):
        return tag_store.setdefault(str(path), FakeMutagenFile())

    monkeypatch.setattr(metadata_write, "_load_mutagen_file", fake_load_mutagen_file)
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(
        plan_path,
        bundle_dir,
        db_path=tmp_db,
        write_fixture_metadata=True,
        quiet=True,
    )

    assert len(bundle.files) == 1
    fixture = bundle.files[0]
    assert fixture.backend == "mutagen"
    assert fixture.metadata_written is True
    assert fixture.errors == []
    assert tag_store[fixture.fixture_path] == {"description": ["Metal Hit"], "genre": ["SFX"]}

    report = compare_metadata_write_fixture_readback(bundle_dir, quiet=True)

    assert report.summary.files_checked == 1
    assert report.summary.matched_files == 1
    assert report.summary.mismatched_files == 0
    assert report.summary.error_files == 0
    assert report.files[0].matched_fields == ["description", "genre"]


def test_metadata_write_fixture_bundle_preserves_multiple_mutagen_keywords(
    tmp_path: Path, tmp_db: Path, monkeypatch
) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    tag_store: dict[str, dict[str, list[str]]] = {}

    class FakeMutagenFile(dict):
        def save(self) -> None:
            return None

    def fake_load_mutagen_file(path: Path):
        return tag_store.setdefault(str(path), FakeMutagenFile())

    monkeypatch.setattr(metadata_write, "_load_mutagen_file", fake_load_mutagen_file)
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Car Crash 01.flac"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)
    _seed_keyword_tags(tmp_db, ["vehicle impact", "auto collision", "wreck"])

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)
    assert len(preview.commands) == 1
    expected_keywords = ["auto collision", "vehicle impact", "wreck"]
    assert preview.commands[0].fields["keywords"] == expected_keywords

    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(
        plan_path,
        bundle_dir,
        db_path=tmp_db,
        write_fixture_metadata=True,
        quiet=True,
    )

    fixture = bundle.files[0]
    assert tag_store[fixture.fixture_path]["keywords"] == expected_keywords

    report = compare_metadata_write_fixture_readback(bundle_dir, quiet=True)

    assert report.summary.matched_files == 1
    assert report.summary.mismatched_files == 0
    assert report.files[0].actual_fields["keywords"] == expected_keywords
    assert "keywords" in report.files[0].matched_fields


def test_metadata_write_fixture_bundle_writes_real_mutagen_format_matrix(tmp_path: Path, tmp_db: Path) -> None:
    pytest.importorskip("mutagen")
    root = tmp_path / "library"
    root.mkdir()
    cases = {
        ".flac": [("description", "Flac Description"), ("category", "SFX"), ("keyword", "impact")],
        ".ogg": [("description", "Ogg Description"), ("category", "SFX"), ("keyword", "texture")],
        ".opus": [("description", "Opus Description"), ("category", "SFX"), ("keyword", "whoosh")],
        ".mp3": [("category", "SFX"), ("originator", "Wavwarden QA"), ("originator_reference", "WW-MP3")],
        ".m4a": [("description", "M4A Description"), ("category", "SFX")],
        ".aif": [("description", "AIFF Description"), ("category", "SFX")],
        ".aiff": [("description", "AIFF Description"), ("category", "SFX")],
    }

    generated_extensions: set[str] = set()
    for extension, tags in cases.items():
        audio = root / f"fixture{extension}"
        try:
            _write_real_tagged_audio_fixture(audio)
        except Exception:
            continue
        generated_extensions.add(extension)
        file_id = _seed_indexed_file(tmp_db, audio)
        for field, value in tags:
            _seed_tag(tmp_db, field, value, file_id=file_id)

    if not generated_extensions:
        pytest.skip("no real Mutagen fixture formats could be generated")
    assert ".flac" in generated_extensions

    plan = build_metadata_write_plan(tmp_db, root=root, backend="mutagen", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.errors == []
    assert {Path(command.path).suffix.lower() for command in preview.commands} == generated_extensions - {
        ".aif",
        ".aiff",
    }
    assert not any(entry.supported for entry in plan.entries if Path(entry.path).suffix.lower() in {".aif", ".aiff"})

    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(
        plan_path,
        bundle_dir,
        db_path=tmp_db,
        write_fixture_metadata=True,
        quiet=True,
    )

    assert bundle.errors == []
    assert all(fixture.metadata_written for fixture in bundle.files)

    report = compare_metadata_write_fixture_readback(bundle_dir, quiet=True)

    assert report.summary.files_checked == len(preview.commands)
    assert report.summary.matched_files == len(preview.commands)
    assert report.summary.mismatched_files == 0
    assert report.summary.error_files == 0


def test_metadata_write_apply_writes_and_undoes_real_flac(tmp_path: Path, tmp_db: Path) -> None:
    pytest.importorskip("mutagen")
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    _write_real_tagged_audio_fixture(audio)
    original = audio.read_bytes()
    _seed_file(tmp_db, audio)
    _seed_keyword_tags(tmp_db, ["impact", "metal"])

    plan = build_metadata_write_plan(tmp_db, root=root, backend="mutagen", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    log_path = tmp_path / "metadata_apply_log.json"

    applied = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=tmp_path / "backups",
        log_path=log_path,
        quiet=True,
    )

    assert applied.errors == []
    assert applied.files_backed_up == 1
    assert applied.files_written == 1
    assert applied.files_verified == 1
    assert applied.backups[0]["pre_apply_md5"] == _md5(Path(applied.backups[0]["backup_path"]))
    assert applied.backups[0]["post_apply_md5"] == _md5(audio)
    assert metadata_write.read_mutagen_fields(audio, ["description", "genre", "keywords"]) == {
        "description": "Metal Hit",
        "genre": "SFX",
        "keywords": ["impact", "metal"],
    }

    undone = undo_metadata_write_apply_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undone.errors == []
    assert undone.restored == 1
    assert audio.read_bytes() == original


def test_metadata_write_apply_refuses_config_safe_folder(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    safe = root / "Master"
    safe.mkdir(parents=True)
    audio = safe / "SFX_HIT_01.wav"
    _write_wav_without_bext(audio)
    original = audio.read_bytes()
    _seed_file(tmp_db, audio)
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(safe)]}))

    plan = build_metadata_write_plan(
        tmp_db,
        root=root,
        backend="bwfmetaedit",
        bwfmetaedit=_fake_bwfmetaedit(tmp_path),
    )
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    applied = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=tmp_path / "backups",
        log_path=tmp_path / "metadata_apply_log.json",
        config_path=config_path,
        quiet=True,
    )

    assert applied.files_written == 0
    assert applied.files_backed_up == 0
    assert applied.errors == [
        {
            "path": str(audio),
            "error": "protected by safe folder",
            "safe_folder": str(safe.resolve()),
        }
    ]
    assert audio.read_bytes() == original


def test_metadata_write_fixture_bundle_can_execute_bwfmetaedit_on_copied_fixture(
    tmp_path: Path, tmp_db: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    _write_wav_without_bext(audio)
    _seed_file(tmp_db, audio)
    _seed_keyword_tags(tmp_db, ["vehicle impact", "auto collision", "wreck"])
    calls: list[tuple[list[str], Path]] = []

    def fake_run_bwfmetaedit_command(command: list[str], fixture_path: Path, timeout: int = 30) -> dict:
        calls.append((list(command), fixture_path))
        executable_command = metadata_write._bwfmetaedit_write_command(command, fixture_path)
        _write_wav_with_info(
            fixture_path,
            description="Metal Hit",
            info={"IKEY": "auto collision; vehicle impact; wreck"},
        )
        return {"command": executable_command, "returncode": 0, "stdout": "updated\n", "stderr": ""}

    monkeypatch.setattr(metadata_write, "run_bwfmetaedit_command", fake_run_bwfmetaedit_command)
    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(
        plan_path,
        bundle_dir,
        db_path=tmp_db,
        write_fixture_metadata=True,
        quiet=True,
    )

    assert read_bext_core_fields(audio) == {}
    assert len(calls) == 1
    fixture = bundle.files[0]
    assert fixture.backend == "bwfmetaedit"
    assert fixture.metadata_written is True
    assert fixture.errors == []
    assert fixture.write_result == {
        "command": [
            str(tmp_path / "bwfmetaedit"),
            "--reject-overwrite",
            "--specialchars",
            "--Description=Metal Hit",
            "--IKEY=auto collision; vehicle impact; wreck",
            fixture.fixture_path,
        ],
        "returncode": 0,
        "stdout": "updated\n",
        "stderr": "",
    }
    assert "--simulate" in calls[0][0]
    assert "--simulate" not in fixture.write_result["command"]

    report = compare_metadata_write_fixture_readback(bundle_dir, quiet=True)

    assert report.summary.files_checked == 1
    assert report.summary.matched_files == 1
    assert report.summary.mismatched_files == 0
    assert report.summary.error_files == 0
    assert report.files[0].matched_fields == ["Description", "IKEY"]
    assert report.files[0].actual_fields["IKEY"] == ["auto collision", "vehicle impact", "wreck"]


def test_bwfmetaedit_fixture_write_refuses_non_fixture_target(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.wav"
    original = tmp_path / "original.wav"
    command = ["bwfmetaedit", "--simulate", "--Description=Metal Hit", str(original)]

    try:
        metadata_write._bwfmetaedit_write_command(command, fixture)
    except RuntimeError as e:
        assert str(e) == "BWF MetaEdit command does not target the expected audio path"
    else:
        raise AssertionError("expected fixture target guard to reject original path")


def test_metadata_write_fixture_bundle_can_run_real_bwfmetaedit_when_available(tmp_path: Path, tmp_db: Path) -> None:
    executable = shutil.which("bwfmetaedit") or shutil.which("BWFMetaEdit")
    if executable is None:
        pytest.skip("BWF MetaEdit is not installed")
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    _write_wav_without_bext(audio)
    _seed_file(tmp_db, audio)
    _seed_keyword_tags(tmp_db, ["vehicle impact", "auto collision", "wreck"])

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=executable)
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(
        plan_path,
        bundle_dir,
        db_path=tmp_db,
        write_fixture_metadata=True,
        quiet=True,
    )

    assert read_bext_core_fields(audio) == {}
    fixture = bundle.files[0]
    assert fixture.metadata_written is True
    assert fixture.errors == []
    assert fixture.write_result is not None
    assert fixture.write_result["returncode"] == 0
    assert "--simulate" not in fixture.write_result["command"]
    assert fixture.write_result["command"][-1] == fixture.fixture_path

    report = compare_metadata_write_fixture_readback(bundle_dir, quiet=True)

    assert report.summary.files_checked == 1
    assert report.summary.matched_files == 1
    assert report.summary.error_files == 0
    assert report.files[0].matched_fields == ["Description", "IKEY"]
    assert report.files[0].actual_fields["IKEY"] == ["auto collision", "vehicle impact", "wreck"]


def test_metadata_write_apply_writes_bwfmetaedit_original_with_backup_and_db_refresh(
    tmp_path: Path, tmp_db: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    _write_wav_without_bext(audio)
    original = audio.read_bytes()
    _seed_file(tmp_db, audio)
    write_calls: list[tuple[list[str], Path]] = []

    def fake_run_bwfmetaedit_command(command: list[str], target_path: Path, timeout: int = 30) -> dict:
        write_calls.append((list(command), target_path))
        executable_command = metadata_write._bwfmetaedit_write_command(command, target_path)
        _write_wav_with_bext(target_path, description="Metal Hit")
        return {"command": executable_command, "returncode": 0, "stdout": "updated\n", "stderr": ""}

    monkeypatch.setattr(metadata_write, "run_bwfmetaedit_command", fake_run_bwfmetaedit_command)
    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    dry_run = apply_metadata_write_plan(plan_path, db_path=tmp_db, quiet=True)

    assert dry_run.dry_run is True
    assert dry_run.applied == 1
    assert dry_run.files_written == 1
    assert read_bext_core_fields(audio) == {}

    backup_dir = tmp_path / "backups"
    log_path = tmp_path / "metadata_apply_log.json"
    applied = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=backup_dir,
        log_path=log_path,
        quiet=True,
    )

    assert applied.dry_run is False
    assert applied.applied == 1
    assert applied.files_written == 1
    assert applied.files_backed_up == 1
    assert applied.files_verified == 1
    assert applied.errors == []
    assert applied.write_results == [
        {
            "path": str(audio),
            "command": [
                str(tmp_path / "bwfmetaedit"),
                "--reject-overwrite",
                "--specialchars",
                "--Description=Metal Hit",
                str(audio),
            ],
            "returncode": 0,
            "stdout": "updated\n",
            "stderr": "",
        }
    ]
    assert applied.readback[0]["matched_fields"] == ["Description"]
    assert write_calls[0][1] == audio
    assert "--simulate" in write_calls[0][0]
    backup_path = Path(applied.backups[0]["backup_path"])
    assert backup_path.read_bytes() == original
    conn = get_connection(tmp_db)
    row = conn.execute("SELECT size_bytes, md5, has_bext FROM files WHERE path = ?", (str(audio),)).fetchone()
    conn.close()
    assert row["size_bytes"] == audio.stat().st_size
    assert row["md5"] != "abc123"
    assert row["has_bext"] == 1

    undone = undo_metadata_write_apply_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undone.restored == 1
    assert undone.errors == []
    assert audio.read_bytes() == original
    conn = get_connection(tmp_db)
    row = conn.execute("SELECT size_bytes, md5, has_bext FROM files WHERE path = ?", (str(audio),)).fetchone()
    conn.close()
    assert row["size_bytes"] == len(original)
    assert row["md5"] != "abc123"
    assert row["has_bext"] == 0


def test_metadata_write_apply_can_run_real_bwfmetaedit_when_available(tmp_path: Path, tmp_db: Path) -> None:
    executable = shutil.which("bwfmetaedit") or shutil.which("BWFMetaEdit")
    if executable is None:
        pytest.skip("BWF MetaEdit is not installed")
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    _write_wav_without_bext(audio)
    original = audio.read_bytes()
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=executable)
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    log_path = tmp_path / "metadata_apply_log.json"
    applied = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=tmp_path / "backups",
        log_path=log_path,
        quiet=True,
    )

    assert applied.applied == 1
    assert applied.files_verified == 1
    assert applied.errors == []
    assert applied.write_results[0]["returncode"] == 0
    assert read_bext_core_fields(audio)["Description"] == "Metal Hit"

    undone = undo_metadata_write_apply_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undone.restored == 1
    assert audio.read_bytes() == original


def test_metadata_write_apply_writes_mutagen_original_with_backup_and_db_refresh(
    tmp_path: Path, tmp_db: Path, monkeypatch
) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    writes: list[tuple[Path, dict[str, str]]] = []
    readbacks: dict[Path, dict[str, str]] = {}

    def fake_write_mutagen_fields(path: Path, fields: dict[str, str]) -> None:
        writes.append((path, dict(fields)))
        path.write_bytes(path.read_bytes() + b"\nTAGS")
        readbacks[path] = dict(fields)

    monkeypatch.setattr(metadata_write, "write_mutagen_fields", fake_write_mutagen_fields)
    monkeypatch.setattr(metadata_write, "read_mutagen_fields", lambda path, _fields: readbacks.get(path, {}))
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    original = b"not really audio"
    audio.write_bytes(original)
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    dry_run = apply_metadata_write_plan(plan_path, db_path=tmp_db, quiet=True)

    assert dry_run.dry_run is True
    assert dry_run.applied == 2
    assert dry_run.files_written == 1
    assert writes == []
    assert audio.read_bytes() == original

    backup_dir = tmp_path / "backups"
    log_path = tmp_path / "metadata_apply_log.json"
    applied = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=backup_dir,
        log_path=log_path,
        quiet=True,
    )

    assert applied.dry_run is False
    assert applied.applied == 2
    assert applied.files_written == 1
    assert applied.files_backed_up == 1
    assert applied.files_verified == 1
    assert applied.errors == []
    assert applied.readback == [
        {
            "path": str(audio),
            "expected_fields": {"description": "Metal Hit", "genre": "SFX"},
            "actual_fields": {"description": "Metal Hit", "genre": "SFX"},
            "matched_fields": ["description", "genre"],
            "mismatched_fields": {},
        }
    ]
    assert writes == [(audio, {"description": "Metal Hit", "genre": "SFX"})]
    assert audio.read_bytes() == original + b"\nTAGS"
    backup_path = Path(applied.backups[0]["backup_path"])
    assert backup_path.read_bytes() == original
    assert log_path.exists()
    conn = get_connection(tmp_db)
    row = conn.execute("SELECT size_bytes, md5 FROM files WHERE path = ?", (str(audio),)).fetchone()
    conn.close()
    assert row["size_bytes"] == len(original + b"\nTAGS")
    assert row["md5"] != "abc123"

    undo_dry_run = undo_metadata_write_apply_log(log_path, db_path=tmp_db, quiet=True)
    assert undo_dry_run.dry_run is True
    assert undo_dry_run.restored == 1
    assert audio.read_bytes() == original + b"\nTAGS"

    undone = undo_metadata_write_apply_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)
    assert undone.dry_run is False
    assert undone.restored == 1
    assert undone.errors == []
    assert audio.read_bytes() == original
    conn = get_connection(tmp_db)
    row = conn.execute("SELECT size_bytes, md5 FROM files WHERE path = ?", (str(audio),)).fetchone()
    conn.close()
    assert row["size_bytes"] == len(original)
    assert row["md5"] != "abc123"


def test_metadata_write_apply_reports_mutagen_readback_mismatch(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    wrote = False

    def fake_write_mutagen_fields(_path: Path, _fields: dict[str, str]) -> None:
        nonlocal wrote
        wrote = True

    def fake_read_mutagen_fields(_path: Path, _fields: list[str]) -> dict[str, str]:
        return {"description": "Wrong"} if wrote else {}

    monkeypatch.setattr(metadata_write, "write_mutagen_fields", fake_write_mutagen_fields)
    monkeypatch.setattr(metadata_write, "read_mutagen_fields", fake_read_mutagen_fields)
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    result = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=tmp_path / "backups",
        quiet=True,
    )

    assert result.applied == 0
    assert result.files_written == 0
    assert result.files_backed_up == 1
    assert result.files_verified == 0
    # PR #7: mismatch must trigger an automatic restore from the pre-apply backup.
    assert result.files_restored == 1
    assert result.readback[0]["mismatched_fields"] == {
        "genre": {"expected": "SFX", "actual": None},
        "description": {"expected": "Metal Hit", "actual": "Wrong"},
    }
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error["path"] == str(audio)
    assert "metadata readback mismatch" in error["error"]
    assert "original restored from backup" in error["error"]
    assert error["fields"] == result.readback[0]["mismatched_fields"]
    assert "backup_path" in error
    # And the actual file on disk should match the backup (was rolled back).
    backup_path = Path(error["backup_path"])
    assert audio.read_bytes() == backup_path.read_bytes()


def _wired_mutagen_fake(monkeypatch):
    """Wire fake mutagen read/write that flip from empty to full once a write happens.

    Matches the pattern used by the existing readback-mismatch test: during
    plan-build, ``read_mutagen_fields`` must return an empty dict so the
    planner generates write entries; once ``write_mutagen_fields`` is called,
    subsequent reads return the expected values so the readback verify
    passes. The shared ``wrote`` flag is the cheapest way to express that.
    """
    state = {"wrote": False}

    def fake_write(_path, _fields):
        state["wrote"] = True

    def fake_read(_path, _fields):
        return {"description": "Metal Hit", "genre": "SFX"} if state["wrote"] else {}

    monkeypatch.setattr(metadata_write, "write_mutagen_fields", fake_write)
    monkeypatch.setattr(metadata_write, "read_mutagen_fields", fake_read)


def test_metadata_write_apply_defaults_to_sibling_backups(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    """PR #13 follow-up: without --backup-dir, backups are .original-<stamp>Z siblings."""
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    _wired_mutagen_fake(monkeypatch)
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    result = apply_metadata_write_plan(plan_path, db_path=tmp_db, dry_run=False, quiet=True)

    # A sibling .original-<stamp>Z file lives next to the source.
    siblings = list(root.glob("SFX_HIT_01.flac.original-*Z"))
    assert len(siblings) == 1
    assert result.backup_dir == "sibling"
    assert result.files_backed_up == 1
    # The recorded backup_path in the result points at the sibling.
    assert result.backups[0]["backup_path"] == str(siblings[0])


def test_metadata_write_apply_cli_requires_yes_when_no_backup(tmp_path: Path, tmp_db: Path) -> None:
    """PR #17: --apply --no-backup refuses without --yes so the safety bypass is intentional."""
    from sfxworkbench.cli import app
    from typer.testing import CliRunner

    runner = CliRunner()
    # Plan file doesn't need to exist meaningfully — the safety gate fires before
    # we even reach the load_metadata_write_plan call.
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}")
    result = runner.invoke(
        app,
        [
            "metadata",
            "write-apply",
            str(plan_path),
            "--db",
            str(tmp_db),
            "--apply",
            "--no-backup",
        ],
    )
    assert result.exit_code == 1
    assert "safety net" in result.output
    assert "--yes" in result.output


def test_metadata_write_apply_with_no_backup_skips_backups(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    """PR #13 follow-up: --no-backup truly skips backups (and disables restore-on-mismatch)."""
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    _wired_mutagen_fake(monkeypatch)
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    audio.write_bytes(b"x")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    result = apply_metadata_write_plan(plan_path, db_path=tmp_db, dry_run=False, backup=False, quiet=True)

    assert result.files_backed_up == 0
    assert result.backup_dir is None
    siblings = list(root.glob("SFX_HIT_01.flac.original-*Z"))
    assert siblings == []
    # Backup metadata still recorded (so apply-log keeps a per-file row) but
    # backup_path is None.
    assert result.backups[0]["backup_path"] is None


def test_metadata_write_apply_rejects_file_changed_after_plan(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    writes: list[Path] = []
    monkeypatch.setattr(metadata_write, "write_mutagen_fields", lambda path, _fields: writes.append(path))
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    original = b"not really audio"
    audio.write_bytes(original)
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    changed = original + b"\nexternal edit"
    audio.write_bytes(changed)

    result = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=tmp_path / "backups",
        quiet=True,
    )

    assert result.applied == 0
    assert result.files_written == 0
    assert result.files_backed_up == 0
    assert result.backups == []
    assert writes == []
    assert result.errors == [
        {
            "entry_id": 1,
            "path": str(audio),
            "error": f"file size changed: expected {len(original)}, got {len(changed)}",
        },
        {
            "entry_id": 2,
            "path": str(audio),
            "error": f"file size changed: expected {len(original)}, got {len(changed)}",
        },
    ]


def test_metadata_write_undo_refuses_target_changed_after_apply(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    readbacks: dict[Path, dict[str, str]] = {}

    def fake_write_mutagen_fields(path: Path, fields: dict[str, str]) -> None:
        path.write_bytes(path.read_bytes() + b"\nTAGS")
        readbacks[path] = dict(fields)

    monkeypatch.setattr(metadata_write, "write_mutagen_fields", fake_write_mutagen_fields)
    monkeypatch.setattr(metadata_write, "read_mutagen_fields", lambda path, _fields: readbacks.get(path, {}))
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.flac"
    original = b"not really audio"
    audio.write_bytes(original)
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    log_path = tmp_path / "metadata_apply_log.json"
    applied = apply_metadata_write_plan(
        plan_path,
        db_path=tmp_db,
        dry_run=False,
        backup_dir=tmp_path / "backups",
        log_path=log_path,
        quiet=True,
    )
    assert applied.errors == []
    audio.write_bytes(audio.read_bytes() + b"\npost apply edit")

    undone = undo_metadata_write_apply_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undone.restored == 0
    assert undone.errors == [{"path": str(audio), "error": "target changed since apply log was written"}]
    assert audio.read_bytes() == original + b"\nTAGS\npost apply edit"


def test_metadata_write_preview_requires_available_backend(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(
        tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=tmp_path / "missing-bwfmetaedit"
    )
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)

    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, quiet=True)

    assert preview.would_write == 0
    assert preview.errors == [{"path": str(plan_path), "error": "backend unavailable: bwfmetaedit"}]
    assert preview.commands == []


def test_metadata_write_preview_rejects_non_ascii_bext_values(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)
    conn = get_connection(tmp_db)
    conn.execute("UPDATE accepted_tags SET value = ? WHERE field = 'description'", ("Café Hit",))
    conn.commit()
    conn.close()

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    preview = preview_metadata_write_plan(plan_path, db_path=tmp_db, require_reviewed=True, quiet=True)

    assert preview.would_write == 0
    assert preview.commands == []
    assert preview.errors == [
        {
            "entry_id": 2,
            "path": str(audio),
            "error": "Description must be ASCII for BWF MetaEdit/BEXT",
        }
    ]


def test_metadata_write_fixture_bundle_copies_audio_and_rewrites_commands(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)

    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(plan_path, bundle_dir, db_path=tmp_db, quiet=True)

    manifest = bundle_dir / FIXTURE_MANIFEST_NAME
    assert manifest.exists()
    assert len(bundle.files) == 1
    fixture = bundle.files[0]
    assert fixture.source_path == str(audio)
    assert fixture.fixture_path == str(bundle_dir / "audio" / "000001_SFX_HIT_01.wav")
    assert Path(fixture.fixture_path).read_bytes() == b"not really audio"
    assert audio.read_bytes() == b"not really audio"
    assert fixture.expected_fields == {"Description": "Metal Hit"}
    assert fixture.command[-1] == fixture.fixture_path
    assert fixture.command[:-1] == [
        str(tmp_path / "bwfmetaedit"),
        "--simulate",
        "--reject-overwrite",
        "--specialchars",
        "--Description=Metal Hit",
    ]

    payload = json.loads(manifest.read_text())
    assert payload["files"][0]["expected_fields"] == {"Description": "Metal Hit"}
    assert payload["files"][0]["command"][-1].endswith("000001_SFX_HIT_01.wav")


def test_read_bext_core_fields_reads_supported_fields(tmp_path: Path) -> None:
    wav = tmp_path / "tagged.wav"
    _write_wav_with_bext(
        wav,
        description="Metal Hit",
        originator="sfxworkbench",
        originator_reference="WW-001",
    )

    fields = read_bext_core_fields(wav)

    assert fields["Description"] == "Metal Hit"
    assert fields["Originator"] == "sfxworkbench"
    assert fields["OriginatorReference"] == "WW-001"


def test_read_riff_info_fields_reads_ikey(tmp_path: Path) -> None:
    wav = tmp_path / "tagged_info.wav"
    _write_wav_with_info(wav, info={"IKEY": "auto collision; vehicle impact; wreck"})

    fields = read_riff_info_fields(wav)

    assert fields["IKEY"] == "auto collision; vehicle impact; wreck"


def test_metadata_write_readback_matches_fixture_manifest(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(plan_path, bundle_dir, db_path=tmp_db, quiet=True)
    _write_wav_with_bext(Path(bundle.files[0].fixture_path), description="Metal Hit")

    report = compare_metadata_write_fixture_readback(bundle_dir, quiet=True)

    assert report.summary.files_checked == 1
    assert report.summary.matched_files == 1
    assert report.summary.mismatched_files == 0
    assert report.files[0].matched_fields == ["Description"]
    assert report.files[0].mismatched_fields == {}


def test_metadata_write_readback_reports_mismatched_fixture_fields(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, backend="bwfmetaedit", bwfmetaedit=_fake_bwfmetaedit(tmp_path))
    plan_path = tmp_path / "metadata_write_plan.json"
    write_metadata_write_plan(plan, plan_path, quiet=True)
    review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    bundle_dir = tmp_path / "metadata_fixtures"
    bundle = build_metadata_write_fixture_bundle(plan_path, bundle_dir, db_path=tmp_db, quiet=True)
    _write_wav_with_bext(Path(bundle.files[0].fixture_path), description="Wrong")

    report = compare_metadata_write_fixture_readback(bundle_dir / FIXTURE_MANIFEST_NAME, quiet=True)

    assert report.summary.files_checked == 1
    assert report.summary.matched_files == 0
    assert report.summary.mismatched_files == 1
    assert report.files[0].mismatched_fields == {"Description": {"expected": "Metal Hit", "actual": "Wrong"}}
