"""Tests for standalone audit.py."""

import importlib.util
import json
import subprocess
import sys
import unicodedata
from pathlib import Path


def _load_audit_module():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("standalone_audit", root / "audit.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_standalone_audit_reports_filename_issues_and_duplicates(tmp_path: Path) -> None:
    audit_mod = _load_audit_module()
    root = tmp_path / "lib"
    root.mkdir()
    nfd_name = unicodedata.normalize("NFD", "café.wav")
    (root / nfd_name).write_bytes(b"same")
    (root / "copy.wav").write_bytes(b"same")

    report = audit_mod.audit(root)

    assert report["schema_version"] == 1
    assert report["summary"]["total_files"] == 2
    assert report["filename_issues"]["unicode_normalization"] >= 1
    assert report["summary"]["duplicate_groups"] == 1


def test_standalone_audit_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    out = tmp_path / "reports"
    root.mkdir()
    (root / "sound.wav").write_bytes(b"not a real wav")

    script = Path(__file__).resolve().parents[1] / "audit.py"
    result = subprocess.run(
        [sys.executable, str(script), str(root), "--output-dir", str(out), "--json"],
        check=True,
        capture_output=True,
        text=True,
    )

    parsed = json.loads(result.stdout)
    assert parsed["summary"]["total_files"] == 1
    assert list(out.glob("audit_*.json"))
    assert list(out.glob("audit_*.md"))
