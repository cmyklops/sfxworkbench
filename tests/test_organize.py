"""Tests for folder organization previews."""

from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.organize import (
    apply_nesting_plan,
    apply_organize_report,
    audit_organization,
    build_nesting_plan_from_report,
    review_organize_report,
    undo_nesting_log,
    undo_organize_log,
    write_organize_audit_report,
)


def test_organize_audit_strips_obvious_top_level_sort_prefixes(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    for name in [
        "01 - Ghosthack - Ultimate Foley Sounds",
        "01 Ancient_Game",
        "1 Boom TRAX",
        "1. SoundMorph - Energy",
        "00  SoundMorph - Sinematic 2",
        "10 Years Anniversary Addition - Cinematic Metal Impacts",
        "10000",
    ]:
        (root / name).mkdir()

    report = audit_organization(root)

    planned = {entry.old_name: entry.new_name for entry in report.entries}
    assert planned == {
        "01 - Ghosthack - Ultimate Foley Sounds": "Ghosthack - Ultimate Foley Sounds",
        "01 Ancient_Game": "Ancient_Game",
        "1 Boom TRAX": "Boom TRAX",
        "1. SoundMorph - Energy": "SoundMorph - Energy",
        "00  SoundMorph - Sinematic 2": "SoundMorph - Sinematic 2",
    }
    assert report.summary.directories_scanned == 7
    assert report.summary.planned == 5
    assert report.summary.errors == 0


def test_organize_audit_reports_collisions(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "01 Boom").mkdir()
    (root / "Boom").mkdir()

    report = audit_organization(root)

    assert report.entries == []
    assert report.summary.errors == 1
    assert report.errors[0]["error"] == "target exists"


def test_organize_audit_respects_depth(tmp_path: Path) -> None:
    root = tmp_path / "library"
    nested = root / "Vendor" / "01 Pack"
    nested.mkdir(parents=True)

    top_report = audit_organization(root, depth=1)
    nested_report = audit_organization(root, depth=2)

    assert top_report.entries == []
    assert [entry.new_name for entry in nested_report.entries] == ["Pack"]


def test_organize_audit_rejects_unknown_pattern(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()

    try:
        audit_organization(root, pattern="unknown")
    except ValueError as e:
        assert "strip-leading-numbers" in str(e)
        assert "redundant-nesting" in str(e)
    else:
        raise AssertionError("Expected ValueError")


def test_write_organize_audit_report(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "01 Pack").mkdir()
    report = audit_organization(root)
    out = tmp_path / "reports" / "organize.json"

    write_organize_audit_report(report, out, quiet=True)

    assert out.exists()
    assert '"new_name": "Pack"' in out.read_text()


def test_review_organize_report_approves_entries(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "01 Pack").mkdir()
    report = audit_organization(root)
    report_path = tmp_path / "organize.json"
    write_organize_audit_report(report, report_path, quiet=True)

    result = review_organize_report(report_path, approve_all=True, quiet=True)

    assert result.total_entries == 1
    assert result.approved_entries == 1
    assert '"approved_entries": [\n      0\n    ]' in report_path.read_text()


def test_apply_organize_report_requires_review(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "01 Pack"
    source.mkdir()
    report = audit_organization(root)
    report_path = tmp_path / "organize.json"
    write_organize_audit_report(report, report_path, quiet=True)

    result = apply_organize_report(report_path, require_reviewed=True, quiet=True)

    assert result.renamed == 0
    assert result.errors
    assert source.exists()


def test_redundant_nesting_reports_repeated_folder_names(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "Vendor" / "Pack" / "Pack" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    report = audit_organization(root, pattern="redundant-nesting", depth=4)

    repeated = [candidate for candidate in report.candidates if candidate.kind == "repeated_folder_name"]
    assert report.entries == []
    assert report.summary.candidates >= 1
    assert repeated[0].path == str(audio.parent)
    assert repeated[0].target_path == str(audio.parent.parent)
    assert repeated[0].confidence == "high"


def test_redundant_nesting_reports_single_child_chains(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "Vendor" / "Wrapper" / "Only Child" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    report = audit_organization(root, pattern="redundant-nesting", depth=4)

    chains = [candidate for candidate in report.candidates if candidate.kind == "single_child_chain"]
    assert any(candidate.path == str(root / "Vendor" / "Wrapper") for candidate in chains)
    assert all(candidate.suggested_action == "review_collapse_wrapper" for candidate in chains)


def test_redundant_nesting_reports_low_value_wrappers(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "Vendor" / "Pack" / "WAV" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    report = audit_organization(root, pattern="redundant-nesting", depth=4)

    wrappers = [candidate for candidate in report.candidates if candidate.kind == "low_value_wrapper"]
    assert wrappers[0].path == str(audio.parent)
    assert wrappers[0].target_path == str(audio.parent.parent)
    assert wrappers[0].audio_files == 1


def test_redundant_nesting_report_is_not_applyable(tmp_path: Path) -> None:
    root = tmp_path / "library"
    wrapper = root / "Vendor" / "Wrapper" / "Only Child"
    wrapper.mkdir(parents=True)
    (wrapper / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting.json"
    write_organize_audit_report(report, report_path, quiet=True)

    result = apply_organize_report(report_path, require_reviewed=False, quiet=True)

    assert result.renamed == 0
    assert result.errors
    assert "report-only" in result.errors[0]["error"]
    assert wrapper.exists()


def test_build_nesting_plan_from_repeated_folder_report(tmp_path: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    (repeated / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    plan_path = tmp_path / "nesting_plan.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, output_path=plan_path, quiet=True)

    assert plan_path.exists()
    assert len(plan.entries) == 1
    assert plan.entries[0].source_path == str(repeated)
    assert plan.entries[0].target_path == str(repeated.parent)
    assert plan.entries[0].moves[0].new_path == str(repeated.parent / "hit.wav")
    assert plan.errors == []


def test_build_nesting_plan_reports_collisions(tmp_path: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    (repeated / "hit.wav").write_bytes(b"audio")
    (repeated.parent / "hit.wav").write_bytes(b"existing")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, quiet=True)

    assert plan.entries == []
    assert plan.errors[0]["error"] == "target exists"


def test_apply_nesting_plan_requires_review(tmp_path: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    (repeated / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    plan_path = tmp_path / "nesting_plan.json"
    write_organize_audit_report(report, report_path, quiet=True)
    build_nesting_plan_from_report(report_path, output_path=plan_path, quiet=True)

    result = apply_nesting_plan(plan_path, require_reviewed=True, dry_run=False, quiet=True)

    assert result.flattened == 0
    assert result.errors
    assert (repeated / "hit.wav").exists()


def test_apply_and_undo_nesting_plan_updates_filesystem_and_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    audio = repeated / "hit.wav"
    audio.write_bytes(b"audio")
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    plan_path = tmp_path / "nesting_plan.json"
    log_path = tmp_path / "nesting_log.json"
    write_organize_audit_report(report, report_path, quiet=True)
    build_nesting_plan_from_report(report_path, output_path=plan_path, quiet=True)
    review_organize_report(plan_path, approve_all=True, quiet=True)

    result = apply_nesting_plan(
        plan_path, db_path=tmp_db, log_path=log_path, require_reviewed=True, dry_run=False, quiet=True
    )

    flattened_audio = repeated.parent / "hit.wav"
    assert result.flattened == 1
    assert result.moved == 1
    assert flattened_audio.exists()
    assert not repeated.exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(flattened_audio)]

    undo = undo_nesting_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.undone == 1
    assert audio.exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(audio)]


def test_apply_and_undo_organize_report_updates_filesystem_and_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    source = root / "01 Pack"
    source.mkdir(parents=True)
    audio = source / "sound.wav"
    audio.write_bytes(b"audio")
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root)
    report_path = tmp_path / "organize.json"
    log_path = tmp_path / "organize_log.json"
    write_organize_audit_report(report, report_path, quiet=True)
    review_organize_report(report_path, approve_all=True, quiet=True)

    result = apply_organize_report(report_path, db_path=tmp_db, log_path=log_path, require_reviewed=True, quiet=True)

    target_audio = root / "Pack" / "sound.wav"
    assert result.renamed == 1
    assert target_audio.exists()
    assert not audio.exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(target_audio)]

    undo = undo_organize_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.undone == 1
    assert audio.exists()
