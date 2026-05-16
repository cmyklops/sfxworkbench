"""Tests for the Textual alpha data adapters."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import sfxworkbench.tui_data as tui_data
from sfxworkbench.cli import app
from sfxworkbench.scan import scan_library
from sfxworkbench.tui_data import (
    PlanSummary,
    clean_findings,
    dashboard_metrics,
    dedupe_findings,
    dedupe_group_rows,
    discover_plan_files,
    feature_pages,
    file_detail,
    history_feature_labels,
    history_features_for_summary,
    history_matches_feature,
    indexed_library_size_gb,
    list_files,
    list_queue_items,
    metadata_findings,
    metadata_plan_counts,
    metadata_tag_change_rows,
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
    start_steps,
    summarize_plan_file,
)
from typer.testing import CliRunner

runner = CliRunner()


def _indexed_unsafe_fixture(db_path: Path) -> tuple[Path, str, str, str]:
    unsafe = list_queue_items(db_path, queue_key="filename_issues", limit=10)
    assert unsafe, "tmp_library did not index any filename issue fixtures"
    item = unsafe[0]
    issue = item.detail.partition(" ")[0]
    path = Path(item.path)
    return path, item.label, path.stem, issue


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
    target, expected_filename, expected_stem, expected_issue = _indexed_unsafe_fixture(tmp_db)

    detail = file_detail(tmp_db, path=str(target))

    assert detail is not None
    assert detail.filename == expected_filename
    assert any(label == "Path" and value == str(target) for label, value in detail.facts)
    assert any(label == "Stem" and value == expected_stem for label, value in detail.facts)
    assert [section.title for section in detail.sections] == [
        "Searchable Metadata To Vet",
        "Read From File - Search Fields",
        "Planned DB Tags",
        "Already Applied - DB Tags",
        "Read From File - Provenance/Technical",
        "Audio",
        "Embedded Metadata Flags",
        "Review State",
        "Location",
    ]
    assert any(label == "RIFF INFO" for section in detail.sections for label, _ in section.rows)
    assert any(expected_issue in issue for issue in detail.issues)
    assert any("sfx rename" in action for action in detail.actions)
    assert any("open -R" in action for action in detail.actions)


def test_tui_file_detail_formats_size_as_human_units(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    target = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    conn = sqlite3.connect(tmp_db)
    try:
        conn.execute("UPDATE files SET size_bytes = ? WHERE path = ?", (1024**3, str(target)))
        conn.commit()
    finally:
        conn.close()

    detail = file_detail(tmp_db, path=str(target))

    assert detail is not None
    location = next(section for section in detail.sections if section.title == "Location")
    assert ("Size", "1.0 GB") in location.rows


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


def test_tui_metadata_rows_hide_provenance_fields_from_main_review_table(
    tmp_library: Path, tmp_db: Path, tmp_path: Path
) -> None:
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
                (file_id, "bext", "description", "Steady   rain\n tail", "test", "2026-05-11T00:00:00"),
                (
                    file_id,
                    "bext",
                    "description",
                    "sSPEED=030.000-ND sTAKE=13 sUBITS=$04131313 sSWVER=2.65 "
                    "sPROJECT= sSCENE=ID_CRD_AL sFILENAME=ID_CRD_AL_13.WAV "
                    "sTAPE=130413 sTRK1=Track A sTRK2=Track B sNOTE=",
                    "test",
                    "2026-05-11T00:00:00",
                ),
                (
                    file_id,
                    "bext",
                    "description",
                    "sSPEED=030.000-ND sTAKE=14 sTRK1=Track A sNOTE= useful note",
                    "test",
                    "2026-05-11T00:00:00",
                ),
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
        conn.execute(
            """
            INSERT INTO accepted_tags (
                file_id, field, value, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                "description",
                "sSPEED=030.000-ND sTAKE=15 sTRK1=Track A sNOTE=",
                "legacy",
                "2026-05-11T00:00:00",
                "2026-05-11T00:00:00",
            ),
        )
        conn.commit()
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
                        "field": "description",
                        "proposed_value": "Steady rain tail",
                        "source": "filename",
                        "review_status": "pending",
                        "action": "add",
                    }
                ]
            }
        )
    )

    rows = metadata_workbench_rows(tmp_db, plan_path=plan_path, query="AMB_RAIN")

    assert "Description: Steady rain tail" in rows[0].embedded_summary
    assert "Description: useful note" in rows[0].embedded_summary
    assert "Steady rain tail" in rows[0].tags_summary
    assert "useful note" in rows[0].tags_summary
    assert "sSPEED" not in rows[0].embedded_summary
    assert "sTAKE" not in rows[0].tags_summary
    assert "Track A" not in rows[0].tags_summary
    assert "legacy" not in rows[0].accepted_summary
    assert rows[0].pending_changes == 0
    assert rows[0].tag_items[0].source == "file"
    assert rows[0].tag_items[0].field == "description"
    assert [item.source for item in rows[0].tag_items] == ["file", "file"]
    assert metadata_tag_change_rows(plan_path, db_path=tmp_db) == []
    assert "OriginatorReference" not in rows[0].embedded_summary
    assert "vendor.example" not in rows[0].embedded_summary


def test_tui_queue_items_expand_review_counts(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    missing = list_queue_items(tmp_db, queue_key="missing_metadata", limit=5)
    unsafe = list_queue_items(tmp_db, queue_key="filename_issues", limit=10)

    assert any(item.label == "AMB_RAIN_01.wav" for item in missing)
    assert unsafe


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

    assert list(by_key) == ["scan", "clean", "dedupe", "metadata", "files"]
    assert by_key["scan"].label == "Scan"
    assert by_key["files"].label == "Files"
    assert by_key["clean"].label == "Cleanup"
    assert by_key["clean"].description.startswith("Remove junk")
    assert by_key["dedupe"].description.startswith("Review exact")
    assert by_key["metadata"].status == "review"


def test_tui_start_steps_begin_with_library_and_index(tmp_library: Path, tmp_db: Path) -> None:
    empty_steps = start_steps(tmp_db, library_path=tmp_library)

    assert [step.label for step in empty_steps[:2]] == ["Choose a copied library", "Build searchable index"]
    assert empty_steps[0].status == "clear"
    assert empty_steps[1].status == "ready"
    assert "Quick Index" in empty_steps[1].next_action

    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    indexed_steps = start_steps(tmp_db, library_path=tmp_library)

    by_key = {step.destination_key: step for step in indexed_steps}
    assert by_key["scan"].status == "clear"
    assert by_key["duplicates"].destination == "Dedupe"
    assert by_key["missing_metadata"].destination == "Metadata"


def test_tui_feature_findings_cover_each_page(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)

    assert any(row.label == "Indexed files" for row in scan_findings(tmp_db))
    assert any(row.label == "Junk items" for row in clean_findings(tmp_library, tmp_db))
    assert any(row.label == "Long paths" for row in clean_findings(tmp_library, tmp_db))
    assert any(row.label == "Duplicate groups" for row in dedupe_findings(tmp_db))
    assert any(row.label == "Missing BEXT/iXML" for row in metadata_findings(tmp_db))


def test_tui_metadata_findings_use_whole_plan_counts(tmp_db: Path, tmp_path: Path) -> None:
    plan_path = tmp_path / "metadata_tag_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "summary": {
                    "files_considered": 3,
                    "candidate_entries": 5,
                    "add_entries": 4,
                    "skip_existing_entries": 1,
                    "approved_entries": 1,
                    "rejected_entries": 1,
                },
                "entries": [
                    {
                        "path": "/lib/a.wav",
                        "filename": "a.wav",
                        "field": "description",
                        "proposed_value": "Rain",
                        "review_status": "pending",
                    },
                    {
                        "path": "/lib/b.wav",
                        "filename": "b.wav",
                        "field": "keywords",
                        "proposed_value": "storm",
                        "review_status": "pending",
                    },
                    {
                        "path": "/lib/c.wav",
                        "filename": "c.wav",
                        "field": "description",
                        "proposed_value": "Thunder",
                        "review_status": "approved",
                    },
                    {
                        "path": "/lib/c.wav",
                        "filename": "c.wav",
                        "field": "category",
                        "proposed_value": "Weather",
                        "review_status": "rejected",
                    },
                    {
                        "path": "/lib/c.wav",
                        "filename": "c.wav",
                        "field": "keywords",
                        "proposed_value": "weather",
                        "review_status": "pending",
                        "action": "skip_existing",
                    },
                ],
            }
        )
    )

    counts = metadata_plan_counts(plan_path)
    findings = {row.label: row for row in metadata_findings(tmp_db, plan_path=plan_path)}

    assert counts.total_entries == 5
    assert counts.pending_add_entries == 2
    assert counts.approved_add_entries == 1
    assert counts.rejected_add_entries == 1
    assert counts.skip_existing_entries == 1
    assert findings["Pending tag changes"].count == 2
    assert "4 add entrie(s) from 3 file(s) considered" in findings["Pending tag changes"].detail
    assert findings["Approved tag changes"].count == 1


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
                        "field": "description",
                        "proposed_value": "Steady rain",
                        "source": "ucs_catalog",
                        "review_status": "pending",
                    },
                    {
                        "path": str(target),
                        "filename": target.name,
                        "field": "keywords",
                        "proposed_value": "rain ;  exterior",
                        "source": "synonym",
                        "review_status": "approved",
                    },
                    {
                        "path": str(target),
                        "filename": target.name,
                        "field": "keywords",
                        "proposed_value": "rain ;  exterior",
                        "source": "synonym",
                        "review_status": "pending",
                        "action": "skip_existing",
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
    assert "Steady rain" in metadata[0].tags_summary
    assert "rain, exterior" in metadata[0].tags_summary
    assert metadata[0].tags_summary.count("rain, exterior") == 1
    assert [item.source for item in metadata[0].tag_items] == ["plan", "plan"]
    assert [item.status for item in metadata[0].tag_items] == ["pending", "approved"]

    changes = metadata_tag_change_rows(plan_path)
    assert [change.status for change in changes] == ["pending", "approved"]
    assert changes[1].value == "rain, exterior"
    assert [change.value for change in changes].count("rain, exterior") == 1
    assert isinstance(dedupe_group_rows(tmp_db), list)


def test_tui_metadata_rows_can_page_and_randomize_pending_plan_files(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    first = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    second = tmp_library / "sounds" / "SFX_GUNSHOT_01.wav"
    plan_path = tmp_path / "metadata_tag_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry_id": 1,
                        "path": str(first),
                        "filename": first.name,
                        "field": "description",
                        "proposed_value": "Steady rain",
                        "source": "filename",
                        "review_status": "pending",
                    },
                    {
                        "entry_id": 2,
                        "path": str(second),
                        "filename": second.name,
                        "field": "description",
                        "proposed_value": "Pistol shot",
                        "source": "filename",
                        "review_status": "pending",
                    },
                ]
            }
        )
    )

    page_one = metadata_workbench_rows(tmp_db, plan_path=plan_path, limit=1, pending_only=True)
    page_two = metadata_workbench_rows(tmp_db, plan_path=plan_path, limit=1, offset=1, pending_only=True)
    random_page = metadata_workbench_rows(tmp_db, plan_path=plan_path, limit=1, random_pending=True, pending_only=True)

    assert [row.filename for row in page_one] == [first.name]
    assert [row.filename for row in page_two] == [second.name]
    assert len(random_page) == 1
    assert random_page[0].filename in {first.name, second.name}

    def fail_read_text(*args, **kwargs):
        raise AssertionError("metadata plan index should be cached after first load")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    cached_page = metadata_workbench_rows(tmp_db, plan_path=plan_path, limit=1, offset=1, pending_only=True)

    assert [row.filename for row in cached_page] == [second.name]


def test_tui_metadata_plan_index_persists_between_memory_cache_misses(
    tmp_library: Path, tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    first = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    plan_path = tmp_path / "metadata_tag_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry_id": 1,
                        "path": str(first),
                        "filename": first.name,
                        "field": "description",
                        "proposed_value": "Steady rain",
                        "source": "filename",
                        "review_status": "pending",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(tui_data, "_PLAN_INDEX_CACHE_DIR", tmp_path / "plan-index-cache")
    tui_data._METADATA_PLAN_INDEX_CACHE.clear()

    rows = metadata_workbench_rows(tmp_db, plan_path=plan_path, limit=1, pending_only=True)

    assert [row.filename for row in rows] == [first.name]
    assert list((tmp_path / "plan-index-cache").glob("metadata_plan_*.sqlite"))

    tui_data._METADATA_PLAN_INDEX_CACHE.clear()
    tui_data.clear_adapter_cache()

    def fail_read_text(*args, **kwargs):
        raise AssertionError("persistent metadata plan index should avoid reparsing JSON")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    persisted_rows = metadata_workbench_rows(tmp_db, plan_path=plan_path, limit=1, pending_only=True)

    assert [row.filename for row in persisted_rows] == [first.name]


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
    assert discover_plan_files([tmp_path], query="old.wav", content_query=False) == []
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
    assert [Path(summary.path).name for summary in discover_plan_files([tmp_path], category="Preview")] == [
        "clean_preview_20260512_120000.json"
    ]
    assert [Path(summary.path).name for summary in discover_plan_files([tmp_path], category="History")] == [
        "tui_action_20260512_120001_scan.json"
    ]
    future_mtime = max(path.stat().st_mtime for path in tmp_path.rglob("*.json")) + 1
    assert discover_plan_files([tmp_path], modified_since=future_mtime) == []
    assert discover_plan_files([tmp_path], query="not-here") == []


def test_tui_history_feature_filtering_uses_report_vocabulary() -> None:
    metadata = PlanSummary(
        path="/reports/metadata_tag_plan.json",
        category="Plan",
        kind="tag_plan",
        title="Metadata tag plan",
        description="139,448 add entries",
    )
    dedupe = PlanSummary(
        path="/reports/dedupe_plan.json",
        category="Plan",
        kind="dedupe_plan",
        title="Exact duplicate quarantine plan",
    )
    clean = PlanSummary(
        path="/reports/clean_preview_20260512_120000.json",
        category="Preview",
        kind="clean_preview",
        title="Preview junk cleanup",
    )
    unknown = PlanSummary(
        path="/reports/custom_output.json",
        category="Report",
        kind="custom",
        title="Custom output",
    )

    assert "metadata" in history_features_for_summary(metadata)
    assert "dedupe" in history_features_for_summary(dedupe)
    assert "clean" in history_features_for_summary(clean)
    assert history_matches_feature(metadata, "Metadata")
    assert history_matches_feature(clean, "Cleanup")
    assert history_matches_feature(dedupe, "All Recent")
    assert not history_matches_feature(metadata, "dedupe")
    assert history_feature_labels(unknown) == "All"


def test_tui_lightweight_tag_plan_summary_uses_summary_without_full_parse(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "metadata_tag_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "entries": [{"path": f"/lib/{index}.wav", "action": "add"} for index in range(20)],
                "summary": {
                    "files_considered": 120,
                    "candidate_entries": 324078,
                    "add_entries": 139448,
                    "skip_existing_entries": 184630,
                    "approved_entries": 12,
                    "rejected_entries": 3,
                },
                "target": "db",
            }
        )
    )

    def fail_read_text(*args, **kwargs):
        raise AssertionError("lightweight tag-plan summary should not call read_text")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    summary = summarize_plan_file(plan_path, lightweight=True)

    assert summary.kind == "tag_plan"
    assert summary.category == "Plan"
    assert summary.title == "Metadata tag plan"
    assert summary.entries == 324078
    assert "139,448 add" in summary.description


def test_tui_history_lightweight_summary_avoids_large_full_parse(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "dedupe_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "path": f"/lib/{index}.wav",
                        "action": "quarantine",
                        "value": "x" * 256,
                    }
                    for index in range(1_000)
                ],
                "summary": {"duplicate_groups": 42, "errors": 2},
            }
        )
    )

    def fail_read_text(*args, **kwargs):
        raise AssertionError("lightweight history summary should not full-parse large JSON")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    summaries = discover_plan_files([tmp_path], content_query=False)

    assert len(summaries) == 1
    assert summaries[0].kind == "dedupe_plan"
    assert summaries[0].category == "Plan"
    assert summaries[0].entries == 42
    assert summaries[0].errors == 2


def test_tui_history_lightweight_summary_handles_missing_summary(tmp_path: Path, monkeypatch) -> None:
    report_path = tmp_path / "format_audit.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "sfxworkbench",
                "action": "review_only",
                "entries": [{"path": f"/lib/{index}.wav", "detail": "x" * 256} for index in range(1_000)],
            }
        )
    )

    def fail_read_text(*args, **kwargs):
        raise AssertionError("lightweight history summary should tolerate missing summary without full parse")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    summaries = discover_plan_files([tmp_path], content_query=False)

    assert len(summaries) == 1
    assert summaries[0].kind == "json_report"
    assert summaries[0].category == "Report"
    assert summaries[0].entries == 0
    assert summaries[0].errors == 0


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


def test_tui_plan_detail_rows_format_quarantine_entry_sizes(tmp_path: Path) -> None:
    path = tmp_path / "delete_plan.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry_id": 1,
                        "source_log": "combined_quarantine_log.json",
                        "path": "old.wav",
                        "source_path": "old.wav",
                        "path_type": "file",
                        "size_bytes": 1024**4,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = plan_detail_rows(path)

    assert rows[0].detail == "file; 1.0 TB"


# -- PR #2 safety fixes -----------------------------------------------------


def test_summarize_plan_file_reraises_invalid_json_as_value_error(tmp_path: Path) -> None:
    """A corrupted plan file produces ValueError, not a raw JSONDecodeError.

    Pre-fix this leaked ``json.JSONDecodeError`` past callers that only knew to
    catch ``ValueError``, crashing the TUI when a plan/report file was malformed.
    """
    bad = tmp_path / "broken.json"
    bad.write_text("{not valid json")

    import pytest

    with pytest.raises(ValueError, match="invalid JSON"):
        summarize_plan_file(bad)


def test_plan_detail_rows_reraises_invalid_json_as_value_error(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{not valid json")

    import pytest

    with pytest.raises(ValueError, match="invalid JSON"):
        plan_detail_rows(bad)


def test_save_library_path_returns_none_on_success(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True, quiet=True)
    assert save_library_path(tmp_db, tmp_library) is None
    assert saved_library_path(tmp_db) == str(tmp_library)


def test_save_library_path_returns_error_message_on_db_failure(tmp_path: Path, monkeypatch) -> None:
    """When SQLite raises, the helper surfaces a string so the caller can warn the user."""
    db_path = tmp_path / "test.db"

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("sfxworkbench.tui_data.get_connection", boom)

    result = save_library_path(db_path, "/some/library")
    assert isinstance(result, str)
    assert "could not save library path" in result
    assert "database is locked" in result
