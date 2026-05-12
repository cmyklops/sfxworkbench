"""Tests for the Textual alpha data adapters."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sfxworkbench.cli import app
from sfxworkbench.scan import scan_library
from sfxworkbench.tui_data import (
    advanced_findings,
    clean_findings,
    dashboard_metrics,
    dedupe_findings,
    dedupe_group_rows,
    discover_plan_files,
    feature_pages,
    file_detail,
    indexed_library_size_gb,
    list_files,
    list_queue_items,
    metadata_findings,
    metadata_workbench_rows,
    plan_detail_rows,
    preferred_library_path,
    report_presets,
    report_search_paths,
    review_presets,
    review_queues,
    save_library_path,
    saved_library_path,
    scan_findings,
    summarize_plan_file,
)
from typer.testing import CliRunner

runner = CliRunner()


def test_tui_dashboard_and_queues_reflect_index_state(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=False, quiet=True)
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(tmp_library / "sounds")]}))

    metrics = {metric.key: metric for metric in dashboard_metrics(tmp_db, config_path=config_path)}
    queues = {queue.key: queue for queue in review_queues(tmp_db)}

    assert metrics["indexed_files"].value >= 2
    assert metrics["safe_folders"].value == 1
    assert "Duplicate groups" in metrics["duplicate_groups"].label
    assert queues["scan_errors"].lane == "Health"
    assert queues["duplicates"].lane == "Cleanup"
    assert "sfx dedupe" in queues["duplicates"].next_action
    assert queues["missing_metadata"].lane == "Metadata"
    assert "metadata audit" in queues["missing_metadata"].next_action
    assert queues["missing_metadata"].count >= 1
    assert queues["filename_issues"].count >= 1
    assert indexed_library_size_gb(tmp_db) > 0


def test_tui_file_listing_returns_index_rows(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    rows = list_files(tmp_db, limit=5)

    assert rows
    assert any(row.filename == "AMB_RAIN_01.wav" for row in rows)


def test_tui_file_listing_includes_live_metadata_counts(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"

    conn = sqlite3.connect(tmp_db)
    try:
        file_id = conn.execute("SELECT id FROM files WHERE path = ?", (str(target),)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO accepted_tags (
                file_id, field, value, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, "description", "Steady rain", "test", "2026-05-11T00:00:00", "2026-05-11T00:00:00"),
        )
        conn.execute(
            """
            INSERT INTO metadata_fields (
                file_id, namespace, key, value, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, "bext", "description", "Steady rain", "test", "2026-05-11T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = list_files(tmp_db, query="AMB_RAIN", limit=5)

    assert rows[0].accepted_tag_count == 1
    assert rows[0].metadata_field_count == 1
    assert rows[0].issue_count == 0


def test_tui_file_search_falls_back_for_literal_paths(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    rows = list_files(tmp_db, query=str(tmp_library / "sounds" / "AMB_RAIN_01.wav"), limit=5)

    assert [row.filename for row in rows] == ["AMB_RAIN_01.wav"]


def test_tui_file_detail_includes_facts_and_issues(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "bad:name.wav"

    detail = file_detail(tmp_db, path=str(target))

    assert detail is not None
    assert detail.filename == "bad:name.wav"
    assert any(label == "Path" and value == str(target) for label, value in detail.facts)
    assert any(label == "Stem" and value == "bad:name" for label, value in detail.facts)
    assert [section.title for section in detail.sections] == [
        "Searchable Metadata To Vet",
        "Read From File - Search Fields",
        "Will Write - Proposed DB Tags",
        "Already Applied - DB Tags",
        "Read From File - Provenance/Technical",
        "Audio",
        "Embedded Metadata Flags",
        "Review State",
        "Location",
    ]
    assert any(label == "RIFF INFO" for section in detail.sections for label, _ in section.rows)
    assert any("illegal_chars" in issue for issue in detail.issues)
    assert any("sfx rename" in action for action in detail.actions)
    assert any("open -R" in action for action in detail.actions)


def test_tui_file_detail_includes_indexed_metadata_fields(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"

    conn = sqlite3.connect(tmp_db)
    try:
        file_id = conn.execute("SELECT id FROM files WHERE path = ?", (str(target),)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO metadata_fields (
                file_id, namespace, key, value, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, "bext", "description", "Steady rain", "test", "2026-05-11T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    detail = file_detail(tmp_db, path=str(target))

    assert detail is not None
    indexed = next(section for section in detail.sections if section.title == "Read From File - Search Fields")
    assert ("Description (bext)", "Steady rain [test]") in indexed.rows


def test_tui_metadata_rows_hide_provenance_fields_from_main_review_table(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"

    conn = sqlite3.connect(tmp_db)
    try:
        file_id = conn.execute("SELECT id FROM files WHERE path = ?", (str(target),)).fetchone()[0]
        conn.executemany(
            """
            INSERT INTO metadata_fields (
                file_id, namespace, key, value, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (file_id, "bext", "description", "Steady rain", "test", "2026-05-11T00:00:00"),
                (
                    file_id,
                    "bext",
                    "OriginatorReference",
                    "www.vendor.example",
                    "test",
                    "2026-05-11T00:00:00",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    rows = metadata_workbench_rows(tmp_db, query="AMB_RAIN")

    assert "Description: Steady rain" in rows[0].embedded_summary
    assert "OriginatorReference" not in rows[0].embedded_summary
    assert "vendor.example" not in rows[0].embedded_summary


def test_tui_queue_items_expand_review_counts(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    missing = list_queue_items(tmp_db, queue_key="missing_metadata", limit=5)
    unsafe = list_queue_items(tmp_db, queue_key="filename_issues", limit=10)

    assert any(item.label == "AMB_RAIN_01.wav" for item in missing)
    assert any(item.label == "bad:name.wav" for item in unsafe)


def test_tui_queue_items_can_filter_selected_queue(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    rows = list_queue_items(tmp_db, queue_key="missing_metadata", filter_text="GUNSHOT", limit=10)

    assert [item.label for item in rows] == ["SFX_GUNSHOT_01.wav"]
    assert "44100 Hz" in rows[0].detail


def test_tui_review_presets_offer_queue_specific_filters() -> None:
    missing = review_presets("missing_metadata")
    duplicates = review_presets("duplicates")
    unknown = review_presets("custom_queue")

    assert missing[0].filter_text == ""
    assert any(preset.label == "48k WAV" and preset.filter_text == "wav 48000" for preset in missing)
    assert any(preset.label == "WAV duplicates" and preset.filter_text == "wav" for preset in duplicates)
    assert unknown[0].label == "All items"


def test_tui_report_presets_and_category_filters() -> None:
    presets = report_presets()

    assert presets[0].label == "Everything"
    assert any(preset.label == "Plans" and preset.category == "Plan" for preset in presets)
    assert any(preset.label == "Protected" and preset.query == "safe_folder" for preset in presets)


def test_tui_report_search_paths_use_explicit_or_nearby_reports(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "index.db"
    reports = tmp_path / "state" / "reports"
    reports.mkdir(parents=True)
    explicit = tmp_path / "explicit"
    explicit.mkdir()

    assert report_search_paths(db_path, report_paths=[explicit]) == [explicit]
    assert reports in report_search_paths(db_path)
    assert not db_path.exists()


def test_tui_library_path_preference_resumes_and_can_clear(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    alternate_root = tmp_library.parent / "Alternate Library"

    save_library_path(tmp_db, alternate_root)

    assert saved_library_path(tmp_db) == str(alternate_root)
    assert preferred_library_path(tmp_db) == str(alternate_root)

    save_library_path(tmp_db, "")

    assert saved_library_path(tmp_db) is None
    assert preferred_library_path(tmp_db) == str(tmp_library)


def test_tui_feature_pages_cover_full_operations_workbench(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    pages = feature_pages(tmp_db)
    by_key = {page.key: page for page in pages}

    assert list(by_key) == ["scan", "clean", "dedupe", "metadata", "advanced"]
    assert by_key["scan"].label == "Scan"
    assert by_key["clean"].label == "Declutter"
    assert by_key["clean"].description.startswith("Remove junk")
    assert by_key["dedupe"].description.startswith("Review exact")
    assert by_key["metadata"].status == "review"


def test_tui_feature_findings_cover_each_page(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    assert any(row.label == "Indexed files" for row in scan_findings(tmp_db))
    assert any(row.label == "Junk items" for row in clean_findings(tmp_library, tmp_db))
    assert any(row.label == "Long paths" for row in clean_findings(tmp_library, tmp_db))
    assert any(row.label == "Duplicate groups" for row in dedupe_findings(tmp_db))
    assert any(row.label == "Missing BEXT/iXML" for row in metadata_findings(tmp_db))
    assert any(row.label == "Index file" and str(tmp_db) in str(row.count) for row in advanced_findings(tmp_db))


def test_tui_dedupe_rows_and_metadata_rows_surface_review_state(
    tmp_library: Path, tmp_db: Path, tmp_path: Path
) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=False, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    conn = sqlite3.connect(tmp_db)
    try:
        file_id = conn.execute("SELECT id FROM files WHERE path = ?", (str(target),)).fetchone()[0]
    finally:
        conn.close()
    plan_path = tmp_path / "metadata_tag_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "path": str(target),
                        "filename": target.name,
                        "source": "ucs_catalog",
                        "review_status": "pending",
                    },
                    {
                        "path": str(target),
                        "filename": target.name,
                        "source": "synonym",
                        "review_status": "approved",
                    },
                ]
            }
        )
    )

    metadata = metadata_workbench_rows(tmp_db, plan_path=plan_path, query="AMB_RAIN")

    assert file_id
    assert metadata[0].pending_changes == 1
    assert metadata[0].approved_changes == 1
    assert metadata[0].sources == "synonym, ucs_catalog"
    assert isinstance(dedupe_group_rows(tmp_db), list)


def test_tui_plan_discovery_summarizes_json_plans(tmp_path: Path) -> None:
    plan_path = tmp_path / "rename_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "root": str(tmp_path),
                "pattern": "portable",
                "entries": [{"old_path": "old.wav", "new_path": "new.wav"}],
                "errors": [{"path": "safe.wav", "error": "protected by safe folder", "safe_folder": str(tmp_path)}],
            }
        )
    )
    report_path = tmp_path / "metadata_report.json"
    report_path.write_text(
        json.dumps(
            {
                "command": "metadata_audit",
                "report": {"summary": {"missing_metadata": 2}, "entries": []},
            }
        )
    )
    log_path = tmp_path / "organize_apply_log.json"
    log_path.write_text(
        json.dumps(
            {
                "pattern": "organize:strip-leading-numbers",
                "entries": [{"old_path": "01 Pack", "new_path": "Pack"}],
            }
        )
    )
    clean_preview_path = tmp_path / "clean_preview_20260512_120000.json"
    clean_preview_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-05-12T12:00:00+00:00",
                "root": str(tmp_path),
                "dry_run": True,
                "removed_files": ["._Ambience.wav"],
                "removed_dirs": ["_wfCache"],
                "bytes_freed": 42,
            }
        )
    )
    apply_log_dir = tmp_path / "apply_logs"
    apply_log_dir.mkdir()
    tag_log_path = apply_log_dir / "tag_apply_log.json"
    tag_log_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": "tag_apply",
                "entries": [{"field": "description", "value": "Rain"}],
            }
        )
    )
    action_history_dir = tmp_path / "action_history"
    action_history_dir.mkdir()
    action_history_path = action_history_dir / "tui_action_20260512_120001_scan.json"
    action_history_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": "tui_action",
                "action": "scan",
                "status": "ok",
                "message": "Indexed 2 file(s).",
                "errors": [],
            }
        )
    )

    summaries = discover_plan_files([tmp_path])
    by_name = {Path(summary.path).name: summary for summary in summaries}

    assert len(summaries) == 6
    assert by_name["rename_plan.json"].kind == "rename_or_organize"
    assert by_name["rename_plan.json"].category == "Plan"
    assert by_name["rename_plan.json"].entries == 1
    assert by_name["rename_plan.json"].protected == 1
    assert by_name["rename_plan.json"].undoable is True
    assert by_name["clean_preview_20260512_120000.json"].kind == "clean_preview"
    assert by_name["clean_preview_20260512_120000.json"].category == "Preview"
    assert by_name["clean_preview_20260512_120000.json"].entries == 2
    assert by_name["metadata_report.json"].category == "Report"
    assert by_name["organize_apply_log.json"].category == "Log"
    assert by_name["tag_apply_log.json"].category == "Log"
    assert by_name["tui_action_20260512_120001_scan.json"].category == "History"
    assert by_name["tui_action_20260512_120001_scan.json"].title == "Scan (ok)"

    detail_rows = plan_detail_rows(plan_path)
    assert detail_rows[0].source == "old.wav"
    assert detail_rows[0].target == "new.wav"
    assert detail_rows[1].kind == "error"
    assert detail_rows[1].status == "error"

    report_rows = plan_detail_rows(report_path)
    assert report_rows[0].kind == "summary"
    assert report_rows[0].action == "missing_metadata"
    assert report_rows[0].source == "2"

    assert discover_plan_files([tmp_path], query="old.wav")[0].path == str(plan_path)
    assert {Path(summary.path).name for summary in discover_plan_files([tmp_path], query="rename clean")} == {
        "rename_plan.json",
        "clean_preview_20260512_120000.json",
    }
    assert [Path(summary.path).name for summary in discover_plan_files([tmp_path], category="Plan")] == [
        "rename_plan.json"
    ]
    assert {Path(summary.path).name for summary in discover_plan_files([tmp_path], category="Log")} == {
        "organize_apply_log.json",
        "tag_apply_log.json",
    }
    future_mtime = max(path.stat().st_mtime for path in tmp_path.rglob("*.json")) + 1
    assert discover_plan_files([tmp_path], modified_since=future_mtime) == []
    assert discover_plan_files([tmp_path], query="not-here") == []


def test_tui_plan_detail_rows_expand_nesting_reports_and_action_outputs(tmp_path: Path) -> None:
    report_path = tmp_path / "redundant_nesting_report.json"
    source = tmp_path / "Vendor" / "Pack" / "Pack"
    target = tmp_path / "Vendor" / "Pack"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "sfxworkbench",
                "root": str(tmp_path),
                "pattern": "redundant-nesting",
                "depth": 8,
                "summary": {"directories_scanned": 9, "candidates": 1, "errors": 0},
                "candidates": [
                    {
                        "path": str(source),
                        "name": "Pack",
                        "kind": "repeated_folder_name",
                        "suggested_action": "review_flatten_child_into_parent",
                        "reason": "folder name repeats its parent",
                        "depth": 3,
                        "parent_path": str(target),
                        "target_path": str(target),
                        "child_dirs": 0,
                        "direct_files": 1,
                        "audio_files": 1,
                        "confidence": "high",
                    }
                ],
                "errors": [],
            }
        )
    )
    action_path = tmp_path / "action_history.json"
    action_path.write_text(
        json.dumps(
            {
                "command": "tui_action",
                "action": "organize_nesting_audit",
                "status": "ok",
                "message": "Previewed 0 folder organization entrie(s), 1 candidate(s), errors 0.",
                "output_path": str(report_path),
                "errors": [],
            }
        )
    )

    summary = summarize_plan_file(report_path)
    assert summary.kind == "organize_nesting_report"
    assert summary.category == "Report"
    assert summary.entries == 1
    assert summary.title == "Nested folder candidates"

    rows = plan_detail_rows(action_path)
    candidate_rows = [row for row in rows if row.kind == "candidate"]
    assert rows[0].kind == "action"
    assert candidate_rows[0].source == str(source)
    assert candidate_rows[0].target == str(target)
    assert candidate_rows[0].status == "high"
    assert "folder name repeats its parent" in candidate_rows[0].detail


def test_tui_command_invokes_runner(tmp_db: Path, monkeypatch) -> None:
    calls = []

    def fake_run_tui(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("sfxworkbench.tui_app.run_tui", fake_run_tui)

    result = runner.invoke(app, ["tui", "--db", str(tmp_db), "--report", str(tmp_db.parent)])

    assert result.exit_code == 0
    assert calls
    assert calls[0]["db_path"] == tmp_db
    assert calls[0]["report_paths"] == [tmp_db.parent]
