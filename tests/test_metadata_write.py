"""Tests for dry-run embedded metadata write plans."""

from __future__ import annotations

import json
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.metadata_write import (
    FIXTURE_MANIFEST_NAME,
    build_metadata_write_fixture_bundle,
    build_metadata_write_plan,
    preview_metadata_write_plan,
    review_metadata_write_plan,
    write_metadata_write_plan,
)


def _fake_bwfmetaedit(tmp_path: Path) -> Path:
    executable = tmp_path / "bwfmetaedit"
    executable.write_text("#!/bin/sh\necho 'BWF MetaEdit 24.04'\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def _seed_file(tmp_db: Path, path: Path) -> None:
    conn = get_connection(tmp_db)
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
            path.stat().st_size,
            path.stat().st_mtime,
            "abc123",
            48000,
            24,
            2,
            1.0,
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
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
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


def test_metadata_write_plan_maps_supported_and_unsupported_tags(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))

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


def test_metadata_write_review_and_preview_is_dry_run(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
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
        "--description=Metal Hit",
        str(audio),
    ]


def test_metadata_write_preview_requires_available_backend(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "SFX_HIT_01.wav"
    audio.write_bytes(b"not really audio")
    _seed_file(tmp_db, audio)

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=tmp_path / "missing-bwfmetaedit")
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

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
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

    plan = build_metadata_write_plan(tmp_db, root=root, bwfmetaedit=_fake_bwfmetaedit(tmp_path))
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
        "--description=Metal Hit",
    ]

    payload = json.loads(manifest.read_text())
    assert payload["files"][0]["expected_fields"] == {"Description": "Metal Hit"}
    assert payload["files"][0]["command"][-1].endswith("000001_SFX_HIT_01.wav")
