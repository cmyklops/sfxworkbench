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
    for artifact in [
        "scan_result",
        "audit_result",
        "metadata_report",
        "related_groups_report",
        "format_report",
        "pack_overlap_report",
        "pack_consolidation_plan",
        "pack_apply_dry_run",
    ]:
        assert Path(payload["artifacts"][artifact]).exists()
    assert (output_dir / "manifest.json").exists()
