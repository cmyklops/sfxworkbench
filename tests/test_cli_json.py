"""CLI smoke tests for JSON output."""

import json

from typer.testing import CliRunner
from wavwarden.cli import app

runner = CliRunner()


def test_scan_audit_search_export_json(tmp_library, tmp_db, tmp_path) -> None:
    scan = runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--no-hash", "--json"])
    assert scan.exit_code == 0
    assert json.loads(scan.stdout)["command"] == "scan"

    audit = runner.invoke(app, ["audit", "--db", str(tmp_db), "--json"])
    assert audit.exit_code == 0
    assert json.loads(audit.stdout)["command"] == "audit"

    search = runner.invoke(app, ["search", "RAIN", "--db", str(tmp_db), "--json"])
    assert search.exit_code == 0
    assert json.loads(search.stdout)["results"]

    out = tmp_path / "library.csv"
    export = runner.invoke(app, ["export", "--db", str(tmp_db), "--output", str(out), "--json"])
    assert export.exit_code == 0
    assert json.loads(export.stdout)["count"] > 0


def test_clean_dedupe_rename_json(tmp_library, tmp_db, tmp_path) -> None:
    clean = runner.invoke(app, ["clean", str(tmp_library), "--json"])
    assert clean.exit_code == 0
    assert json.loads(clean.stdout)["command"] == "clean"

    scan = runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert scan.exit_code == 0

    with runner.isolated_filesystem(temp_dir=tmp_path):
        dedupe = runner.invoke(app, ["dedupe", "--db", str(tmp_db), "--summary-only", "--json"])
        assert dedupe.exit_code == 0
        payload = json.loads(dedupe.stdout)
        assert payload["command"] == "dedupe"
        assert payload["plan_path"] is None
        assert "summary" in payload

    rename = runner.invoke(app, ["rename", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert rename.exit_code == 0
    assert json.loads(rename.stdout)["command"] == "rename"


def test_packs_audit_json(tmp_library, tmp_db, tmp_path) -> None:
    scan = runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert scan.exit_code == 0

    out = tmp_path / "packs.json"
    packs = runner.invoke(
        app, ["packs", "audit", str(tmp_library), "--db", str(tmp_db), "--output", str(out), "--json"]
    )

    assert packs.exit_code == 0
    payload = json.loads(packs.stdout)
    assert payload["command"] == "packs_audit"
    assert payload["report_path"] == str(out)
    assert "summary" in payload["report"]
    assert out.exists()
