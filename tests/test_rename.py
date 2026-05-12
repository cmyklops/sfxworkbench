"""Tests for sfxworkbench.rename."""

import json
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.rename import apply_rename_plan, build_rename_plan, undo_rename_log
from sfxworkbench.scan import scan_library


def test_rename_plan_sanitizes_and_prefixes_non_ucs(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    bad = root / "bad:name.wav"
    bad.write_bytes(
        b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x04\x00\x00\x00\x00\x00\x00\x00"
    )

    plan = build_rename_plan(root)

    assert len(plan.entries) == 1
    assert plan.entries[0].new_filename == "SFX_MISC_BAD_NAME.wav"
    assert "illegal_or_risky_chars" in plan.entries[0].issue_fixes
    assert "ucs_prefix" in plan.entries[0].issue_fixes


def test_rename_apply_and_undo_updates_filesystem_and_db(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    plan = build_rename_plan(tmp_library)
    target_entry = next(e for e in plan.entries if e.old_filename == "BOOM.wav")
    focused = plan.model_copy(update={"entries": [target_entry], "errors": []})

    log_path = tmp_path / "rename_log.json"
    result = apply_rename_plan(focused, db_path=tmp_db, log_path=log_path, dry_run=False, quiet=True)

    assert result.renamed == 1
    assert log_path.exists()
    assert Path(target_entry.new_path).exists()
    assert not Path(target_entry.old_path).exists()

    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files WHERE filename = ?", (target_entry.new_filename,)).fetchall()
    conn.close()
    assert len(rows) == 1

    undo = undo_rename_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)
    assert undo.undone == 1
    assert Path(target_entry.old_path).exists()
    assert not Path(target_entry.new_path).exists()


def test_rename_refuses_collision(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    source = root / "boom.wav"
    target = root / "SFX_MISC_BOOM.wav"
    source.write_bytes(b"audio")
    target.write_bytes(b"existing")

    plan = build_rename_plan(root)

    assert plan.errors
    assert plan.errors[0]["error"] == "target exists"


def test_rename_apply_refuses_stale_index_target_before_moving(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    source = root / "bad:name.wav"
    source.write_bytes(b"audio")
    plan = build_rename_plan(root)
    entry = plan.entries[0]

    conn = get_connection(tmp_db)
    stat = source.stat()
    for path in (Path(entry.old_path), Path(entry.new_path)):
        conn.execute(
            """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(path), path.name, path.stem, path.suffix.lower(), stat.st_size, stat.st_mtime, None, "2026"),
        )
    conn.commit()
    conn.close()

    result = apply_rename_plan(plan, db_path=tmp_db, dry_run=False, quiet=True)

    assert result.renamed == 0
    assert result.errors[0]["error"] == "target already exists in index"
    assert source.exists()
    assert not Path(entry.new_path).exists()


def test_safe_rename_plan_preserves_names_without_ucs_prefix(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    bad = root / "bad:name.wav"
    bad.write_bytes(b"audio")

    plan = build_rename_plan(root, pattern="safe")

    assert len(plan.entries) == 1
    assert plan.entries[0].new_filename == "bad_name.wav"
    assert "illegal_chars" in plan.entries[0].issue_fixes
    assert "ucs_prefix" not in plan.entries[0].issue_fixes


def test_safe_rename_applies_directory_and_file_updates_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "lib"
    bad_dir = root / "Bad: Folder "
    bad_dir.mkdir(parents=True)
    bad_file = bad_dir / "bad:file.wav"
    bad_file.write_bytes(
        b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x04\x00\x00\x00\x00\x00\x00\x00"
    )
    scan_library(root, tmp_db, skip_hash=True, quiet=True)

    plan = build_rename_plan(root, pattern="safe")
    log_path = tmp_path / "safe_rename_log.json"
    result = apply_rename_plan(plan, db_path=tmp_db, log_path=log_path, dry_run=False, quiet=True)

    assert result.renamed == 2
    new_file = root / "Bad_ Folder" / "bad_file.wav"
    assert new_file.exists()
    assert not bad_file.exists()

    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    issues = conn.execute("SELECT issue FROM fn_issues").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(new_file)]
    assert [row["issue"] for row in issues] == []

    undo = undo_rename_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)
    assert undo.undone == 2
    assert bad_file.exists()


def test_portable_rename_plan_fixes_risky_and_non_ascii_names(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    bad_dir = root / "CB Sound Design - Defect \u2013 Hum, Noise And Glitches"
    bad_dir.mkdir(parents=True)
    bad_file = bad_dir / "100_C#_Flesh & Bones!.wav"
    bad_file.write_bytes(b"audio")

    plan = build_rename_plan(root, pattern="portable")
    planned = {entry.old_filename: entry.new_filename for entry in plan.entries}

    assert planned["CB Sound Design - Defect \u2013 Hum, Noise And Glitches"] == (
        "CB Sound Design - Defect - Hum, Noise And Glitches"
    )
    assert planned["100_C#_Flesh & Bones!.wav"] == "100_CSharp_Flesh and Bones_.wav"
    assert any("non_ascii" in entry.issue_fixes for entry in plan.entries)
    assert any("risky_or_illegal_chars" in entry.issue_fixes for entry in plan.entries)


def test_portable_rename_translates_cyrillic_c_in_key_names(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    bad_file = root / "Ghosthack - FRE - Vocal Loop 07 - \u0421m 126BPM.wav"
    bad_file.write_bytes(b"audio")

    plan = build_rename_plan(root, pattern="portable")

    assert len(plan.entries) == 1
    assert plan.entries[0].new_filename == "Ghosthack - FRE - Vocal Loop 07 - Cm 126BPM.wav"


def test_portable_rename_spaces_ampersand_replacement(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    bad_file = root / "Doors&Building stuff.wav"
    bad_file.write_bytes(b"audio")

    plan = build_rename_plan(root, pattern="portable")

    assert plan.entries[0].new_filename == "Doors and Building stuff.wav"


def test_portable_rename_directory_ampersand_updates_db_and_issues(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "lib"
    bad_dir = root / "Series 9000 Open & Close"
    bad_dir.mkdir(parents=True)
    wav = bad_dir / "Door 01.wav"
    wav.write_bytes(
        b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x04\x00\x00\x00\x00\x00\x00\x00"
    )
    scan_library(root, tmp_db, skip_hash=True, quiet=True)

    plan = build_rename_plan(root, pattern="portable")

    assert len(plan.entries) == 1
    assert plan.entries[0].old_filename == "Series 9000 Open & Close"
    assert plan.entries[0].new_filename == "Series 9000 Open and Close"

    log_path = tmp_path / "portable_rename_log.json"
    result = apply_rename_plan(plan, db_path=tmp_db, log_path=log_path, dry_run=False, quiet=True)

    new_wav = root / "Series 9000 Open and Close" / "Door 01.wav"
    assert result.renamed == 1
    assert new_wav.exists()
    assert not wav.exists()

    conn = get_connection(tmp_db)
    paths = [row["path"] for row in conn.execute("SELECT path FROM files").fetchall()]
    issues = conn.execute("SELECT issue FROM fn_issues").fetchall()
    conn.close()
    assert paths == [str(new_wav)]
    assert issues == []


def test_portable_rename_shortens_long_paths(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    deep = root / ("Long Folder " * 8).strip()
    deep.mkdir(parents=True)
    bad_file = deep / (("Very Long Filename " * 9).strip() + ".wav")
    bad_file.write_bytes(b"audio")

    plan = build_rename_plan(root, pattern="portable")

    assert len(plan.entries) == 1
    assert "path_too_long" in plan.entries[0].issue_fixes
    assert len(plan.entries[0].new_path.encode("utf-8")) <= 240
    assert plan.entries[0].new_filename.endswith(".wav")


def test_apply_rename_plan_allows_partial_when_requested(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    valid_source = root / "bad:name.wav"
    blocked_source = root / "blocked.wav"
    valid_source.write_bytes(b"audio")
    blocked_source.write_bytes(b"audio")

    plan = build_rename_plan(root, pattern="safe")
    valid_entry = next(e for e in plan.entries if e.old_filename == "bad:name.wav")
    blocked_target = root / "already-there.wav"
    blocked_target.write_bytes(b"audio")
    focused = plan.model_copy(
        update={
            "entries": [valid_entry],
            "errors": [{"path": str(blocked_source), "target": str(blocked_target), "error": "target exists"}],
        }
    )

    refused = apply_rename_plan(focused, dry_run=False, quiet=True)

    assert refused.renamed == 0
    assert valid_source.exists()

    allowed = apply_rename_plan(
        focused, log_path=tmp_path / "partial_log.json", dry_run=False, quiet=True, allow_partial=True
    )

    assert allowed.renamed == 1
    assert allowed.errors == focused.errors
    assert Path(valid_entry.new_path).exists()


def test_rename_plan_uses_config_safe_folder(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    safe = root / "Master"
    safe.mkdir(parents=True)
    protected = safe / "bad:name.wav"
    protected.write_bytes(b"audio")
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(safe)]}))

    plan = build_rename_plan(root, pattern="safe", config_path=config_path)

    assert plan.entries == []
    assert plan.errors == [
        {
            "path": str(protected),
            "error": "protected by safe folder",
            "safe_folder": str(safe.resolve()),
        }
    ]


def test_apply_rename_plan_refuses_config_safe_folder_for_old_plan(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    safe = root / "Master"
    safe.mkdir(parents=True)
    protected = safe / "bad:name.wav"
    protected.write_bytes(b"audio")
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(safe)]}))
    old_plan = build_rename_plan(root, pattern="safe")

    result = apply_rename_plan(old_plan, dry_run=False, quiet=True, config_path=config_path)

    assert result.renamed == 0
    assert result.errors == [
        {
            "path": str(protected),
            "error": "protected by safe folder",
            "safe_folder": str(safe.resolve()),
        }
    ]
    assert protected.exists()
