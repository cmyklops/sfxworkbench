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

    metadata_backends = runner.invoke(app, ["metadata", "backends", "--json"])
    assert metadata_backends.exit_code == 0
    assert json.loads(metadata_backends.stdout)["command"] == "metadata_backends"

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


def test_tag_plan_review_apply_json(tmp_library, tmp_db, tmp_path) -> None:
    scan = runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert scan.exit_code == 0

    plan_path = tmp_path / "tag_plan.json"
    plan = runner.invoke(
        app,
        ["tag", "plan", str(tmp_library), "--db", str(tmp_db), "--output", str(plan_path), "--json"],
    )
    assert plan.exit_code == 0
    assert json.loads(plan.stdout)["command"] == "tag_plan"
    assert plan_path.exists()

    review = runner.invoke(app, ["tag", "review", str(plan_path), "--approve-all", "--json"])
    assert review.exit_code == 0
    assert json.loads(review.stdout)["command"] == "tag_review"

    log = tmp_path / "tag_apply_log.json"
    apply = runner.invoke(
        app,
        [
            "tag",
            "apply",
            str(plan_path),
            "--db",
            str(tmp_db),
            "--require-reviewed",
            "--apply",
            "--log",
            str(log),
            "--json",
        ],
    )
    assert apply.exit_code == 0
    payload = json.loads(apply.stdout)
    assert payload["command"] == "tag_apply"
    assert payload["result"]["target"] == "db"
    assert log.exists()

    sidecar_path = tmp_path / "accepted_tags.sidecar.json"
    sidecar_export = runner.invoke(
        app,
        [
            "tag",
            "sidecar-export",
            str(sidecar_path),
            "--db",
            str(tmp_db),
            "--path",
            str(tmp_library),
            "--json",
        ],
    )
    assert sidecar_export.exit_code == 0
    sidecar_payload = json.loads(sidecar_export.stdout)
    assert sidecar_payload["command"] == "tag_sidecar_export"
    assert sidecar_payload["report"]["tag_count"] > 0
    assert sidecar_path.exists()

    sidecar_import = runner.invoke(
        app,
        ["tag", "sidecar-import", str(sidecar_path), "--db", str(tmp_db), "--json"],
    )
    assert sidecar_import.exit_code == 0
    import_payload = json.loads(sidecar_import.stdout)
    assert import_payload["command"] == "tag_sidecar_import"
    assert import_payload["result"]["planned"] == sidecar_payload["report"]["tag_count"]

    fake_bwfmetaedit = tmp_path / "bwfmetaedit"
    fake_bwfmetaedit.write_text("#!/bin/sh\necho 'BWF MetaEdit 24.04'\n", encoding="utf-8")
    fake_bwfmetaedit.chmod(0o755)
    metadata_write_plan = tmp_path / "metadata_write_plan.json"
    write_plan = runner.invoke(
        app,
        [
            "metadata",
            "write-plan",
            str(metadata_write_plan),
            "--db",
            str(tmp_db),
            "--path",
            str(tmp_library),
            "--bwfmetaedit",
            str(fake_bwfmetaedit),
            "--json",
        ],
    )
    assert write_plan.exit_code == 0
    write_plan_payload = json.loads(write_plan.stdout)
    assert write_plan_payload["command"] == "metadata_write_plan"
    assert metadata_write_plan.exists()

    write_review = runner.invoke(app, ["metadata", "write-review", str(metadata_write_plan), "--approve-all", "--json"])
    assert write_review.exit_code == 0
    assert json.loads(write_review.stdout)["command"] == "metadata_write_review"

    write_preview = runner.invoke(
        app,
        ["metadata", "write-preview", str(metadata_write_plan), "--db", str(tmp_db), "--require-reviewed", "--json"],
    )
    assert write_preview.exit_code == 0
    assert json.loads(write_preview.stdout)["command"] == "metadata_write_preview"

    fixture_dir = tmp_path / "metadata_fixtures"
    write_fixtures = runner.invoke(
        app,
        [
            "metadata",
            "write-fixtures",
            str(metadata_write_plan),
            str(fixture_dir),
            "--db",
            str(tmp_db),
            "--json",
        ],
    )
    assert write_fixtures.exit_code == 0
    assert json.loads(write_fixtures.stdout)["command"] == "metadata_write_fixtures"
    assert (fixture_dir / "metadata_write_fixture_manifest.json").exists()


def test_similarity_cli_json_smoke(tmp_library, tmp_db, tmp_path) -> None:
    scan = runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert scan.exit_code == 0

    cache = tmp_path / "similarity_cache"
    crawl = runner.invoke(
        app,
        [
            "similarity",
            "crawl",
            str(tmp_library),
            "--db",
            str(tmp_db),
            "--cache",
            str(cache),
            "--limit",
            "1",
            "--json",
        ],
    )
    assert crawl.exit_code == 0
    assert json.loads(crawl.stdout)["command"] == "similarity_crawl"

    segments = runner.invoke(
        app, ["similarity", "segments", str(tmp_library), "--db", str(tmp_db), "--limit", "1", "--json"]
    )
    assert segments.exit_code == 0
    assert json.loads(segments.stdout)["command"] == "similarity_segments"

    query_file = tmp_library / "sounds" / "AMB_RAIN_01.wav"
    search = runner.invoke(app, ["similarity", "search", "--file", str(query_file), "--db", str(tmp_db), "--json"])
    assert search.exit_code == 0
    assert json.loads(search.stdout)["report"]["scope"] == "file"

    segment_search = runner.invoke(
        app,
        ["similarity", "search", "--file", str(query_file), "--db", str(tmp_db), "--scope", "segment", "--json"],
    )
    assert segment_search.exit_code == 0
    assert json.loads(segment_search.stdout)["report"]["scope"] == "segment"

    audit = runner.invoke(app, ["similarity", "audit", str(tmp_library), "--db", str(tmp_db), "--json"])
    assert audit.exit_code == 0
    assert json.loads(audit.stdout)["report"]["scope"] == "file"

    segment_audit = runner.invoke(
        app, ["similarity", "audit", str(tmp_library), "--db", str(tmp_db), "--scope", "segment", "--json"]
    )
    assert segment_audit.exit_code == 0
    assert json.loads(segment_audit.stdout)["report"]["scope"] == "segment"

    other_file = tmp_library / "sounds" / "SFX_GUNSHOT_01.wav"
    feedback_set = runner.invoke(
        app,
        [
            "similarity",
            "feedback",
            "set",
            "--left",
            str(query_file),
            "--right",
            str(other_file),
            "--state",
            "ignored",
            "--db",
            str(tmp_db),
            "--json",
        ],
    )
    assert feedback_set.exit_code == 0
    assert json.loads(feedback_set.stdout)["command"] == "similarity_feedback_set"

    feedback_list = runner.invoke(
        app, ["similarity", "feedback", "list", "--db", str(tmp_db), "--state", "ignored", "--json"]
    )
    assert feedback_list.exit_code == 0
    assert json.loads(feedback_list.stdout)["report"]["summary"]["total"] == 1

    feedback_clear = runner.invoke(
        app,
        [
            "similarity",
            "feedback",
            "clear",
            "--left",
            str(query_file),
            "--right",
            str(other_file),
            "--db",
            str(tmp_db),
            "--json",
        ],
    )
    assert feedback_clear.exit_code == 0
    assert json.loads(feedback_clear.stdout)["result"]["removed"] == 1


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
