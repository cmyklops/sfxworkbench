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

    metadata_out = tmp_path / "metadata_report.json"
    metadata = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "metadata",
                    "audit",
                    "--db",
                    str(tmp_db),
                    "--output",
                    str(metadata_out),
                    "--limit",
                    "2",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert metadata["schema_version"] == 1
    assert metadata["command"] == "metadata_audit"
    assert metadata["db_path"] == "<DB>"
    assert metadata["report_path"] == "<TMP>/metadata_report.json"
    assert metadata["report"]["summary"]["total_files"] == 5
    assert metadata["report"]["summary"]["reported_missing_metadata"] == 2
    assert len(metadata["report"]["missing_metadata"]) == 2
    assert metadata_out.exists()

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

    review_payload = _normalize(
        _load(runner.invoke(app, ["dedupe", "--review", str(out), "--approve-all", "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert review_payload["schema_version"] == 1
    assert review_payload["command"] == "dedupe_review"
    assert review_payload["result"]["approved_groups"] >= 1


def test_scan_errors_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"\x00" * 128)
    from wavwarden.db import get_connection

    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, scan_error, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(bad), bad.name, bad.stem, bad.suffix, bad.stat().st_size, 0.0, "Format not recognised.", "2026"),
    )
    conn.commit()
    conn.close()

    out = tmp_path / "scan_error_plan.json"
    payload = _normalize(
        _load(runner.invoke(app, ["scan-errors", "--db", str(tmp_db), "--output", str(out), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "scan_errors"
    assert payload["plan_path"] == "<TMP>/scan_error_plan.json"
    assert payload["plan"]["entries"][0]["action"] == "quarantine"
    assert out.exists()


def test_packs_audit_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    from wavwarden.db import get_connection

    pack_a = tmp_library / "Pack A"
    pack_b = tmp_library / "Pack B"
    pack_a.mkdir()
    pack_b.mkdir()
    conn = get_connection(tmp_db)
    for path, md5 in [
        (pack_a / "one.wav", "A"),
        (pack_a / "two.wav", "B"),
        (pack_b / "one.wav", "A"),
        (pack_b / "two.wav", "B"),
    ]:
        conn.execute(
            """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(path), path.name, path.stem, path.suffix, 10, 0.0, md5, "2026"),
        )
    conn.commit()
    conn.close()

    out = tmp_path / "pack_report.json"
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["packs", "audit", str(tmp_library), "--db", str(tmp_db), "--output", str(out), "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "packs_audit"
    assert payload["db_path"] == "<DB>"
    assert payload["root"] == "<ROOT>"
    assert payload["report_path"] == "<TMP>/pack_report.json"
    assert payload["report"]["schema_version"] == 1
    assert payload["report"]["summary"]["exact_duplicate_groups"] == 1
    assert out.exists()


def test_groups_audit_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    from wavwarden.db import get_connection

    root = tmp_library
    conn = get_connection(tmp_db)
    for name in ["Metal Hit 01.wav", "Metal Hit 02.wav"]:
        path = root / "Impacts" / name
        conn.execute(
            """INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, md5,
                sample_rate, bit_depth, channels, duration_s, scanned_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(path), path.name, path.stem, path.suffix, 10, 0.0, name, 48000, 24, 2, 1.0, "2026"),
        )
    conn.commit()
    conn.close()

    out = tmp_path / "groups_report.json"
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["groups", "audit", str(root), "--db", str(tmp_db), "--output", str(out), "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "groups_audit"
    assert payload["root"] == "<ROOT>"
    assert payload["db_path"] == "<DB>"
    assert payload["report_path"] == "<TMP>/groups_report.json"
    assert payload["report"]["schema_version"] == 1
    assert payload["report"]["summary"]["candidate_groups"] == 1
    assert payload["report"]["groups"][0]["inferred_stem"] == "Metal Hit"
    assert out.exists()


def test_organize_audit_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    folder = tmp_library / "01 Pack"
    folder.mkdir()
    out = tmp_path / "organize_report.json"
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["organize", "audit", str(tmp_library), "--output", str(out), "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload == {
        "schema_version": 1,
        "command": "organize_audit",
        "root": "<ROOT>",
        "report_path": "<TMP>/organize_report.json",
        "report": {
            "schema_version": 1,
            "tool": "wavwarden",
            "tool_version": "0.1.0",
            "root": "<ROOT>",
            "pattern": "strip-leading-numbers",
            "depth": 1,
            "summary": {
                "directories_scanned": 5,
                "planned": 1,
                "candidates": 0,
                "errors": 0,
            },
            "entries": [
                {
                    "old_path": "<ROOT>/01 Pack",
                    "new_path": "<ROOT>/Pack",
                    "old_name": "01 Pack",
                    "new_name": "Pack",
                    "action": "rename",
                    "reason": "strip_leading_number",
                }
            ],
            "candidates": [],
            "errors": [],
        },
    }
    assert out.exists()
