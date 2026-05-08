"""Tests for synthetic large-library benchmark script."""

import json
import subprocess
import sys
from pathlib import Path


def test_bench_large_library_small_run(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "bench_large_library.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(tmp_path / "library"),
            "--db",
            str(tmp_path / "bench.db"),
            "--files",
            "12",
            "--dirs",
            "3",
            "--no-hash",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["command"] == "bench_large_library"
    assert payload["first_scan"]["result"]["total"] == 12
    assert payload["incremental_scan"]["result"]["skipped"] == 12
