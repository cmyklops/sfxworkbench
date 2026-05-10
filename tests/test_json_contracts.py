"""Contract-grade checks for normalized CLI JSON output."""

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner
from wavwarden import metadata_backends, metadata_write
from wavwarden.cli import app
from wavwarden.db import get_connection

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


def _seed_metadata_write_file(tmp_db: Path, path: Path) -> None:
    h = hashlib.md5()
    h.update(path.read_bytes())
    conn = get_connection(tmp_db)
    cursor = conn.execute(
        """
        INSERT INTO files (
            path, filename, stem, extension, size_bytes, mtime, md5,
            sample_rate, bit_depth, channels, duration_s, scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path),
            path.name,
            path.stem,
            path.suffix.lower(),
            path.stat().st_size,
            path.stat().st_mtime,
            h.hexdigest(),
            48000,
            24,
            2,
            1.0,
            "2026",
        ),
    )
    file_id = cursor.lastrowid
    for field, value in (("description", "Metal Hit"), ("category", "SFX")):
        conn.execute(
            """
            INSERT INTO accepted_tags (
                file_id, field, value, source, method, confidence, evidence,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (file_id, field, value, "test", "manual", 0.95, json.dumps(["fixture"]), "2026", "2026"),
        )
    conn.commit()
    conn.close()


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

    metadata_backends = _normalize(
        _load(runner.invoke(app, ["metadata", "backends", "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert metadata_backends["schema_version"] == 1
    assert metadata_backends["command"] == "metadata_backends"
    assert metadata_backends["bwfmetaedit"] is None
    assert metadata_backends["report"]["schema_version"] == 1
    assert metadata_backends["report"]["recommended_backend"] == "auto"
    assert metadata_backends["report"]["backends"][0]["name"] == "bwfmetaedit"
    assert metadata_backends["report"]["backends"][1]["name"] == "mutagen"
    assert "available" in metadata_backends["report"]["backends"][0]

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


def test_similarity_crawl_json_contract(tmp_library: Path, tmp_db: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--no-hash", "--json"])

    payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "crawl",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
                    "--cache",
                    str(tmp_path / "similarity_cache"),
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

    assert payload["schema_version"] == 1
    assert payload["command"] == "similarity_crawl"
    assert payload["root"] == "<ROOT>"
    assert payload["db_path"] == "<DB>"
    assert payload["cache_path"] == "<TMP>/similarity_cache"
    assert payload["report"]["backend"] == "deterministic_v1"
    assert payload["report"]["summary"]["total_files"] == 4
    assert payload["report"]["summary"]["analyzed"] == 4
    assert "segments_detected" in payload["report"]["summary"]
    assert len(payload["report"]["descriptors"]) == 2
    assert payload["report"]["descriptors"][0]["duration_bucket"] is not None
    assert "spectral_centroid" in payload["report"]["descriptors"][0]
    assert "segment_count" in payload["report"]["descriptors"][0]

    segments_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "segments",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
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

    assert segments_payload["schema_version"] == 1
    assert segments_payload["command"] == "similarity_segments"
    assert segments_payload["root"] == "<ROOT>"
    assert segments_payload["db_path"] == "<DB>"
    assert segments_payload["report"]["summary"]["segments"] >= 0
    assert isinstance(segments_payload["report"]["segments"], list)

    search_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "search",
                    "--file",
                    str(tmp_library / "sounds" / "AMB_RAIN_01.wav"),
                    "--db",
                    str(tmp_db),
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

    assert search_payload["schema_version"] == 1
    assert search_payload["command"] == "similarity_search"
    assert search_payload["query_path"] == "<ROOT>/sounds/AMB_RAIN_01.wav"
    assert search_payload["db_path"] == "<DB>"
    assert search_payload["report"]["backend"] == "deterministic_v1"
    assert search_payload["report"]["scope"] == "file"
    assert search_payload["report"]["candidates_considered"] == 4
    assert len(search_payload["report"]["results"]) == 2
    assert "spectral_centroid" in search_payload["report"]["query_descriptor"]
    assert "spectral_centroid" in search_payload["report"]["results"][0]
    assert search_payload["report"]["results"][0]["score"] >= search_payload["report"]["results"][1]["score"]

    segment_search_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "search",
                    "--file",
                    str(tmp_library / "sounds" / "AMB_RAIN_01.wav"),
                    "--db",
                    str(tmp_db),
                    "--scope",
                    "segment",
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

    assert segment_search_payload["schema_version"] == 1
    assert segment_search_payload["command"] == "similarity_search"
    assert segment_search_payload["report"]["scope"] == "segment"
    assert isinstance(segment_search_payload["report"]["results"], list)

    audit_out = tmp_path / "similarity_audit.json"
    audit_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "audit",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
                    "--threshold",
                    "0.9",
                    "--output",
                    str(audit_out),
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

    assert audit_payload["schema_version"] == 1
    assert audit_payload["command"] == "similarity_audit"
    assert audit_payload["root"] == "<ROOT>"
    assert audit_payload["db_path"] == "<DB>"
    assert audit_payload["report_path"] == "<TMP>/similarity_audit.json"
    assert audit_payload["report"]["scope"] == "file"
    assert audit_payload["report"]["threshold"] == 0.9
    assert audit_payload["report"]["summary"]["descriptors_considered"] == 4
    assert "candidate_comparisons" in audit_payload["report"]["summary"]
    assert audit_payload["report"]["summary"]["reported_groups"] <= 2
    assert audit_out.exists()

    segment_audit_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "audit",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
                    "--scope",
                    "segment",
                    "--limit",
                    "1",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert segment_audit_payload["schema_version"] == 1
    assert segment_audit_payload["command"] == "similarity_audit"
    assert segment_audit_payload["report"]["scope"] == "segment"
    assert isinstance(segment_audit_payload["report"]["groups"], list)

    feedback_set_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "feedback",
                    "set",
                    "--left",
                    str(tmp_library / "sounds" / "AMB_RAIN_01.wav"),
                    "--right",
                    str(tmp_library / "sounds" / "SFX_GUNSHOT_01.wav"),
                    "--state",
                    "favorite",
                    "--note",
                    "contract",
                    "--db",
                    str(tmp_db),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert feedback_set_payload["schema_version"] == 1
    assert feedback_set_payload["command"] == "similarity_feedback_set"
    assert feedback_set_payload["db_path"] == "<DB>"
    assert feedback_set_payload["result"]["action"] == "set"
    assert feedback_set_payload["result"]["entry"]["state"] == "favorite"
    assert {
        feedback_set_payload["result"]["entry"]["left_path"],
        feedback_set_payload["result"]["entry"]["right_path"],
    } == {"<ROOT>/sounds/AMB_RAIN_01.wav", "<ROOT>/sounds/SFX_GUNSHOT_01.wav"}

    feedback_list_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "feedback",
                    "list",
                    "--db",
                    str(tmp_db),
                    "--state",
                    "favorite",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert feedback_list_payload["schema_version"] == 1
    assert feedback_list_payload["command"] == "similarity_feedback_list"
    assert feedback_list_payload["report"]["summary"]["total"] == 1
    assert feedback_list_payload["report"]["entries"][0]["note"] == "contract"

    feedback_clear_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "similarity",
                    "feedback",
                    "clear",
                    "--left",
                    str(tmp_library / "sounds" / "AMB_RAIN_01.wav"),
                    "--right",
                    str(tmp_library / "sounds" / "SFX_GUNSHOT_01.wav"),
                    "--db",
                    str(tmp_db),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert feedback_clear_payload["schema_version"] == 1
    assert feedback_clear_payload["command"] == "similarity_feedback_clear"
    assert feedback_clear_payload["result"]["removed"] == 1


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
        _load(
            runner.invoke(
                app,
                [
                    "dedupe",
                    "--db",
                    str(tmp_db),
                    "--safe-folder",
                    str(tmp_library),
                    "--prefer-extension",
                    "wav",
                    "--output",
                    str(out),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert plan_payload["plan_path"] == "<TMP>/review/dedupe_plan.json"
    assert out.exists()
    plan_file = _normalize(json.loads(out.read_text()), tmp_path, tmp_library, tmp_db)
    assert plan_file["safe_folders"] == ["<ROOT>"]
    assert plan_file["preservation_priority"]["rules"] == [
        {"rule": "prefer_safe_folder", "values": ["<ROOT>"]},
        {"rule": "prefer_extension", "values": [".wav"]},
    ]

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
        path.write_bytes(b"x" * 10)
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

    plan_out = tmp_path / "pack_plan.json"
    plan_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "packs",
                    "plan",
                    "--report",
                    str(out),
                    "--safe-folder",
                    str(pack_a),
                    "--prefer-folder",
                    str(pack_a),
                    "--output",
                    str(plan_out),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert plan_payload["schema_version"] == 1
    assert plan_payload["command"] == "packs_plan"
    assert plan_payload["report_path"] == "<TMP>/pack_report.json"
    assert plan_payload["plan_path"] == "<TMP>/pack_plan.json"
    assert plan_payload["plan"]["safe_folders"] == ["<ROOT>/Pack A"]
    assert plan_payload["plan"]["preservation_priority"]["rules"] == [
        {"rule": "prefer_safe_folder", "values": ["<ROOT>/Pack A"]},
        {"rule": "prefer_folder", "values": ["<ROOT>/Pack A"]},
    ]
    assert plan_payload["plan"]["summary"]["quarantine_entries"] == 1

    review_payload = _normalize(
        _load(runner.invoke(app, ["packs", "review", str(plan_out), "--approve-all", "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert review_payload["schema_version"] == 1
    assert review_payload["command"] == "packs_review"
    assert review_payload["result"]["approved_groups"] == 1

    apply_payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["packs", "apply", str(plan_out), "--require-reviewed", "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert apply_payload["schema_version"] == 1
    assert apply_payload["command"] == "packs_apply"
    assert apply_payload["result"]["dry_run"] is True
    assert apply_payload["result"]["quarantined"] == 1


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


def test_format_audit_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    from wavwarden.db import get_connection

    root = tmp_library
    conn = get_connection(tmp_db)
    for name, sample_rate in [("Metal Hit 01.wav", 44100), ("Metal Hit 02.wav", 48000)]:
        path = root / "Impacts" / name
        conn.execute(
            """INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, md5,
                sample_rate, bit_depth, channels, duration_s, scanned_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(path), path.name, path.stem, path.suffix, 10, 0.0, name, sample_rate, 24, 2, 1.0, "2026"),
        )
    conn.commit()
    conn.close()

    out = tmp_path / "format_report.json"
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["format", "audit", str(root), "--db", str(tmp_db), "--output", str(out), "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "format_audit"
    assert payload["root"] == "<ROOT>"
    assert payload["db_path"] == "<DB>"
    assert payload["report_path"] == "<TMP>/format_report.json"
    assert payload["report"]["schema_version"] == 1
    assert payload["report"]["summary"]["inconsistent_groups"] == 1
    assert payload["report"]["groups"][0]["action"] == "review_only"
    assert payload["report"]["groups"][0]["inconsistencies"][0] == {
        "field": "sample_rate",
        "values": [44100, 48000],
    }
    assert out.exists()


def test_ucs_import_info_categories_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    src.write_text(
        "\n".join(
            [
                "Category,SubCategory,CatID,CatShort,Explanations,Synonyms - Comma Separated",
                'AIR,BLOW,AIRBlow,AIR,"Steady air blows.","Aerate, Air"',
                'AMBIENCE,BACKYRD,AMBBack,AMB,"Backyard ambience.","Yard, Garden"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cache = tmp_path / "ucs_catalog.json"

    import_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "ucs",
                    "import",
                    str(src),
                    "--output",
                    str(cache),
                    "--release-version",
                    "v8.2.1",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert import_payload["schema_version"] == 1
    assert import_payload["command"] == "ucs_import"
    assert import_payload["catalog_path"] == "<TMP>/ucs_catalog.json"
    assert import_payload["source"] == "<TMP>/_categorylist.csv"
    assert import_payload["result"]["entry_count"] == 2
    assert import_payload["result"]["unique_cat_shorts"] == 2
    assert import_payload["result"]["release_version"] == "v8.2.1"
    assert cache.exists()

    info_payload = _normalize(
        _load(runner.invoke(app, ["ucs", "info", "--catalog", str(cache), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert info_payload["schema_version"] == 1
    assert info_payload["command"] == "ucs_info"
    assert info_payload["loaded"] is True
    assert info_payload["catalog_path"] == "<TMP>/ucs_catalog.json"
    assert info_payload["entry_count"] == 2
    assert info_payload["provenance"]["release_version"] == "v8.2.1"

    cat_payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["ucs", "categories", "--catalog", str(cache), "--cat-short", "AIR", "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert cat_payload["schema_version"] == 1
    assert cat_payload["command"] == "ucs_categories"
    assert cat_payload["result"]["matched"] == 1
    assert cat_payload["result"]["total_loaded"] == 2
    assert cat_payload["result"]["entries"][0]["subcategory"] == "BLOW"


def test_tag_suggest_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--no-hash", "--json"])

    out = tmp_path / "tag_suggestions.json"
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["tag", "suggest", str(tmp_library), "--db", str(tmp_db), "--output", str(out), "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "tag_suggest"
    assert payload["root"] == "<ROOT>"
    assert payload["db_path"] == "<DB>"
    assert payload["report_path"] == "<TMP>/tag_suggestions.json"
    assert payload["report"]["schema_version"] == 1
    assert payload["report"]["tool"] == "wavwarden"
    assert payload["report"]["min_confidence"] == 0.0
    assert payload["report"]["synonym_limit"] == 0
    assert payload["report"]["synonym_depth"] == 0
    assert payload["report"]["summary"]["files_considered"] >= 1

    # Confirm UCS-named fixtures (AMB_RAIN_01, SFX_GUNSHOT_01) yield ucs_stem suggestions.
    ucs_entries = [
        entry for entry in payload["report"]["entries"] if any(s["source"] == "ucs_stem" for s in entry["suggestions"])
    ]
    assert ucs_entries, "expected at least one UCS-derived suggestion entry"
    sample = ucs_entries[0]
    fields = {s["field"] for s in sample["suggestions"]}
    assert {"ucs_category", "ucs_subcategory", "description"} <= fields
    assert out.exists()

    synonym_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "tag",
                    "suggest",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
                    "--include-synonyms",
                    "--synonym-limit",
                    "2",
                    "--synonym-depth",
                    "1",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert synonym_payload["report"]["synonym_limit"] == 2
    assert synonym_payload["report"]["synonym_depth"] == 1

    plan_out = tmp_path / "tag_plan.json"
    plan_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "tag",
                    "plan",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
                    "--from-suggestions",
                    str(out),
                    "--output",
                    str(plan_out),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert plan_payload["schema_version"] == 1
    assert plan_payload["command"] == "tag_plan"
    assert plan_payload["plan_path"] == "<TMP>/tag_plan.json"
    assert plan_payload["plan"]["target"] == "db"
    assert plan_payload["plan"]["summary"]["candidate_entries"] >= 1
    assert plan_payload["plan"]["entries"][0]["review_status"] == "pending"

    review_payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["tag", "review", str(plan_out), "--entry", "1", "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert review_payload["schema_version"] == 1
    assert review_payload["command"] == "tag_review"
    assert review_payload["result"]["approved_entries"] == 1

    tag_log = tmp_path / "tag_apply_log.json"
    apply_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "tag",
                    "apply",
                    str(plan_out),
                    "--db",
                    str(tmp_db),
                    "--require-reviewed",
                    "--apply",
                    "--log",
                    str(tag_log),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert apply_payload["schema_version"] == 1
    assert apply_payload["command"] == "tag_apply"
    assert apply_payload["result"]["target"] == "db"
    assert apply_payload["result"]["dry_run"] is False
    assert apply_payload["result"]["applied"] == 1
    assert apply_payload["result"]["log_path"] == "<TMP>/tag_apply_log.json"

    sidecar_out = tmp_path / "accepted_tags.sidecar.json"
    sidecar_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "tag",
                    "sidecar-export",
                    str(sidecar_out),
                    "--db",
                    str(tmp_db),
                    "--path",
                    str(tmp_library),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert sidecar_payload["schema_version"] == 1
    assert sidecar_payload["command"] == "tag_sidecar_export"
    assert sidecar_payload["db_path"] == "<DB>"
    assert sidecar_payload["root"] == "<ROOT>"
    assert sidecar_payload["sidecar_path"] == "<TMP>/accepted_tags.sidecar.json"
    assert sidecar_payload["report"]["schema_version"] == 1
    assert sidecar_payload["report"]["entry_count"] == 1
    assert sidecar_payload["report"]["tag_count"] == 1
    assert sidecar_payload["report"]["entries"][0]["path"].startswith("<ROOT>/")

    sidecar_import_payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["tag", "sidecar-import", str(sidecar_out), "--db", str(tmp_db), "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert sidecar_import_payload["schema_version"] == 1
    assert sidecar_import_payload["command"] == "tag_sidecar_import"
    assert sidecar_import_payload["db_path"] == "<DB>"
    assert sidecar_import_payload["sidecar_path"] == "<TMP>/accepted_tags.sidecar.json"
    assert sidecar_import_payload["result"]["planned"] == 1
    assert sidecar_import_payload["result"]["skipped"] == 1

    fake_bwfmetaedit = tmp_path / "bwfmetaedit"
    fake_bwfmetaedit.write_text("#!/bin/sh\necho 'BWF MetaEdit 24.04'\n", encoding="utf-8")
    fake_bwfmetaedit.chmod(0o755)
    write_plan_out = tmp_path / "metadata_write_plan.json"
    write_plan_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "metadata",
                    "write-plan",
                    str(write_plan_out),
                    "--db",
                    str(tmp_db),
                    "--path",
                    str(tmp_library),
                    "--bwfmetaedit",
                    str(fake_bwfmetaedit),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert write_plan_payload["schema_version"] == 1
    assert write_plan_payload["command"] == "metadata_write_plan"
    assert write_plan_payload["db_path"] == "<DB>"
    assert write_plan_payload["root"] == "<ROOT>"
    assert write_plan_payload["plan_path"] == "<TMP>/metadata_write_plan.json"
    assert write_plan_payload["plan"]["dry_run_only"] is True
    assert write_plan_payload["plan"]["backend"]["available"] is True
    assert write_plan_payload["plan"]["backend"]["name"] == "auto"
    assert write_plan_payload["plan"]["backends"][0]["executable"] == "<TMP>/bwfmetaedit"
    assert write_plan_payload["plan"]["summary"]["candidate_entries"] == 1
    assert write_plan_payload["plan"]["summary"]["supported_entries"] <= 1

    write_review_payload = _normalize(
        _load(runner.invoke(app, ["metadata", "write-review", str(write_plan_out), "--approve-all", "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert write_review_payload["schema_version"] == 1
    assert write_review_payload["command"] == "metadata_write_review"
    assert write_review_payload["result"]["approved_entries"] == 1

    write_preview_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "metadata",
                    "write-preview",
                    str(write_plan_out),
                    "--db",
                    str(tmp_db),
                    "--require-reviewed",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert write_preview_payload["schema_version"] == 1
    assert write_preview_payload["command"] == "metadata_write_preview"
    assert write_preview_payload["result"]["dry_run"] is True
    assert write_preview_payload["result"]["planned"] == 1
    assert isinstance(write_preview_payload["result"]["commands"], list)
    if write_preview_payload["result"]["commands"]:
        rendered = write_preview_payload["result"]["commands"][0]
        assert rendered["simulated"] is True
        assert "--simulate" in rendered["command"]

    fixture_dir = tmp_path / "metadata_fixtures"
    write_fixtures_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "metadata",
                    "write-fixtures",
                    str(write_plan_out),
                    str(fixture_dir),
                    "--db",
                    str(tmp_db),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert write_fixtures_payload["schema_version"] == 1
    assert write_fixtures_payload["command"] == "metadata_write_fixtures"
    assert write_fixtures_payload["plan_path"] == "<TMP>/metadata_write_plan.json"
    assert write_fixtures_payload["output_dir"] == "<TMP>/metadata_fixtures"
    assert write_fixtures_payload["bundle"]["dry_run"] is True
    assert isinstance(write_fixtures_payload["bundle"]["files"], list)

    write_readback_payload = _normalize(
        _load(runner.invoke(app, ["metadata", "write-readback", str(fixture_dir), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert write_readback_payload["schema_version"] == 1
    assert write_readback_payload["command"] == "metadata_write_readback"
    assert write_readback_payload["manifest_path"] == "<TMP>/metadata_fixtures"
    assert (
        write_readback_payload["report"]["manifest_path"]
        == "<TMP>/metadata_fixtures/metadata_write_fixture_manifest.json"
    )
    assert "files_checked" in write_readback_payload["report"]["summary"]


def test_metadata_write_apply_and_undo_json_contract(
    tmp_db: Path, tmp_path: Path, tmp_library: Path, monkeypatch
) -> None:
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")
    readbacks: dict[Path, dict[str, str]] = {}

    def fake_write_mutagen_fields(path: Path, fields: dict[str, str]) -> None:
        path.write_bytes(path.read_bytes() + b"\nTAGS")
        readbacks[path] = dict(fields)

    monkeypatch.setattr(metadata_write, "write_mutagen_fields", fake_write_mutagen_fields)
    monkeypatch.setattr(metadata_write, "read_mutagen_fields", lambda path, _fields: readbacks.get(path, {}))

    audio = tmp_library / "sounds" / "SFX_HIT_01.flac"
    original = b"not really audio"
    audio.write_bytes(original)
    _seed_metadata_write_file(tmp_db, audio)

    plan_out = tmp_path / "metadata_write_apply_plan.json"
    plan_result = runner.invoke(
        app,
        [
            "metadata",
            "write-plan",
            str(plan_out),
            "--db",
            str(tmp_db),
            "--path",
            str(tmp_library),
            "--json",
        ],
    )
    assert plan_result.exit_code == 0
    review_result = runner.invoke(app, ["metadata", "write-review", str(plan_out), "--approve-all", "--json"])
    assert review_result.exit_code == 0

    dry_run_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "metadata",
                    "write-apply",
                    str(plan_out),
                    "--db",
                    str(tmp_db),
                    "--require-reviewed",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert dry_run_payload["schema_version"] == 1
    assert dry_run_payload["command"] == "metadata_write_apply"
    assert dry_run_payload["plan_path"] == "<TMP>/metadata_write_apply_plan.json"
    assert dry_run_payload["db_path"] == "<DB>"
    assert dry_run_payload["result"]["dry_run"] is True
    assert dry_run_payload["result"]["planned"] == 2
    assert dry_run_payload["result"]["applied"] == 2
    assert dry_run_payload["result"]["files_written"] == 1
    assert dry_run_payload["result"]["backups"] == []

    backup_dir = tmp_path / "metadata_write_backups"
    log_path = tmp_path / "metadata_write_apply_log.json"
    apply_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "metadata",
                    "write-apply",
                    str(plan_out),
                    "--db",
                    str(tmp_db),
                    "--require-reviewed",
                    "--backup-dir",
                    str(backup_dir),
                    "--log",
                    str(log_path),
                    "--apply",
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert apply_payload["schema_version"] == 1
    assert apply_payload["command"] == "metadata_write_apply"
    assert apply_payload["result"]["dry_run"] is False
    assert apply_payload["result"]["applied"] == 2
    assert apply_payload["result"]["files_backed_up"] == 1
    assert apply_payload["result"]["files_verified"] == 1
    assert apply_payload["result"]["backup_dir"] == "<TMP>/metadata_write_backups"
    assert apply_payload["result"]["log_path"] == "<TMP>/metadata_write_apply_log.json"
    assert apply_payload["result"]["backups"][0]["path"] == "<ROOT>/sounds/SFX_HIT_01.flac"
    assert apply_payload["result"]["readback"][0]["matched_fields"] == ["description", "genre"]
    assert audio.read_bytes() == original + b"\nTAGS"

    undo_dry_run_payload = _normalize(
        _load(runner.invoke(app, ["metadata", "write-undo", str(log_path), "--db", str(tmp_db), "--json"]).stdout),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert undo_dry_run_payload["schema_version"] == 1
    assert undo_dry_run_payload["command"] == "metadata_write_undo"
    assert undo_dry_run_payload["log_path"] == "<TMP>/metadata_write_apply_log.json"
    assert undo_dry_run_payload["db_path"] == "<DB>"
    assert undo_dry_run_payload["result"]["dry_run"] is True
    assert undo_dry_run_payload["result"]["planned"] == 1
    assert undo_dry_run_payload["result"]["restored"] == 1

    undo_payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["metadata", "write-undo", str(log_path), "--db", str(tmp_db), "--apply", "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert undo_payload["schema_version"] == 1
    assert undo_payload["command"] == "metadata_write_undo"
    assert undo_payload["result"]["dry_run"] is False
    assert undo_payload["result"]["restored"] == 1
    assert undo_payload["result"]["errors"] == []
    assert audio.read_bytes() == original


def test_ucs_validate_and_catalog_tag_suggest_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    src.write_text(
        "\n".join(
            [
                "Category,SubCategory,CatID,CatShort,Explanations,Synonyms - Comma Separated",
                'AMBIENCE,RAIN,AMBRain,AMB,"Rain ambience.","Rain"',
                'SOUND EFFECT,GUNSHOT,SFXGunshot,SFX,"Gunshot.","Gunshot"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cache = tmp_path / "ucs_catalog.json"
    runner.invoke(app, ["ucs", "import", str(src), "--output", str(cache), "--json"])
    runner.invoke(app, ["scan", str(tmp_library), "--db", str(tmp_db), "--no-hash", "--json"])

    validate_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "ucs",
                    "validate",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
                    "--catalog",
                    str(cache),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert validate_payload["schema_version"] == 1
    assert validate_payload["command"] == "ucs_validate"
    assert validate_payload["root"] == "<ROOT>"
    assert validate_payload["db_path"] == "<DB>"
    assert validate_payload["catalog_path"] == "<TMP>/ucs_catalog.json"
    assert validate_payload["report"]["catalog_path"] == "<TMP>/ucs_catalog.json"
    assert validate_payload["report"]["summary"]["catalog_matches"] == 2
    assert validate_payload["report"]["summary"]["catalog_misses"] == 0

    suggest_payload = _normalize(
        _load(
            runner.invoke(
                app,
                [
                    "tag",
                    "suggest",
                    str(tmp_library),
                    "--db",
                    str(tmp_db),
                    "--ucs-catalog",
                    str(cache),
                    "--json",
                ],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )
    assert suggest_payload["command"] == "tag_suggest"
    assert suggest_payload["ucs_catalog_path"] == "<TMP>/ucs_catalog.json"
    assert suggest_payload["report"]["ucs_catalog_path"] == "<TMP>/ucs_catalog.json"
    assert suggest_payload["report"]["summary"]["by_source"]["ucs_catalog"] >= 1


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


def test_vendor_product_organize_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    folder = tmp_library / "SoundMorph - Energy"
    folder.mkdir()
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["organize", "audit", str(tmp_library), "--pattern", "vendor-product-folders", "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "organize_audit"
    assert payload["report"]["pattern"] == "vendor-product-folders"
    assert payload["report"]["summary"]["planned"] == 1
    assert payload["report"]["entries"][0]["old_path"] == "<ROOT>/SoundMorph - Energy"
    assert payload["report"]["entries"][0]["new_path"] == "<ROOT>/SoundMorph/Energy"
    assert payload["report"]["entries"][0]["reason"] == "vendor_product_refolder"


def test_common_prefix_organize_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    for name in ["GDC 2015 - Soniss", "GDC SFX 2017", "GDC2023"]:
        (tmp_library / name).mkdir()
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["organize", "audit", str(tmp_library), "--pattern", "common-prefix-folders", "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "organize_audit"
    assert payload["report"]["pattern"] == "common-prefix-folders"
    assert payload["report"]["summary"]["planned"] == 3
    assert payload["report"]["entries"][0]["old_path"] == "<ROOT>/GDC 2015 - Soniss"
    assert payload["report"]["entries"][0]["new_path"] == "<ROOT>/GDC/2015 - Soniss"
    assert payload["report"]["entries"][0]["reason"] == "common_prefix_refolder"


def test_numeric_series_organize_json_contract(tmp_db: Path, tmp_path: Path, tmp_library: Path) -> None:
    (tmp_library / "6000").mkdir()
    payload = _normalize(
        _load(
            runner.invoke(
                app,
                ["organize", "audit", str(tmp_library), "--pattern", "numeric-series-folders", "--json"],
            ).stdout
        ),
        tmp_path,
        tmp_library,
        tmp_db,
    )

    assert payload["schema_version"] == 1
    assert payload["command"] == "organize_audit"
    assert payload["report"]["pattern"] == "numeric-series-folders"
    assert payload["report"]["summary"]["planned"] == 1
    assert payload["report"]["entries"][0]["old_path"] == "<ROOT>/6000"
    assert payload["report"]["entries"][0]["new_path"] == "<ROOT>/Sound Ideas/The General Series 6000"
    assert payload["report"]["entries"][0]["reason"] == "numeric_series_catalog"
