"""Tests for the Internal Studio Beta audit harness."""

import json
import subprocess
import sys
from pathlib import Path


def test_internal_beta_audit_writes_report_bundle(tmp_path: Path, tmp_library: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "internal_beta_audit.py"
    output_dir = tmp_path / "beta_reports"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_library),
            "--output-dir",
            str(output_dir),
            "--limit",
            "10",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)

    assert payload["schema_version"] == 1
    assert payload["command"] == "internal_beta_audit"
    assert payload["root"] == str(tmp_library.resolve())
    assert payload["db_path"] == str(output_dir.resolve() / "index.db")
    assert payload["summary"]["scan"]["total"] == 5
    assert payload["summary"]["pack_apply_dry_run"]["dry_run"] is True
    assert payload["include_format"] is False
    assert "format" not in payload["summary"]
    assert "format_report" not in payload["artifacts"]
    assert payload["include_similarity"] is False
    assert payload["similarity_validation"] is False
    assert payload["similarity_validation_mode"] == "disabled"
    for artifact in [
        "scan_result",
        "audit_result",
        "metadata_report",
        "related_groups_report",
        "pack_overlap_report",
        "pack_consolidation_plan",
        "pack_apply_dry_run",
    ]:
        assert Path(payload["artifacts"][artifact]).exists()
    assert (output_dir / "manifest.json").exists()


def test_internal_beta_audit_can_include_advanced_format_report(tmp_path: Path, tmp_library: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "internal_beta_audit.py"
    output_dir = tmp_path / "beta_reports"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_library),
            "--output-dir",
            str(output_dir),
            "--include-format",
            "--limit",
            "10",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)

    assert payload["include_format"] is True
    assert "format" in payload["summary"]
    assert Path(payload["artifacts"]["format_report"]).exists()


def test_internal_beta_audit_can_include_similarity_reports(tmp_path: Path, tmp_library: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "internal_beta_audit.py"
    output_dir = tmp_path / "beta_reports"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_library),
            "--output-dir",
            str(output_dir),
            "--include-similarity",
            "--similarity-threshold",
            "0.9",
            "--limit",
            "10",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)

    assert payload["include_similarity"] is True
    assert payload["similarity_validation"] is True
    assert payload["similarity_validation_mode"] == "manual_beta_audit"
    assert (
        payload["similarity_automation_recommendation"] == "defer_overnight_automation_until_manual_validation_passes"
    )
    assert payload["similarity_threshold"] == 0.9
    assert "similarity" in payload["summary"]
    assert payload["summary"]["similarity"]["crawl"]["total_files"] == 4
    for artifact in [
        "similarity_cache",
        "similarity_crawl_report",
        "similarity_segments_report",
        "similarity_audit_file_report",
        "similarity_audit_segment_report",
    ]:
        assert Path(payload["artifacts"][artifact]).exists()


def test_internal_beta_audit_similarity_validation_alias(tmp_path: Path, tmp_library: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "internal_beta_audit.py"
    output_dir = tmp_path / "beta_reports"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_library),
            "--output-dir",
            str(output_dir),
            "--similarity-validation",
            "--limit",
            "10",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)

    assert payload["include_similarity"] is True
    assert payload["similarity_validation"] is True
    assert payload["similarity_validation_mode"] == "manual_beta_audit"
    assert "similarity" in payload["summary"]
    assert Path(payload["artifacts"]["similarity_audit_file_report"]).exists()
