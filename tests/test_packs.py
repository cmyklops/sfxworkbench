"""Tests for pack/folder duplicate reports."""

import hashlib
import json
from pathlib import Path

from sfxworkbench.db import get_connection, path_scope_filter, path_scope_params
from sfxworkbench.packs import (
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


def _pack_plan_for_files(tmp_path: Path, tmp_db: Path, root: Path, files: list[dict]) -> Path:
    _write_pack_files(files)
    _seed_files(tmp_db, files)
    report_path = tmp_path / "pack_report.json"
    plan_path = tmp_path / "pack_plan.json"
    write_pack_audit_report(audit_packs(root, tmp_db, min_files=1), report_path, quiet=True)
    build_pack_plan(report_path, output_path=plan_path, quiet=True)
    return plan_path


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


def test_pack_audit_scopes_windows_style_paths(tmp_db: Path) -> None:
    conn = get_connection(tmp_db)
    conn.executemany(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("C:\\Lib\\A\\one.wav", "one.wav", "one", ".wav", 10, 0.0, "A", "2026"),
            ("C:\\Lib\\B\\one.wav", "one.wav", "one", ".wav", 10, 0.0, "A", "2026"),
            ("C:\\Lib2\\C\\one.wav", "one.wav", "one", ".wav", 10, 0.0, "A", "2026"),
        ],
    )
    conn.commit()
    conn.close()

    report = audit_packs(Path("c:/lib"), tmp_db, min_files=1)

    assert report.summary.indexed_files_considered == 2
    assert {Path(folder.path).name for group in report.exact_groups for folder in group.folders} == {"A", "B"}


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


def test_pack_audit_escapes_sql_like_wildcards_in_root(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "lib_a"
    sibling = tmp_path / "libXa"
    root.mkdir()
    sibling.mkdir()
    _seed_files(
        tmp_db,
        [
            {"path": root / "one.wav", "md5": "A"},
            {"path": sibling / "two.wav", "md5": "B"},
        ],
    )

    report = audit_packs(root, tmp_db, min_files=1)

    assert report.summary.indexed_files_considered == 1


def test_pack_plan_escapes_sql_like_wildcards_when_loading_folder_files(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    source = root / "B_Pack"
    wildcard_sibling = root / "BXPack"
    _seed_files(
        tmp_db,
        [
            {"path": keep / "one.wav", "md5": "A"},
            {"path": source / "one.wav", "md5": "A"},
            {"path": wildcard_sibling / "extra.wav", "md5": "C"},
        ],
    )
    report_path = tmp_path / "pack_report.json"
    write_pack_audit_report(audit_packs(root, tmp_db, min_files=1), report_path, quiet=True)

    plan = build_pack_plan(report_path, quiet=True)

    entry = next(entry for entry in plan.entries if entry.folder_path == str(source))
    assert [file.path for file in entry.files] == [str(source / "one.wav")]


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
    moved_rows = conn.execute(
        f"SELECT path FROM files WHERE {path_scope_filter()}",
        path_scope_params(quarantined_path),
    ).fetchall()
    conn.close()
    assert len(moved_rows) == 2

    undo = undo_pack_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.restored == 1
    assert duplicate.exists()
    conn = get_connection(tmp_db)
    restored_rows = conn.execute(
        f"SELECT path FROM files WHERE {path_scope_filter()}",
        path_scope_params(duplicate),
    ).fetchall()
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


def test_pack_plan_prefers_safe_folder_keep_and_ignores_protected_sources(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    safe = root / "Protected"
    protected_keep = safe / "A Pack"
    protected_duplicate = safe / "B Pack"
    duplicate = root / "Imports" / "C Pack"
    files = [
        {"path": protected_keep / "one.wav", "md5": "A", "size": 10},
        {"path": protected_duplicate / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    _write_pack_files(files)
    _seed_files(tmp_db, files)
    report_path = tmp_path / "pack_report.json"
    write_pack_audit_report(audit_packs(root, tmp_db, min_files=1), report_path, quiet=True)

    plan = build_pack_plan(report_path, safe_folders=[safe], quiet=True)

    assert plan.safe_folders == [str(safe.resolve())]
    assert plan.summary.quarantine_entries == 1
    assert plan.summary.ignored_entries >= 1
    assert plan.summary.protected_entries == 1
    quarantine_entry = next(entry for entry in plan.entries if entry.action == "quarantine_folder")
    protected_entry = next(entry for entry in plan.entries if entry.protected_by is not None)
    assert quarantine_entry.folder_path == str(duplicate)
    assert quarantine_entry.keep_folder_path == str(protected_keep)
    assert quarantine_entry.keep_protected_by == str(safe.resolve())
    assert protected_entry.folder_path == str(protected_duplicate)
    assert protected_entry.protected_by == str(safe.resolve())
    assert protected_entry.reason.startswith("source folder is inside safe folder")


def test_pack_plan_uses_config_safe_folder(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    safe = root / "Protected"
    protected_keep = safe / "A Pack"
    duplicate = root / "Imports" / "B Pack"
    files = [
        {"path": protected_keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    _write_pack_files(files)
    _seed_files(tmp_db, files)
    report_path = tmp_path / "pack_report.json"
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(safe)]}))
    write_pack_audit_report(audit_packs(root, tmp_db, min_files=1), report_path, quiet=True)

    plan = build_pack_plan(report_path, config_path=config_path, quiet=True)

    assert plan.safe_folders == [str(safe.resolve())]
    assert plan.entries[0].folder_path == str(duplicate)
    assert plan.entries[0].keep_folder_path == str(protected_keep)
    assert plan.entries[0].keep_protected_by == str(safe.resolve())


def test_pack_plan_uses_preferred_folder_for_exact_duplicate_keep(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    preferred = root / "Preferred"
    preferred_pack = preferred / "A Pack"
    duplicate = root / "Imports" / "B Pack"
    files = [
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
        {"path": preferred_pack / "one.wav", "md5": "A", "size": 10},
    ]
    _write_pack_files(files)
    _seed_files(tmp_db, files)
    report_path = tmp_path / "pack_report.json"
    write_pack_audit_report(audit_packs(root, tmp_db, min_files=1), report_path, quiet=True)

    plan = build_pack_plan(report_path, prefer_folders=[preferred], quiet=True)

    assert plan.preservation_priority["rules"] == [{"rule": "prefer_folder", "values": [str(preferred.resolve())]}]
    assert plan.entries[0].folder_path == str(duplicate)
    assert plan.entries[0].keep_folder_path == str(preferred_pack)
    assert plan.entries[0].keep_preservation_evidence == [{"rule": "prefer_folder", "value": str(preferred.resolve())}]


def test_pack_plan_does_not_quarantine_larger_overlap_to_save_safe_smaller_folder(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    safe = root / "Master"
    smaller = safe / "Pack v1"
    larger = root / "Imports" / "Pack v2"
    files = [
        {"path": smaller / "one.wav", "md5": "A", "size": 10},
        {"path": larger / "one.wav", "md5": "A", "size": 10},
        {"path": larger / "two.wav", "md5": "B", "size": 10},
    ]
    _write_pack_files(files)
    _seed_files(tmp_db, files)
    report_path = tmp_path / "pack_report.json"
    write_pack_audit_report(audit_packs(root, tmp_db, min_files=1, overlap_threshold=0.5), report_path, quiet=True)

    plan = build_pack_plan(report_path, safe_folders=[safe], quiet=True)

    overlap_entries = [entry for entry in plan.entries if entry.source_type == "pack_overlap"]
    assert overlap_entries[0].folder_path == str(smaller)
    assert overlap_entries[0].action == "ignore"
    assert overlap_entries[0].protected_by == str(safe.resolve())
    assert not any(entry.folder_path == str(larger) and entry.action == "quarantine_folder" for entry in plan.entries)


def test_pack_apply_refuses_cli_safe_folder_even_for_old_plan(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    review_pack_plan(plan_path, approve_all=True, quiet=True)

    result = apply_pack_plan(
        plan_path,
        db_path=tmp_db,
        safe_folders=[duplicate],
        require_reviewed=True,
        dry_run=False,
        quiet=True,
    )

    assert result.quarantined == 0
    assert duplicate.exists()
    assert result.errors == [
        {
            "path": str(duplicate),
            "safe_folder": str(duplicate.resolve()),
            "error": "source folder is protected by safe folder",
        }
    ]


def test_pack_apply_refuses_config_safe_folder_even_for_old_plan(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(duplicate)]}))
    review_pack_plan(plan_path, approve_all=True, quiet=True)

    result = apply_pack_plan(
        plan_path,
        db_path=tmp_db,
        config_path=config_path,
        require_reviewed=True,
        dry_run=False,
        quiet=True,
    )

    assert result.quarantined == 0
    assert duplicate.exists()
    assert result.errors[0]["safe_folder"] == str(duplicate.resolve())


def test_pack_apply_rejects_changed_size_before_quarantine(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    review_pack_plan(plan_path, approve_all=True, quiet=True)
    (duplicate / "one.wav").write_bytes(b"changed-size")

    result = apply_pack_plan(plan_path, require_reviewed=True, dry_run=False, quiet=True)

    assert result.quarantined == 0
    assert duplicate.exists()
    assert result.errors[0]["error"].startswith("size changed")


def test_pack_apply_rejects_changed_hash_before_quarantine(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    expected_hash = hashlib.md5(b"x" * 10).hexdigest()
    files = [
        {"path": keep / "one.wav", "md5": expected_hash, "size": 10},
        {"path": duplicate / "one.wav", "md5": expected_hash, "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    review_pack_plan(plan_path, approve_all=True, quiet=True)
    (duplicate / "one.wav").write_bytes(b"y" * 10)

    result = apply_pack_plan(plan_path, require_reviewed=True, dry_run=False, quiet=True)

    assert result.quarantined == 0
    assert duplicate.exists()
    assert result.errors == [{"path": str(duplicate / "one.wav"), "error": "md5 changed"}]


def test_pack_apply_rejects_missing_planned_file(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    review_pack_plan(plan_path, approve_all=True, quiet=True)
    (duplicate / "one.wav").unlink()

    result = apply_pack_plan(plan_path, require_reviewed=True, dry_run=False, quiet=True)

    assert result.quarantined == 0
    assert duplicate.exists()
    assert result.errors == [{"path": str(duplicate / "one.wav"), "error": "file does not exist"}]


def test_pack_apply_rejects_unplanned_indexed_file(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    review_pack_plan(plan_path, approve_all=True, quiet=True)
    extra = {"path": duplicate / "new.wav", "md5": "NEW", "size": 10}
    _write_pack_files([extra])
    _seed_files(tmp_db, [extra])

    result = apply_pack_plan(plan_path, db_path=tmp_db, require_reviewed=True, dry_run=False, quiet=True)

    assert result.quarantined == 0
    assert duplicate.exists()
    assert result.errors == [{"path": str(duplicate / "new.wav"), "error": "indexed file was not in plan"}]


def test_pack_apply_partial_approval_moves_only_approved_group(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate_b = root / "B Pack"
    duplicate_c = root / "C Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate_b / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate_c / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    review_pack_plan(plan_path, groups=[1], quiet=True)

    result = apply_pack_plan(
        plan_path,
        db_path=tmp_db,
        quarantine_dir=tmp_path / "quarantine",
        log_path=tmp_path / "pack_log.json",
        require_reviewed=True,
        dry_run=False,
        quiet=True,
    )

    assert result.quarantined == 1
    assert not duplicate_b.exists()
    assert duplicate_c.exists()
    assert result.errors == [{"path": str(duplicate_c), "error": "group 2 is not approved"}]


def test_pack_apply_uses_non_overwriting_quarantine_target(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    quarantine_dir = tmp_path / "quarantine"
    resolved_duplicate = duplicate.resolve()
    existing_target = quarantine_dir.joinpath(
        *(part for part in resolved_duplicate.parts if part not in (resolved_duplicate.anchor, "/"))
    )
    existing_target.mkdir(parents=True)
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    review_pack_plan(plan_path, approve_all=True, quiet=True)
    log_path = tmp_path / "pack_log.json"

    result = apply_pack_plan(
        plan_path,
        db_path=tmp_db,
        quarantine_dir=quarantine_dir,
        log_path=log_path,
        require_reviewed=True,
        dry_run=False,
        quiet=True,
    )

    quarantined_path = Path(json.loads(log_path.read_text())["entries"][0]["quarantine_path"])
    assert result.quarantined == 1
    assert existing_target.exists()
    assert quarantined_path.name == "B Pack__1"
    assert quarantined_path.exists()


def test_pack_apply_moves_non_indexed_sidecars_with_folder(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    keep = root / "A Pack"
    duplicate = root / "B Pack"
    files = [
        {"path": keep / "one.wav", "md5": "A", "size": 10},
        {"path": duplicate / "one.wav", "md5": "A", "size": 10},
    ]
    plan_path = _pack_plan_for_files(tmp_path, tmp_db, root, files)
    sidecar = duplicate / "notes.txt"
    sidecar.write_text("vendor notes")
    review_pack_plan(plan_path, approve_all=True, quiet=True)
    log_path = tmp_path / "pack_log.json"

    result = apply_pack_plan(
        plan_path,
        db_path=tmp_db,
        quarantine_dir=tmp_path / "quarantine",
        log_path=log_path,
        require_reviewed=True,
        dry_run=False,
        quiet=True,
    )

    quarantined_path = Path(json.loads(log_path.read_text())["entries"][0]["quarantine_path"])
    assert result.quarantined == 1
    assert (quarantined_path / "notes.txt").read_text() == "vendor notes"
