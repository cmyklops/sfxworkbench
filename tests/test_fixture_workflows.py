"""Golden fixture workflow checks."""

import json
from pathlib import Path

from wavwarden.audit_cmd import run_audit
from wavwarden.clean import find_junk
from wavwarden.dedupe import find_duplicates
from wavwarden.rename import build_rename_plan
from wavwarden.scan import scan_library


def test_tmp_library_matches_basic_manifest(tmp_library: Path, tmp_db: Path) -> None:
    manifest = json.loads((Path(__file__).parent / "fixtures" / "library_basic_manifest.json").read_text())

    junk_files, junk_dirs = find_junk(tmp_library, quiet=True)
    assert len(junk_files) == manifest["expected_junk_files"]
    assert len(junk_dirs) == manifest["expected_junk_dirs"]

    scan = scan_library(tmp_library, tmp_db, skip_hash=False, quiet=True)
    assert scan.total == manifest["expected_audio_files"]
    assert scan.scanned == manifest["expected_audio_files"]

    audit = run_audit(tmp_db, quiet=True)
    assert audit.total_files == manifest["expected_audio_files"]
    assert audit.scan_errors >= manifest["expected_scan_errors_at_least"]
    for issue_type in manifest["expected_filename_issue_types"]:
        assert issue_type in audit.fn_issues_by_type

    duplicates = find_duplicates(tmp_db)
    assert duplicates

    rename_plan = build_rename_plan(tmp_library)
    assert rename_plan.entries
