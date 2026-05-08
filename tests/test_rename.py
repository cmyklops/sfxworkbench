"""Tests for wavwarden.rename."""

from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.rename import apply_rename_plan, build_rename_plan, undo_rename_log
from wavwarden.scan import scan_library


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
