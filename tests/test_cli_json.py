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


def test_organize_audit_json(tmp_library, tmp_path) -> None:
    (tmp_library / "01 Pack").mkdir()
    out = tmp_path / "organize.json"
    organize = runner.invoke(app, ["organize", "audit", str(tmp_library), "--output", str(out), "--json"])

    assert organize.exit_code == 0
    payload = json.loads(organize.stdout)
    assert payload["command"] == "organize_audit"
    assert payload["report_path"] == str(out)
    assert payload["report"]["summary"]["planned"] == 1
    assert out.exists()

    review = runner.invoke(app, ["organize", "review", str(out), "--approve-all", "--json"])
    assert review.exit_code == 0
    assert json.loads(review.stdout)["command"] == "organize_review"

    log = tmp_path / "organize_log.json"
    apply = runner.invoke(app, ["organize", "apply", str(out), "--log", str(log), "--require-reviewed", "--json"])
    assert apply.exit_code == 0
    assert json.loads(apply.stdout)["command"] == "organize_apply"
    assert log.exists()

    undo = runner.invoke(app, ["organize", "undo", str(log), "--apply", "--json"])
    assert undo.exit_code == 0
    assert json.loads(undo.stdout)["command"] == "organize_undo"


def test_organize_redundant_nesting_json(tmp_library, tmp_path) -> None:
    audio = tmp_library / "Vendor" / "Pack" / "Pack" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    out = tmp_path / "nesting.json"

    organize = runner.invoke(
        app,
        [
            "organize",
            "audit",
            str(tmp_library),
            "--pattern",
            "redundant-nesting",
            "--depth",
            "4",
            "--output",
            str(out),
            "--json",
        ],
    )

    assert organize.exit_code == 0
    payload = json.loads(organize.stdout)
    assert payload["command"] == "organize_audit"
    assert payload["report"]["pattern"] == "redundant-nesting"
    assert payload["report"]["summary"]["candidates"] >= 1
    assert any(candidate["kind"] == "repeated_folder_name" for candidate in payload["report"]["candidates"])
    assert out.exists()
