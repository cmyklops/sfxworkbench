"""Tests for TUI/GUI shared operation actions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.models import UcsCatalog, UcsCatalogProvenance, UcsEntry
from sfxworkbench.scan import scan_library
from sfxworkbench.tui_actions import (
    ActionResult,
    apply_dedupe_plan_action,
    apply_delete_plan_action,
    apply_nesting_action,
    apply_pack_plan_action,
    apply_rename_action,
    apply_tag_plan_action,
    apply_tag_plan_and_build_embedded_plan_action,
    approve_dedupe_plan_action,
    approve_organize_action,
    approve_tag_plan_action,
    build_dedupe_plan_action,
    build_delete_plan_action,
    clean_action,
    full_audit_action,
    operation_report_dir,
    organize_audit_action,
    pack_audit_action,
    pack_plan_action,
    rename_preview_action,
    scan_action,
    tag_plan_action,
    write_action_history,
)


def _sample_ucs_catalog() -> UcsCatalog:
    return UcsCatalog(
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
        entries=[
            UcsEntry(cat_short="AMB", category="AMBIENCE", subcategory="RAIN", cat_id="AMBRain"),
        ],
    )


def _write_sample_ucs_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "Category,SubCategory,CatID,CatShort,Explanations,Synonyms - Comma Separated",
                'AMBIENCE,RAIN,AMBRain,AMB,"Rain ambience.","Rain, Weather"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_tui_action_runner_scan_audit_and_clean_preview(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"

    scan = scan_action(tmp_library, tmp_db)
    audit = full_audit_action(tmp_library, tmp_db, report_dir)
    clean = clean_action(tmp_library, report_dir, apply=False)

    assert scan.ok
    assert "Quick-indexed" in scan.message
    assert audit.ok or audit.status == "error"  # Missing UCS catalog is reported but not a crash.
    assert audit.output_path == str(report_dir)
    assert (report_dir / "audit_bundle.json").exists()
    assert clean.ok
    assert clean.output_path is not None
    assert Path(clean.output_path).exists()
    assert clean.details is not None
    assert clean.details["removed_files"] or clean.details["removed_dirs"]


def test_tui_long_actions_report_progress(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    audit_events: list[tuple[str, int, int | None, str]] = []
    clean_events: list[tuple[str, int, int | None, str]] = []
    rename_events: list[tuple[str, int, int | None, str]] = []

    audit = full_audit_action(
        tmp_library,
        tmp_db,
        report_dir,
        progress_callback=lambda phase, completed, total, message: audit_events.append(
            (phase, completed, total, message)
        ),
    )
    clean = clean_action(
        tmp_library,
        report_dir,
        apply=False,
        progress_callback=lambda phase, completed, total, message: clean_events.append(
            (phase, completed, total, message)
        ),
    )
    rename = rename_preview_action(
        tmp_library,
        report_dir,
        progress_callback=lambda phase, completed, total, message: rename_events.append(
            (phase, completed, total, message)
        ),
    )

    assert audit.ok or audit.status == "error"
    assert clean.ok
    assert rename.ok
    assert any(event[0] == "scanning" for event in audit_events)
    assert any(event[0] == "auditing" for event in audit_events)
    assert any(event[0] == "walking" for event in clean_events)
    assert clean_events[-1][0] == "preview"
    assert any(event[0] == "walking" for event in rename_events)
    assert any(event[0] == "planning" for event in rename_events)
    assert rename_events[-1][0] == "preview"


def test_tui_pack_plan_action_reports_progress(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    pack_a = tmp_library / "Pack A"
    pack_b = tmp_library / "Pack B"
    pack_a.mkdir()
    pack_b.mkdir()
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_a / "AMB_RAIN_01.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_a / "AMB_RAIN_02.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_b / "AMB_RAIN_01.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_b / "AMB_RAIN_02.wav")
    scan_library(tmp_library, tmp_db, skip_hash=False, quiet=True)
    report_dir = tmp_path / "reports"
    events: list[tuple[str, int, int | None, str]] = []

    audit = pack_audit_action(tmp_library, tmp_db, report_dir)
    plan = pack_plan_action(
        report_dir,
        progress_callback=lambda phase, completed, total, message: events.append(
            (phase, completed, total, message)
        ),
    )

    assert audit.ok
    assert plan.ok
    assert any(event[0] == "planning" for event in events)
    assert any(event[0] == "writing_report" for event in events)
    assert events[-1][0] == "complete"


def test_tui_pack_apply_action_reports_progress(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    pack_a = tmp_library / "Pack A"
    pack_b = tmp_library / "Pack B"
    pack_a.mkdir()
    pack_b.mkdir()
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_a / "AMB_RAIN_01.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_a / "AMB_RAIN_02.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_b / "AMB_RAIN_01.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_b / "AMB_RAIN_02.wav")
    scan_library(tmp_library, tmp_db, skip_hash=False, quiet=True)
    report_dir = tmp_path / "reports"
    events: list[tuple[str, int, int | None, str]] = []

    audit = pack_audit_action(tmp_library, tmp_db, report_dir)
    plan = pack_plan_action(report_dir)
    apply = apply_pack_plan_action(
        tmp_db,
        report_dir,
        progress_callback=lambda phase, completed, total, message: events.append(
            (phase, completed, total, message)
        ),
    )

    assert audit.ok
    assert plan.ok
    assert apply.ok
    assert any(event[0] == "validating" for event in events)
    assert any(event[0] == "applying" for event in events)
    assert any(event[0] == "writing_log" for event in events)
    assert events[-1][0] == "complete"


def test_tui_pack_apply_partial_success_is_applied_status(
    tmp_library: Path, tmp_db: Path, tmp_path: Path
) -> None:
    pack_a = tmp_library / "Pack A"
    pack_b = tmp_library / "Pack B"
    pack_a.mkdir()
    pack_b.mkdir()
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_a / "AMB_RAIN_01.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_a / "AMB_RAIN_02.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_b / "AMB_RAIN_01.wav")
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", pack_b / "AMB_RAIN_02.wav")
    scan_library(tmp_library, tmp_db, skip_hash=False, quiet=True)
    report_dir = tmp_path / "reports"

    audit = pack_audit_action(tmp_library, tmp_db, report_dir)
    plan = pack_plan_action(report_dir)
    plan_path = report_dir / "pack_consolidation_plan.json"
    payload = json.loads(plan_path.read_text())
    assert payload["entries"]
    missing_entry = dict(payload["entries"][0])
    missing_entry["folder_path"] = str(tmp_library / "Missing Pack")
    payload["entries"].append(missing_entry)
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    apply = apply_pack_plan_action(tmp_db, report_dir)

    assert audit.ok
    assert plan.ok
    assert apply.status == "applied"
    assert apply.ok
    assert apply.errors
    assert apply.details is not None
    assert apply.details["quarantined"] >= 1


def test_tui_scan_action_reports_cancelled_status(tmp_library: Path, tmp_db: Path) -> None:
    cancel = False

    def progress(phase: str, completed: int, total: int | None, message: str) -> None:
        nonlocal cancel
        _ = total, message
        if phase == "scanning" and completed >= 1:
            cancel = True

    result = scan_action(
        tmp_library,
        tmp_db,
        progress_callback=progress,
        cancel_requested=lambda: cancel,
    )

    assert result.status == "cancelled"


def test_tui_declutter_folder_cleanup_actions_write_reviewable_reports(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "01 Pack").mkdir(parents=True)
    report_dir = tmp_path / "reports"

    preview = organize_audit_action(library, report_dir)
    approve = approve_organize_action(report_dir)

    assert preview.ok
    assert preview.output_path == str(report_dir / "organize_report.json")
    assert (report_dir / "organize_report.json").exists()
    assert approve.ok


def test_tui_apply_name_cleanup_applies_valid_entries_when_plan_has_errors(tmp_path: Path, tmp_db: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    source = tmp_path / "library" / "bad name.wav"
    target = tmp_path / "library" / "bad_name.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    plan_path = report_dir / "portable_rename_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-15T00:00:00+00:00",
                "root": str(source.parent),
                "pattern": "portable",
                "entries": [
                    {
                        "old_path": str(source),
                        "new_path": str(target),
                        "old_filename": source.name,
                        "new_filename": target.name,
                        "issue_fixes": ["space"],
                    }
                ],
                "errors": [{"path": str(source.parent / "blocked.wav"), "error": "target exists"}],
            }
        )
    )

    result = apply_rename_action(tmp_db, report_dir)

    assert result.status == "applied"
    assert "Renamed 1 path(s), skipped 1 issue(s)." in result.message
    assert target.exists()
    assert result.output_path is not None
    assert Path(result.output_path).parent == report_dir / "apply_logs"


def test_tui_apply_nesting_applies_valid_entries_when_plan_has_errors(tmp_path: Path, tmp_db: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    root = tmp_path / "library"
    source = root / "Pack" / "Pack"
    target = source.parent
    old_file = source / "hit.wav"
    new_file = target / "hit.wav"
    source.mkdir(parents=True)
    old_file.write_bytes(b"audio")
    plan_path = report_dir / "nesting_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-15T00:00:00+00:00",
                "tool_version": "test",
                "root": str(root),
                "source_report": str(report_dir / "redundant_nesting_report.json"),
                "entries": [
                    {
                        "source_path": str(source),
                        "target_path": str(target),
                        "kind": "repeated_folder_name",
                        "action": "flatten_child_into_parent",
                        "reason": "folder name repeats its parent",
                        "audio_files": 1,
                        "moves": [{"old_path": str(old_file), "new_path": str(new_file), "path_type": "file"}],
                    }
                ],
                "errors": [{"path": str(root / "Other"), "error": "target exists"}],
            }
        )
    )

    result = apply_nesting_action(tmp_db, report_dir)

    assert result.status == "applied"
    assert "Flattened 1 nested folder(s), moved 1 path(s), skipped 1 issue(s)." in result.message
    assert new_file.exists()
    assert not source.exists()


def test_tui_action_runner_dedupe_plan_review_apply(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    duplicate = tmp_library / "sounds" / "AMB_RAIN_COPY.wav"
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", duplicate)
    scan_library(tmp_library, tmp_db, skip_hash=False, quiet=True)
    report_dir = tmp_path / "reports"

    build = build_dedupe_plan_action(tmp_db, report_dir)
    approve = approve_dedupe_plan_action(report_dir)
    apply = apply_dedupe_plan_action(tmp_db, report_dir)

    assert build.ok
    assert approve.ok
    assert apply.ok
    assert apply.details is not None
    assert apply.details["quarantined"] >= 1
    assert "Destination:" in apply.message
    assert Path(apply.details["quarantine_dir"]).parent == tmp_library
    delete = build_delete_plan_action(report_dir)
    assert delete.ok
    assert delete.details is not None
    assert delete.details["summary"]["candidate_entries"] >= 1


def test_tui_permanent_delete_plan_and_apply_from_quarantine_log(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    apply_log_dir = report_dir / "apply_logs"
    apply_log_dir.mkdir(parents=True)
    quarantined = report_dir / "sfxworkbench_quarantine_20260512_120000" / "old_pack"
    quarantined.mkdir(parents=True)
    (quarantined / "hit.wav").write_bytes(b"audio")
    source_log = apply_log_dir / "pack_quarantine_log_20260512_120000.json"
    source_log.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "folder_path": str(tmp_path / "library" / "old_pack"),
                        "quarantine_path": str(quarantined),
                    }
                ],
            }
        )
    )

    plan = build_delete_plan_action(report_dir)
    # Apply auto-approves any pending entries (the legacy "Approve" button is
    # rolled into "Apply"), so a single click is enough to remove approved
    # quarantined paths.
    applied = apply_delete_plan_action(report_dir)

    assert plan.ok
    assert plan.output_path == str(report_dir / "delete_plan.json")
    assert "1 file" in plan.message  # quarantine folder contains one file
    assert applied.ok
    assert applied.details is not None
    assert applied.details["deleted"] == 1
    assert not quarantined.exists()


def test_tui_permanent_delete_plan_counts_files_inside_quarantine_folders(tmp_path: Path) -> None:
    """A quarantine directory containing N files reports N files, not 1 entry."""
    report_dir = tmp_path / "reports"
    quarantined = report_dir / "wavwarden_quarantine_20260513_010000"
    quarantined.mkdir(parents=True)
    (quarantined / "a.wav").write_bytes(b"aa")
    (quarantined / "b.wav").write_bytes(b"bbb")
    nested = quarantined / "nested"
    nested.mkdir()
    (nested / "c.wav").write_bytes(b"cccc")

    plan = build_delete_plan_action(report_dir)

    assert plan.ok
    assert plan.details is not None
    assert plan.details["summary"]["candidate_entries"] == 1
    assert plan.details["summary"]["directory_entries"] == 1
    assert plan.details["summary"]["files_planned"] == 3
    assert plan.details["summary"]["bytes_planned"] == 2 + 3 + 4
    assert plan.details["entries"][0]["file_count"] == 3
    assert "3 file" in plan.message


def test_tui_permanent_delete_plan_includes_every_quarantine_log(tmp_path: Path) -> None:
    """The plan should surface all quarantined paths, not just those from the latest log."""
    report_dir = tmp_path / "reports"
    apply_log_dir = report_dir / "apply_logs"
    apply_log_dir.mkdir(parents=True)
    first_dir = report_dir / "sfxworkbench_dedupe_quarantine_20260510_100000"
    second_dir = report_dir / "sfxworkbench_quarantine_20260512_120000"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "dupe.wav").write_bytes(b"01")
    (second_dir / "pack.wav").write_bytes(b"0123")
    (apply_log_dir / "dedupe_log_20260510_100000.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [{"path": "/lib/a.wav", "quarantine_path": str(first_dir / "dupe.wav")}],
            }
        )
    )
    (apply_log_dir / "pack_log_20260512_120000.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [{"folder_path": "/lib/old", "quarantine_path": str(second_dir / "pack.wav")}],
            }
        )
    )

    plan = build_delete_plan_action(report_dir)

    assert plan.ok
    assert plan.details is not None
    assert plan.details["summary"]["candidate_entries"] == 2
    assert plan.details["summary"]["bytes_planned"] == 6
    paths = {entry["path"] for entry in plan.details["entries"]}
    assert paths == {str(first_dir / "dupe.wav"), str(second_dir / "pack.wav")}


def test_tui_permanent_delete_plan_ignores_generated_combined_logs(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    apply_log_dir = report_dir / "apply_logs"
    apply_log_dir.mkdir(parents=True)
    real = report_dir / "sfxworkbench_dedupe_quarantine_20260510_100000" / "dupe.wav"
    stale = report_dir / "stale-from-old-combined-log.wav"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"01")
    stale.write_bytes(b"stale")
    (apply_log_dir / "dedupe_log_20260510_100000.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [{"path": "/lib/a.wav", "quarantine_path": str(real)}],
            }
        )
    )
    (apply_log_dir / "combined_quarantine_log_20260511_100000.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": "combined_quarantine_log",
                "entries": [{"path": "/lib/stale.wav", "quarantine_path": str(stale)}],
            }
        )
    )

    plan = build_delete_plan_action(report_dir)

    assert plan.ok
    assert plan.details is not None
    assert plan.details["summary"]["candidate_entries"] == 1
    assert plan.details["entries"][0]["path"] == str(real)


def test_tui_permanent_delete_plan_from_legacy_quarantine_folder(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    quarantined = report_dir / "wavwarden_quarantine_20260508_044220"
    scan_errors = report_dir / "wavwarden_scan_error_quarantine_20260508_045619"
    quarantined.mkdir(parents=True)
    scan_errors.mkdir()
    (quarantined / "Users" / "mattwesdock" / "CommercialLibraries").mkdir(parents=True)
    (quarantined / "Users" / "mattwesdock" / "CommercialLibraries" / "old.wav").write_bytes(b"audio")
    (scan_errors / "bad.wav").write_bytes(b"audio")

    plan = build_delete_plan_action(report_dir)

    assert plan.ok
    assert plan.output_path == str(report_dir / "delete_plan.json")
    assert plan.details is not None
    assert plan.details["summary"]["candidate_entries"] == 2
    assert {entry["path"] for entry in plan.details["entries"]} == {str(quarantined), str(scan_errors)}
    assert list((report_dir / "apply_logs").glob("combined_quarantine_log_*.json"))


def test_tui_action_runner_db_only_metadata_apply(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    conn = get_connection(tmp_db)
    row = conn.execute(
        "SELECT id, size_bytes, mtime, md5 FROM files WHERE path = ?",
        (str(target),),
    ).fetchone()
    conn.close()
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    plan = {
        "schema_version": 1,
        "generated_at": "2026-05-12T00:00:00+00:00",
        "tool": "sfxworkbench",
        "tool_version": "test",
        "root": str(tmp_library),
        "db_path": str(tmp_db),
        "target": "db",
        "summary": {"files_considered": 1, "candidate_entries": 1},
        "entries": [
            {
                "entry_id": 1,
                "file_id": row["id"],
                "path": str(target),
                "filename": target.name,
                "size_bytes": row["size_bytes"],
                "mtime": row["mtime"],
                "md5": row["md5"],
                "field": "description",
                "action": "add",
                "existing_values": [],
                "proposed_value": "Steady Rain",
                "source": "test",
                "method": "manual",
                "confidence": 1.0,
                "evidence": ["test"],
                "review_status": "pending",
            }
        ],
        "errors": [],
    }
    (report_dir / "metadata_tag_plan.json").write_text(json.dumps(plan))

    approve = approve_tag_plan_action(report_dir)
    apply = apply_tag_plan_action(tmp_db, report_dir)

    assert approve.ok
    assert apply.ok
    conn = get_connection(tmp_db)
    try:
        stored = conn.execute("SELECT value FROM accepted_tags WHERE field = 'description'").fetchone()
    finally:
        conn.close()
    assert stored["value"] == "Steady Rain"


def test_tui_apply_tags_and_plan_embedded_chains_both_steps(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    """One click should commit the tag plan and produce the embedded write plan."""
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    conn = get_connection(tmp_db)
    row = conn.execute(
        "SELECT id, size_bytes, mtime, md5 FROM files WHERE path = ?",
        (str(target),),
    ).fetchone()
    conn.close()
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    plan = {
        "schema_version": 1,
        "generated_at": "2026-05-13T00:00:00+00:00",
        "tool": "sfxworkbench",
        "tool_version": "test",
        "root": str(tmp_library),
        "db_path": str(tmp_db),
        "target": "db",
        "summary": {"files_considered": 1, "candidate_entries": 1, "add_entries": 1},
        "entries": [
            {
                "entry_id": 1,
                "file_id": row["id"],
                "path": str(target),
                "filename": target.name,
                "size_bytes": row["size_bytes"],
                "mtime": row["mtime"],
                "md5": row["md5"],
                "field": "description",
                "action": "add",
                "existing_values": [],
                "proposed_value": "Steady Rain",
                "source": "test",
                "method": "manual",
                "confidence": 1.0,
                "evidence": ["test"],
                "review_status": "approved",
            }
        ],
        "errors": [],
    }
    (report_dir / "metadata_tag_plan.json").write_text(json.dumps(plan))

    result = apply_tag_plan_and_build_embedded_plan_action(
        tmp_db,
        report_dir,
        root=tmp_library,
    )

    # DB tag landed regardless of how the embedded-plan probe went.
    conn = get_connection(tmp_db)
    try:
        stored = conn.execute("SELECT value FROM accepted_tags WHERE field = 'description'").fetchone()
    finally:
        conn.close()
    assert stored["value"] == "Steady Rain"
    # Embedded plan was written next to the tag plan.
    assert (report_dir / "metadata_write_plan.json").exists()
    # Result carries both stages' messages and detail blocks.
    assert "DB-only metadata tag" in result.message
    assert "embedded metadata plan" in result.message
    assert result.details is not None
    assert "apply" in result.details and "plan" in result.details
    assert result.action == "tag_apply_and_embedded_plan"


def test_tui_apply_tags_and_plan_embedded_short_circuits_when_db_apply_fails(tmp_path: Path) -> None:
    """If the DB apply step errors, the file-probe step must be skipped."""
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    # No metadata_tag_plan.json exists, so apply_tag_plan_action returns an error result.

    result = apply_tag_plan_and_build_embedded_plan_action(Path("/nonexistent/db"), report_dir)

    assert not result.ok
    # The combined action surfaces the underlying action name so the failure
    # is attributed to the apply step, not to the chained build step.
    assert result.action == "tag_apply"
    assert not (report_dir / "metadata_write_plan.json").exists()


def test_tui_apply_tag_plan_auto_approves_pending_when_user_skips_approve(
    tmp_library: Path, tmp_db: Path, tmp_path: Path
) -> None:
    """The merged Apply button auto-approves any pending entries before writing."""
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    conn = get_connection(tmp_db)
    row = conn.execute(
        "SELECT id, size_bytes, mtime, md5 FROM files WHERE path = ?",
        (str(target),),
    ).fetchone()
    conn.close()
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    plan = {
        "schema_version": 1,
        "generated_at": "2026-05-13T00:00:00+00:00",
        "tool": "sfxworkbench",
        "tool_version": "test",
        "root": str(tmp_library),
        "db_path": str(tmp_db),
        "target": "db",
        "summary": {"files_considered": 1, "candidate_entries": 1, "add_entries": 1},
        "entries": [
            {
                "entry_id": 1,
                "file_id": row["id"],
                "path": str(target),
                "filename": target.name,
                "size_bytes": row["size_bytes"],
                "mtime": row["mtime"],
                "md5": row["md5"],
                "field": "description",
                "action": "add",
                "existing_values": [],
                "proposed_value": "Steady Rain",
                "source": "test",
                "method": "manual",
                "confidence": 1.0,
                "evidence": ["test"],
                "review_status": "pending",
            }
        ],
        "errors": [],
    }
    plan_path = report_dir / "metadata_tag_plan.json"
    plan_path.write_text(json.dumps(plan))

    apply = apply_tag_plan_action(tmp_db, report_dir)

    assert apply.ok
    written = json.loads(plan_path.read_text())
    assert written["entries"][0]["review_status"] == "approved"
    conn = get_connection(tmp_db)
    try:
        stored = conn.execute("SELECT value FROM accepted_tags WHERE field = 'description'").fetchone()
    finally:
        conn.close()
    assert stored["value"] == "Steady Rain"


def test_tui_apply_tag_plan_preserves_user_rejections_when_some_already_approved(
    tmp_library: Path, tmp_db: Path, tmp_path: Path
) -> None:
    """If at least one entry is already approved, Apply must not over-stamp existing rejections."""
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    conn = get_connection(tmp_db)
    row = conn.execute(
        "SELECT id, size_bytes, mtime, md5 FROM files WHERE path = ?",
        (str(target),),
    ).fetchone()
    conn.close()
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    base_entry = {
        "file_id": row["id"],
        "path": str(target),
        "filename": target.name,
        "size_bytes": row["size_bytes"],
        "mtime": row["mtime"],
        "md5": row["md5"],
        "action": "add",
        "existing_values": [],
        "source": "test",
        "method": "manual",
        "confidence": 1.0,
        "evidence": ["test"],
    }
    plan = {
        "schema_version": 1,
        "generated_at": "2026-05-13T00:00:00+00:00",
        "tool": "sfxworkbench",
        "tool_version": "test",
        "root": str(tmp_library),
        "db_path": str(tmp_db),
        "target": "db",
        "summary": {"files_considered": 1, "candidate_entries": 2, "add_entries": 2},
        "entries": [
            {
                **base_entry,
                "entry_id": 1,
                "field": "description",
                "proposed_value": "Approved Value",
                "review_status": "approved",
            },
            {
                **base_entry,
                "entry_id": 2,
                "field": "title",
                "proposed_value": "Rejected Value",
                "review_status": "rejected",
            },
        ],
        "errors": [],
    }
    plan_path = report_dir / "metadata_tag_plan.json"
    plan_path.write_text(json.dumps(plan))

    apply = apply_tag_plan_action(tmp_db, report_dir)

    assert apply.ok
    written = json.loads(plan_path.read_text())
    statuses = {entry["entry_id"]: entry["review_status"] for entry in written["entries"]}
    assert statuses == {1: "approved", 2: "rejected"}  # rejection survived


def test_tui_tag_plan_falls_back_when_ucs_catalog_is_missing(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SFXWORKBENCH_UCS_SOURCE", raising=False)
    monkeypatch.setattr("sfxworkbench.ucs_catalog.default_cache_path", lambda: tmp_path / "missing_ucs_catalog.json")
    monkeypatch.setattr("sfxworkbench.tag_suggest.load_catalog", lambda path=None: None)
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    report_dir = tmp_path / "reports"

    result = tag_plan_action(tmp_library, tmp_db, report_dir)

    assert result.ok
    assert "UCS catalog not loaded" in result.message
    assert result.details is not None
    assert result.details["used_ucs_catalog"] is False
    assert "warning" not in result.details
    assert (report_dir / "metadata_tag_plan.json").exists()


def test_tui_tag_plan_imports_ucs_catalog_before_suggesting(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "sfxworkbench" / "ucs_catalog.json"
    monkeypatch.delenv("SFXWORKBENCH_UCS_DATA", raising=False)
    monkeypatch.delenv("SFXWORKBENCH_UCS_SOURCE", raising=False)
    monkeypatch.setattr("sfxworkbench.ucs_catalog.default_cache_path", lambda: cache)
    report_dir = tmp_path / "reports"
    _write_sample_ucs_csv(report_dir / "_categorylist.csv")
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    result = tag_plan_action(tmp_library, tmp_db, report_dir)

    assert result.ok
    assert cache.exists()
    assert "Imported UCS catalog" in result.message
    assert result.details is not None
    assert result.details["used_ucs_catalog"] is True
    assert result.details["ucs_catalog_imported"] is True
    assert result.details["ucs_catalog_entries"] == 1
    assert any(entry["source"] == "ucs_catalog" for entry in result.details["entries"])


def test_tui_tag_plan_excludes_take_numbers_by_default(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("sfxworkbench.tag_suggest.load_catalog", lambda path=None: _sample_ucs_catalog())
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    report_dir = tmp_path / "reports"

    result = tag_plan_action(tmp_library, tmp_db, report_dir)

    assert result.ok
    assert result.details is not None
    assert "take_number" not in result.details["fields"]
    assert not any(entry["field"] == "take_number" for entry in result.details["entries"])


def test_tui_tag_plan_can_cancel_during_suggestion_generation(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SFXWORKBENCH_UCS_SOURCE", raising=False)
    monkeypatch.setattr("sfxworkbench.ucs_catalog.default_cache_path", lambda: tmp_path / "missing_ucs_catalog.json")
    monkeypatch.setattr("sfxworkbench.tag_suggest.load_catalog", lambda path=None: None)
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    report_dir = tmp_path / "reports"

    result = tag_plan_action(tmp_library, tmp_db, report_dir, cancel_requested=lambda: True)

    assert result.status == "cancelled"
    assert "cancelled" in result.message


def test_tui_tag_plan_keeps_review_grade_ucs_stem_when_catalog_loaded(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("sfxworkbench.tag_suggest.load_catalog", lambda path=None: _sample_ucs_catalog())
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    report_dir = tmp_path / "reports"

    result = tag_plan_action(tmp_library, tmp_db, report_dir)

    assert result.ok
    assert result.details is not None
    assert result.details["used_ucs_catalog"] is True
    assert result.details["min_confidence"] == 0.75
    assert any(entry["source"] == "ucs_stem" for entry in result.details["entries"])


def test_tui_tag_plan_synonyms_use_review_confidence_floor_with_catalog(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("sfxworkbench.tag_suggest.load_catalog", lambda path=None: _sample_ucs_catalog())
    shutil.copy2(tmp_library / "sounds" / "AMB_RAIN_01.wav", tmp_library / "sounds" / "Car Crash 01.wav")
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    report_dir = tmp_path / "reports"

    result = tag_plan_action(tmp_library, tmp_db, report_dir, include_synonyms=True)

    assert result.ok
    assert result.details is not None
    assert result.details["used_ucs_catalog"] is True
    assert result.details["min_confidence"] == 0.62
    assert result.details["synonym_limit"] == 8
    assert result.details["synonym_depth"] == 0
    assert any(entry["source"] == "synonym" for entry in result.details["entries"])


def test_tui_operation_report_dir_prefers_explicit_report_path(tmp_db: Path, tmp_path: Path) -> None:
    explicit = tmp_path / "reports"

    assert operation_report_dir(tmp_db, library_path="/tmp/library", report_paths=[explicit]) == explicit


def test_tui_action_history_is_written_for_any_action(tmp_path: Path) -> None:
    result = ActionResult(
        action="scan",
        status="ok",
        message="Indexed 3 file(s).",
        details={"scanned": 3, "files": [{"path": "large-detail-is-not-copied.wav"}]},
    )

    history_path = write_action_history(result, tmp_path)
    second_history_path = write_action_history(result, tmp_path)
    payload = json.loads(history_path.read_text())

    assert history_path.parent == tmp_path / "action_history"
    assert second_history_path != history_path
    assert payload["command"] == "tui_action"
    assert payload["action"] == "scan"
    assert payload["details"] == {"scanned": 3}
