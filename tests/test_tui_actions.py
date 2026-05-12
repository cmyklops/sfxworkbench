"""Tests for TUI/GUI shared operation actions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.scan import scan_library
from sfxworkbench.tui_actions import (
    ActionResult,
    apply_dedupe_plan_action,
    apply_delete_plan_action,
    apply_tag_plan_action,
    approve_dedupe_plan_action,
    approve_delete_plan_action,
    approve_organize_action,
    approve_tag_plan_action,
    build_dedupe_plan_action,
    build_delete_plan_action,
    clean_action,
    full_audit_action,
    operation_report_dir,
    organize_audit_action,
    scan_action,
    tag_plan_action,
    write_action_history,
)


def test_tui_action_runner_scan_audit_and_clean_preview(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"

    scan = scan_action(tmp_library, tmp_db)
    audit = full_audit_action(tmp_library, tmp_db, report_dir)
    clean = clean_action(tmp_library, report_dir, apply=False)

    assert scan.ok
    assert "Indexed" in scan.message
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

    assert audit.ok or audit.status == "error"
    assert clean.ok
    assert any(event[0] == "scanning" for event in audit_events)
    assert any(event[0] == "auditing" for event in audit_events)
    assert any(event[0] == "walking" for event in clean_events)
    assert clean_events[-1][0] == "preview"


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
    delete = build_delete_plan_action(report_dir)
    assert delete.ok
    assert delete.details is not None
    assert delete.details["summary"]["candidate_entries"] >= 1


def test_tui_permanent_delete_plan_and_apply_from_quarantine_log(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    apply_log_dir = report_dir / "apply_logs"
    apply_log_dir.mkdir(parents=True)
    quarantined = report_dir / "sfxworkbench_pack_quarantine_20260512_120000" / "old_pack"
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
    unapproved = apply_delete_plan_action(report_dir)
    approve = approve_delete_plan_action(report_dir)
    applied = apply_delete_plan_action(report_dir)

    assert plan.ok
    assert plan.output_path == str(report_dir / "delete_plan.json")
    assert not unapproved.ok
    assert approve.ok
    assert applied.ok
    assert applied.details is not None
    assert applied.details["deleted"] == 1
    assert not quarantined.exists()


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
    assert list((report_dir / "apply_logs").glob("legacy_quarantine_log_*.json"))


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


def test_tui_tag_plan_falls_back_when_ucs_catalog_is_missing(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("sfxworkbench.tag_suggest.load_catalog", lambda path=None: None)
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    report_dir = tmp_path / "reports"

    result = tag_plan_action(tmp_library, tmp_db, report_dir)

    assert result.ok
    assert "UCS catalog is optional" in result.message
    assert result.details is not None
    assert result.details["used_ucs_catalog"] is False
    assert (report_dir / "metadata_tag_plan.json").exists()


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
