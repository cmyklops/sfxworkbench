"""Tests for the SQLite artifact registry and job tracking."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sfxworkbench.artifacts import (
    artifact_detail_rows,
    list_artifacts,
    materialize_artifact_rows,
    register_artifact,
    sync_artifacts_from_paths,
)
from sfxworkbench.cli import app
from sfxworkbench.db import get_connection
from sfxworkbench.jobs import finish_job, interrupt_running_jobs, latest_job, start_job, update_job_progress
from typer.testing import CliRunner

runner = CliRunner()


def test_artifact_sync_registers_reports_logs_and_action_history(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = tmp_path / "rename_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pattern": "portable",
                "entries": [{"old_path": "old.wav", "new_path": "new.wav"}],
                "errors": [{"path": "safe.wav", "error": "protected by safe folder", "safe_folder": "/safe"}],
            }
        )
    )
    log_dir = tmp_path / "apply_logs"
    log_dir.mkdir()
    (log_dir / "tag_apply_log.json").write_text(
        json.dumps({"schema_version": 1, "command": "tag_apply", "entries": [{"field": "description"}]})
    )
    action_dir = tmp_path / "action_history"
    action_dir.mkdir()
    (action_dir / "tui_action_20260512_120001_scan.json").write_text(
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

    result = sync_artifacts_from_paths(tmp_db, [tmp_path])
    by_name = {Path(row.path).name: row for row in list_artifacts(tmp_db, limit=20)}

    assert result.scanned == 3
    assert by_name["rename_plan.json"].kind == "rename_or_organize"
    assert by_name["rename_plan.json"].category == "Plan"
    assert by_name["rename_plan.json"].entries == 1
    assert by_name["rename_plan.json"].protected == 1
    assert by_name["tag_apply_log.json"].category == "Log"
    assert by_name["tui_action_20260512_120001_scan.json"].category == "History"
    assert by_name["tui_action_20260512_120001_scan.json"].title == "Scan (ok)"


def test_artifact_sync_tracks_invalid_changed_and_missing_json(tmp_path: Path, tmp_db: Path) -> None:
    valid = tmp_path / "dedupe_plan.json"
    valid.write_text(json.dumps({"groups": [{"id": 1}], "errors": []}))
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json")

    sync_artifacts_from_paths(tmp_db, [tmp_path])
    first = {Path(row.path).name: row for row in list_artifacts(tmp_db, limit=20)}

    assert first["dedupe_plan.json"].status == "ok"
    assert first["bad.json"].status == "error"

    valid.write_text(json.dumps({"groups": [{"id": 1}, {"id": 2}], "errors": []}))
    sync_artifacts_from_paths(tmp_db, [tmp_path])
    changed = {Path(row.path).name: row for row in list_artifacts(tmp_db, limit=20)}
    assert changed["dedupe_plan.json"].entries == 2

    valid.unlink()
    sync_artifacts_from_paths(tmp_db, [tmp_path])
    missing = {Path(row.path).name: row for row in list_artifacts(tmp_db, limit=20)}
    assert missing["dedupe_plan.json"].status == "missing"


def test_large_history_listing_uses_registry_without_full_json_parse(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    plan_path = tmp_path / "dedupe_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {"path": f"/lib/{index}.wav", "action": "quarantine", "value": "x" * 256} for index in range(1_000)
                ],
                "summary": {"duplicate_groups": 42, "errors": 2},
            }
        )
    )

    def fail_read_text(*args, **kwargs):
        raise AssertionError("artifact registry summary should not full-parse large JSON")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    sync_artifacts_from_paths(tmp_db, [tmp_path])
    rows = list_artifacts(tmp_db, limit=10)

    assert len(rows) == 1
    assert rows[0].kind == "dedupe_plan"
    assert rows[0].entries == 42
    assert rows[0].errors == 2


def test_materialized_artifact_rows_feed_detail_and_search(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = tmp_path / "portable_rename_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pattern": "portable",
                "entries": [{"old_path": "old.wav", "new_path": "new.wav", "status": "pending"}],
            }
        )
    )
    artifact = register_artifact(tmp_db, plan_path)

    assert materialize_artifact_rows(tmp_db, artifact_id=artifact.id) == 1
    detail_rows = artifact_detail_rows(tmp_db, artifact_id=artifact.id)
    matches = list_artifacts(tmp_db, query="old.wav", limit=10)

    assert detail_rows[0].source == "old.wav"
    assert detail_rows[0].target == "new.wav"
    assert [row.path for row in matches] == [str(plan_path)]


def test_artifact_detail_rows_format_quarantine_entry_sizes(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = tmp_path / "delete_plan.json"
    plan_path.write_text(
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
        )
    )
    artifact = register_artifact(tmp_db, plan_path)
    materialize_artifact_rows(tmp_db, artifact_id=artifact.id)

    detail_rows = artifact_detail_rows(tmp_db, artifact_id=artifact.id)

    assert detail_rows[0].detail == "file; 1.0 TB"


def test_materialize_sync_fills_rows_for_unchanged_registered_artifacts(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = tmp_path / "portable_rename_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pattern": "portable",
                "entries": [{"old_path": "old.wav", "new_path": "new.wav", "status": "pending"}],
            }
        )
    )

    sync_artifacts_from_paths(tmp_db, [tmp_path], materialize=False)
    assert artifact_detail_rows(tmp_db, path=plan_path) == []

    result = sync_artifacts_from_paths(tmp_db, [tmp_path], materialize=True)
    detail_rows = artifact_detail_rows(tmp_db, path=plan_path)

    assert result.unchanged == 1
    assert detail_rows[0].source == "old.wav"
    assert detail_rows[0].target == "new.wav"


def test_artifact_search_treats_like_wildcards_as_literals(tmp_path: Path, tmp_db: Path) -> None:
    normal = tmp_path / "normal_rename_plan.json"
    normal.write_text(json.dumps({"pattern": "portable", "entries": [{"old_path": "old.wav"}]}))
    percent = tmp_path / "100%_rename_plan.json"
    percent.write_text(json.dumps({"pattern": "portable", "entries": [{"old_path": "percent.wav"}]}))

    sync_artifacts_from_paths(tmp_db, [tmp_path])

    matches = list_artifacts(tmp_db, query="%", limit=10)

    assert [Path(row.path).name for row in matches] == ["100%_rename_plan.json"]


def test_artifact_feature_filter_keeps_multi_feature_pack_artifacts(tmp_path: Path, tmp_db: Path) -> None:
    pack_plan = tmp_path / "pack_plan.json"
    pack_plan.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "sfxworkbench",
                "source_report": "pack_report.json",
                "summary": {"candidate_groups": 1},
                "entries": [{"source_path": "Pack A", "target_path": "Pack B"}],
            }
        )
    )

    sync_artifacts_from_paths(tmp_db, [tmp_path])

    assert [Path(row.path).name for row in list_artifacts(tmp_db, feature="scan")] == ["pack_plan.json"]
    assert [Path(row.path).name for row in list_artifacts(tmp_db, feature="dedupe")] == ["pack_plan.json"]


def test_jobs_record_progress_and_link_output_artifact(tmp_path: Path, tmp_db: Path) -> None:
    output = tmp_path / "metadata_audit.json"
    output.write_text(json.dumps({"command": "metadata_audit", "report": {"summary": {"missing_metadata": 1}}}))
    artifact = register_artifact(tmp_db, output)

    job_id = start_job(tmp_db, "metadata_audit", message="Starting metadata audit")
    update_job_progress(tmp_db, job_id, phase="running", completed=5, total=10, message="Halfway")
    finish_job(tmp_db, job_id, status="ok", output_artifact_id=artifact.id)

    conn = get_connection(tmp_db)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()

    progress = json.loads(row["progress"])
    assert row["status"] == "ok"
    assert row["finished_at"]
    assert row["output_artifact_id"] == artifact.id
    assert progress["phase"] == "running"
    assert progress["completed"] == 5
    assert progress["percent"] == 50.0


def test_startup_recovery_marks_running_jobs_interrupted(tmp_db: Path) -> None:
    job_id = start_job(tmp_db, "scan", message="Starting scan")

    interrupted = interrupt_running_jobs(tmp_db)
    latest = latest_job(tmp_db)

    assert [job.id for job in interrupted] == [job_id]
    assert interrupted[0].action == "scan"
    assert interrupted[0].status == "interrupted"
    assert interrupted[0].finished_at
    assert interrupted[0].error == "Previous TUI session ended before this action reported completion."
    assert latest is not None
    assert latest.status == "interrupted"
    assert latest.finished_at
    assert latest.error == "Previous TUI session ended before this action reported completion."


def test_maintenance_artifacts_sync_cli_rebuilds_registry(tmp_path: Path, tmp_db: Path) -> None:
    (tmp_path / "metadata_audit.json").write_text(
        json.dumps({"command": "metadata_audit", "report": {"summary": {"missing_metadata": 1}}})
    )

    result = runner.invoke(
        app,
        ["maintenance", "artifacts", "sync", "--db", str(tmp_db), "--report", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "maintenance_artifacts_sync"
    assert payload["result"]["registered"] == 1
    assert list_artifacts(tmp_db)[0].kind == "metadata_audit"


def test_artifact_sync_handles_portable_path_characters(tmp_path: Path, tmp_db: Path) -> None:
    names = [
        "space name_rename_plan.json",
        "100%_rename_plan.json",
        "under_score_rename_plan.json",
    ]
    if tmp_path.drive:
        names.extend(["C_Reports_rename_plan.json", "drive_C_rename_plan.json"])
    else:
        names.extend(["C:\\Reports\\rename_plan.json", "drive_C:_rename_plan.json"])

    for name in names:
        artifact_path = tmp_path / name
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps({"pattern": "portable", "entries": [{"old_path": name}]}))

    result = sync_artifacts_from_paths(tmp_db, [tmp_path])
    expected_names = {Path(tmp_path / name).name for name in names}
    registered = {Path(row.path).name for row in list_artifacts(tmp_db, limit=20)}

    assert result.registered == len(names)
    assert expected_names <= registered
    assert [Path(row.path).name for row in list_artifacts(tmp_db, query="%", limit=20)] == ["100%_rename_plan.json"]
    assert {Path(row.path).name for row in list_artifacts(tmp_db, query="_", limit=20)} == expected_names


def test_artifact_sync_marks_windows_style_stored_paths_missing_on_posix(tmp_db: Path) -> None:
    conn = get_connection(tmp_db)
    try:
        conn.execute(
            """
            INSERT INTO artifacts (
                path, kind, feature, category, created_at, mtime, size, summary_json, entry_count, error_count, status
            ) VALUES (?, 'dedupe_plan', 'dedupe', 'Plan', '2026-05-15T00:00:00+00:00', 1, 1, '{}', 0, 0, 'ok')
            """,
            (r"C:\Reports\Old Plans\100%_dedupe_plan.json",),
        )
        conn.commit()
    finally:
        conn.close()

    result = sync_artifacts_from_paths(tmp_db, [Path(r"C:\Reports\Old Plans")])
    rows = list_artifacts(tmp_db, limit=10)

    assert result.scanned == 0
    assert result.missing == 1
    assert rows[0].status == "missing"


def test_artifact_schema_migration_adds_registry_to_old_db(tmp_path: Path) -> None:
    db_path = tmp_path / "old-index.db"
    with sqlite3.connect(db_path) as legacy:
        legacy.execute("CREATE TABLE legacy_marker (id INTEGER PRIMARY KEY, value TEXT)")
        legacy.execute("INSERT INTO legacy_marker (value) VALUES ('kept')")

    conn = get_connection(db_path)
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('artifacts', 'jobs', 'legacy_marker')"
            )
        }
        marker = conn.execute("SELECT value FROM legacy_marker").fetchone()["value"]
    finally:
        conn.close()

    assert tables == {"artifacts", "jobs", "legacy_marker"}
    assert marker == "kept"
