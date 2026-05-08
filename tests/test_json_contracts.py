"""Contract-grade checks for normalized CLI JSON output."""

import json
from pathlib import Path

from typer.testing import CliRunner
from wavwarden.cli import app

runner = CliRunner()


def _load(stdout: str) -> dict:
    return json.loads(stdout)


def _normalize_path(value: str, tmp_path: Path, tmp_library: Path, tmp_db: Path) -> str:
    db = str(tmp_db)
    root = str(tmp_library)
    tmp = str(tmp_path)
    if value == db:
        return "<DB>"
    if value == root:
        return "<ROOT>"
    if value.startswith(root + "/"):
        return "<ROOT>" + value[len(root) :]
    if value.startswith(tmp + "/"):
        return "<TMP>" + value[len(tmp) :]
    return value


def _normalize(value, tmp_path: Path, tmp_library: Path, tmp_db: Path):
    if isinstance(value, dict):
        return {k: _normalize(v, tmp_path, tmp_library, tmp_db) for k, v in value.items() if k not in {"generated_at"}}
    if isinstance(value, list):
        return [_normalize(v, tmp_path, tmp_library, tmp_db) for v in value]
    if isinstance(value, str):
        if value.startswith("dedupe_plan_") and value.endswith(".json"):
            return "<PLAN>"
        return _normalize_path(value, tmp_path, tmp_library, tmp_db)
    return value


def test_scan_json_contract(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--no-hash", "--json"])
    assert result.exit_code == 0
    payload = _normalize(_load(result.stdout), tmp_path, tmp_library, tmp_db)

    assert payload == {
        "schema_version": 1,
        "command": "scan",
        "db_path": "<DB>",
        "root": "<ROOT>",
        "result": {
            "total": 5,
            "scanned": 5,
            "skipped": 0,
            "errors": 0,
        },
    }


def test_audit_search_export_json_contract(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--no-hash", "--json"])

    audit = _normalize(
        _load(runner.invoke(app, ["audit", "--db", str(tmp_db), "--json"]).stdout), tmp_path, tmp_library, tmp_db
    )
    assert audit["schema_version"] == 1
    assert audit["command"] == "audit"
    assert audit["db_path"] == "<DB>"
    assert audit["result"]["total_files"] == 5
    assert audit["result"]["fn_issues_by_type"]["illegal_chars"] == 1
    assert audit["result"]["fn_issues_by_type"]["unicode_normalization"] == 1

    search = _normalize(
        _load(runner.invoke(app, ["search", "RAIN", "--db", str(tmp_db), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert search["command"] == "search"
    assert search["query"] == "RAIN"
    assert [row["filename"] for row in search["results"]] == ["AMB_RAIN_01.wav"]

    out = tmp_path / "library.csv"
    export = _normalize(
        _load(runner.invoke(app, ["export", "--db", str(tmp_db), "--output", str(out), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert export == {
        "schema_version": 1,
        "command": "export",
        "db_path": "<DB>",
        "output": "<TMP>/library.csv",
        "count": 5,
    }


def test_rename_json_contract(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--no-hash", "--json"])
    payload = _normalize(
        _load(runner.invoke(app, ["rename", str(tmp_library), "--db", str(tmp_db), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "rename"
    assert payload["plan"]["schema_version"] == 1
    assert payload["plan"]["pattern"] == "ucs"
    assert any(entry["old_filename"] == "BOOM.wav" for entry in payload["plan"]["entries"])
    assert any(entry["new_filename"].startswith("SFX_MISC_") for entry in payload["plan"]["entries"])


def test_dedupe_summary_and_output_contract(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--json"])

    summary_payload = _normalize(
        _load(runner.invoke(app, ["dedupe", "--db", str(tmp_db), "--summary-only", "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert summary_payload["schema_version"] == 1
    assert summary_payload["command"] == "dedupe"
    assert summary_payload["db_path"] == "<DB>"
    assert summary_payload["plan_path"] is None
    assert summary_payload["summary"]["duplicate_groups"] >= 1
    assert summary_payload["summary"]["extra_copies"] >= 1

    out = tmp_path / "review" / "dedupe_plan.json"
    plan_payload = _normalize(
        _load(runner.invoke(app, ["dedupe", "--db", str(tmp_db), "--output", str(out), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert plan_payload["plan_path"] == "<TMP>/review/dedupe_plan.json"
    assert out.exists()
