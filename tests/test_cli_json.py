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

    metadata = runner.invoke(app, ["metadata", "audit", "--db", str(tmp_db), "--json"])
    assert metadata.exit_code == 0
    assert json.loads(metadata.stdout)["command"] == "metadata_audit"

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

    groups = runner.invoke(app, ["groups", "audit", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert groups.exit_code == 0
    assert json.loads(groups.stdout)["command"] == "groups_audit"

    format_audit = runner.invoke(app, ["format", "audit", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert format_audit.exit_code == 0
    assert json.loads(format_audit.stdout)["command"] == "format_audit"

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

    plan_path = tmp_path / "nesting_plan.json"
    plan = runner.invoke(
        app,
        ["organize", "nesting-plan", str(out), "--output", str(plan_path), "--json"],
    )
    assert plan.exit_code == 0
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["command"] == "organize_nesting_plan"
    assert plan_payload["plan"]["entries"]
    assert plan_path.exists()

    review = runner.invoke(app, ["organize", "review", str(plan_path), "--approve-all", "--json"])
    assert review.exit_code == 0

    apply = runner.invoke(app, ["organize", "nesting-apply", str(plan_path), "--require-reviewed", "--json"])
    assert apply.exit_code == 0
    apply_payload = json.loads(apply.stdout)
    assert apply_payload["command"] == "organize_nesting_apply"
    assert apply_payload["result"]["dry_run"] is True


def test_organize_single_child_nesting_plan_json(tmp_library, tmp_path) -> None:
    audio = tmp_library / "Wrapper" / "Real Pack" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    report_path = tmp_path / "nesting.json"
    plan_path = tmp_path / "single_child_plan.json"
    audit = runner.invoke(
        app,
        [
            "organize",
            "audit",
            str(tmp_library),
            "--pattern",
            "redundant-nesting",
            "--depth",
            "3",
            "--output",
            str(report_path),
            "--json",
        ],
    )
    assert audit.exit_code == 0

    plan = runner.invoke(
        app,
        [
            "organize",
            "nesting-plan",
            str(report_path),
            "--kind",
            "single_child_chain",
            "--output",
            str(plan_path),
            "--json",
        ],
    )

    assert plan.exit_code == 0
    payload = json.loads(plan.stdout)
    assert payload["command"] == "organize_nesting_plan"
    assert payload["plan"]["entries"][0]["kind"] == "single_child_chain"
    assert payload["plan"]["entries"][0]["action"] == "collapse_single_child_wrapper"


def test_organize_low_value_wrapper_nesting_plan_json(tmp_library, tmp_path) -> None:
    audio = tmp_library / "Pack" / "Samples" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    report_path = tmp_path / "nesting.json"
    plan_path = tmp_path / "wrapper_plan.json"
    audit = runner.invoke(
        app,
        [
            "organize",
            "audit",
            str(tmp_library),
            "--pattern",
            "redundant-nesting",
            "--depth",
            "3",
            "--output",
            str(report_path),
            "--json",
        ],
    )
    assert audit.exit_code == 0

    plan = runner.invoke(
        app,
        [
            "organize",
            "nesting-plan",
            str(report_path),
            "--kind",
            "low_value_wrapper",
            "--output",
            str(plan_path),
            "--json",
        ],
    )

    assert plan.exit_code == 0
    payload = json.loads(plan.stdout)
    assert payload["command"] == "organize_nesting_plan"
    assert payload["plan"]["entries"][0]["kind"] == "low_value_wrapper"
    assert payload["plan"]["entries"][0]["action"] == "flatten_low_value_leaf_wrapper"
