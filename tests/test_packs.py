"""Tests for pack/folder duplicate reports."""

import json
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.packs import (
    apply_pack_plan,
    audit_packs,
    build_pack_plan,
    review_pack_plan,
    undo_pack_log,
    write_pack_audit_report,
)


def _seed_files(tmp_db: Path, files: list[dict]) -> None:
    conn = get_connection(tmp_db)
    for f in files:
        path = Path(f["path"])
        conn.execute(
            """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(path),
                path.name,
                path.stem,
                path.suffix,
                f.get("size", 100),
                0.0,
                f.get("md5"),
                "2026-01-01T00:00:00",
            ),
        )
    conn.commit()
    conn.close()


def _write_pack_files(files: list[dict]) -> None:
    for f in files:
        path = Path(f["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * f.get("size", 100))


def test_pack_audit_finds_exact_duplicate_folders(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    pack_a = root / "Vendor" / "Pack"
    pack_b = root / "Imports" / "Pack Copy"
    pack_a.mkdir(parents=True)
    pack_b.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": pack_a / "one.wav", "md5": "A", "size": 10},
            {"path": pack_a / "two.wav", "md5": "B", "size": 20},
            {"path": pack_b / "one.wav", "md5": "A", "size": 10},
            {"path": pack_b / "two.wav", "md5": "B", "size": 20},
        ],
    )

    report = audit_packs(root, tmp_db)

    assert report.summary.exact_duplicate_groups == 1
    assert report.summary.exact_duplicate_folders == 2
    group = report.exact_groups[0]
    assert group.file_count == 2
    assert group.total_bytes == 30
    assert group.same_relative_paths is True
    assert [Path(folder.path).name for folder in group.folders] == ["Pack Copy", "Pack"]


def test_pack_audit_finds_partial_overlap(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    pack_a = root / "Vendor" / "Pack v1"
    pack_b = root / "Vendor" / "Pack v2"
    pack_a.mkdir(parents=True)
    pack_b.mkdir(parents=True)
    _seed_files(
        tmp_db,
        [
            {"path": pack_a / "one.wav", "md5": "A", "size": 10},
            {"path": pack_a / "two.wav", "md5": "B", "size": 10},
            {"path": pack_a / "three.wav", "md5": "C", "size": 10},
            {"path": pack_b / "one.wav", "md5": "A", "size": 10},
            {"path": pack_b / "two.wav", "md5": "B", "size": 10},
            {"path": pack_b / "three.wav", "md5": "C", "size": 10},
            {"path": pack_b / "four.wav", "md5": "D", "size": 10},
        ],
    )

    report = audit_packs(root, tmp_db, overlap_threshold=0.95)

    assert report.summary.exact_duplicate_groups == 0
    assert report.summary.overlap_candidates == 1
    candidate = report.overlap_candidates[0]
    assert candidate.shared_files == 3
    assert candidate.shared_bytes == 30
    assert candidate.smaller_folder_coverage == 1.0
    assert candidate.larger_folder_coverage == 0.75


def test_pack_audit_counts_hashless_files_and_ignores_them(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "A" / "one.wav", "md5": "A"},
            {"path": root / "A" / "two.wav", "md5": None},
            {"path": root / "B" / "one.wav", "md5": "A"},
        ],
    )

    report = audit_packs(root, tmp_db, min_files=1)

    assert report.summary.indexed_files_considered == 2
    assert report.summary.files_without_hash == 1


def test_pack_audit_is_deterministic_except_timestamp(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "B" / "two.wav", "md5": "B"},
            {"path": root / "A" / "one.wav", "md5": "A"},
            {"path": root / "C" / "one.wav", "md5": "A"},
            {"path": root / "C" / "two.wav", "md5": "B"},
            {"path": root / "A" / "two.wav", "md5": "B"},
        ],
    )

    first = audit_packs(root, tmp_db).model_dump(exclude={"generated_at"})
    second = audit_packs(root, tmp_db).model_dump(exclude={"generated_at"})

    assert first == second


def test_pack_audit_is_report_only_and_filters_root(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "A" / "one.wav", "md5": "A"},
            {"path": root / "B" / "one.wav", "md5": "A"},
            {"path": other / "A" / "one.wav", "md5": "A"},
        ],
    )
    before = get_connection(tmp_db).execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"]

    report = audit_packs(root, tmp_db, min_files=1)
    after = get_connection(tmp_db).execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"]

    assert before == after
    assert report.summary.indexed_files_considered == 2
    assert report.summary.exact_duplicate_groups == 1


def test_write_pack_audit_report(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    report = audit_packs(root, tmp_db)
    out = tmp_path / "reports" / "packs.json"

    write_pack_audit_report(report, out, quiet=True)

    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["summary"]["folders_analyzed"] == 0


def test_pack_plan_reviews_applies_and_undoes_exact_duplicate_folder(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": keep / "two.wav", "md5": "B", "size": 20},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "two.wav", "md5": "B", "size": 20},
    ]
    _write_pack_files(files)
    _seed_files(tmp_db, files)
    report_path = tmp_path / "pack_report.json"
    plan_path = tmp_path / "pack_plan.json"
    log_path = tmp_path / "pack_log.json"
    quarantine_dir = tmp_path / "quarantine"
    write_pack_audit_report(audit_packs(root, tmp_db), report_path, quiet=True)

    plan = build_pack_plan(report_path, output_path=plan_path, quiet=True)

    assert plan.summary.quarantine_entries == 1
    assert plan.entries[0].folder_path == str(duplicate)
    assert plan.entries[0].keep_folder_path == str(keep)
    assert plan.entries[0].action == "quarantine_folder"

    review = review_pack_plan(plan_path, approve_all=True, quiet=True)
    assert review.approved_groups == 1

    dry_run = apply_pack_plan(plan_path, require_reviewed=True, dry_run=True, quiet=True)
    assert dry_run.quarantined == 1
    assert duplicate.exists()

    result = apply_pack_plan(
        plan_path,
        db_path=tmp_db,
        require_reviewed=True,
        dry_run=False,
        quarantine_dir=quarantine_dir,
        log_path=log_path,
        quiet=True,
    )

    assert result.quarantined == 1
    assert result.errors == []
    assert not duplicate.exists()
    assert log_path.exists()
    quarantined_path = Path(json.loads(log_path.read_text())["entries"][0]["quarantine_path"])
    assert quarantined_path.exists()
    conn = get_connection(tmp_db)
    moved_rows = conn.execute("SELECT path FROM files WHERE path LIKE ?", (str(quarantined_path) + "/%",)).fetchall()
    conn.close()
    assert len(moved_rows) == 2

    undo = undo_pack_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.restored == 1
    assert duplicate.exists()
    conn = get_connection(tmp_db)
    restored_rows = conn.execute("SELECT path FROM files WHERE path LIKE ?", (str(duplicate) + "/%",)).fetchall()
    conn.close()
    assert len(restored_rows) == 2


def test_pack_plan_marks_partial_overlap_review_only(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    pack_a = root / "Pack A"
    pack_b = root / "Pack B"
    files = [
        {"path": pack_a / "one.wav", "md5": "A", "size": 10},
        {"path": pack_a / "two.wav", "md5": "B", "size": 10},
        {"path": pack_a / "unique-a.wav", "md5": "C", "size": 10},
        {"path": pack_b / "one.wav", "md5": "A", "size": 10},
        {"path": pack_b / "two.wav", "md5": "B", "size": 10},
        {"path": pack_b / "unique-b.wav", "md5": "D", "size": 10},
    ]
    _seed_files(tmp_db, files)
    report_path = tmp_path / "pack_report.json"
    write_pack_audit_report(audit_packs(root, tmp_db, overlap_threshold=0.5), report_path, quiet=True)

    plan = build_pack_plan(report_path, quiet=True)

    assert plan.summary.quarantine_entries == 0
    assert plan.summary.review_entries == 1
    assert plan.entries[0].action == "review"
    assert plan.entries[0].reason.startswith("folder overlap is not complete")
