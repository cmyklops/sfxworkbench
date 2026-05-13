"""Tests for sfxworkbench.utils."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sfxworkbench.utils import atomic_write_json, atomic_write_text, fmt_bytes, json_dumps, progress_interval


def test_progress_interval_keeps_full_detail_for_small_runs() -> None:
    """Runs under 100 entries report every iteration — per-item detail
    matters more than callback throttling at that scale.
    """
    assert progress_interval(0) == 1
    assert progress_interval(1) == 1
    assert progress_interval(99) == 1


def test_progress_interval_scales_to_keep_callback_count_bounded() -> None:
    """The interval grows linearly with total so callbacks fire ~100 times
    regardless of run size. A 1M-entry apply would otherwise emit 10k status
    updates at the old fixed-100 interval.
    """
    assert progress_interval(1000) == 10
    assert progress_interval(10_000) == 100
    assert progress_interval(100_000) == 1_000
    assert progress_interval(1_000_000) == 10_000
    # Sanity: at the user's existing 139k plan the bar still fires often
    # enough to feel responsive (one update every ~1390 entries).
    assert 1000 <= progress_interval(139_448) <= 2000


def test_fmt_bytes_b() -> None:
    assert fmt_bytes(0) == "0.0 B"
    assert fmt_bytes(512) == "512.0 B"


def test_fmt_bytes_kb() -> None:
    assert fmt_bytes(1024) == "1.0 KB"
    assert fmt_bytes(2048) == "2.0 KB"


def test_fmt_bytes_mb() -> None:
    assert fmt_bytes(1024 * 1024) == "1.0 MB"


def test_fmt_bytes_gb() -> None:
    assert fmt_bytes(1024**3) == "1.0 GB"


def test_fmt_bytes_tb() -> None:
    assert fmt_bytes(1024**4) == "1.0 TB"


# -- atomic_write_text / atomic_write_json ----------------------------------


def test_atomic_write_text_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_text_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("original")
    atomic_write_text(target, "replaced")
    assert target.read_text() == "replaced"


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "nested" / "out.txt"
    atomic_write_text(target, "deep")
    assert target.read_text() == "deep"


def test_atomic_write_text_preserves_existing_permissions(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("v1")
    target.chmod(0o640)

    atomic_write_text(target, "v2")
    assert target.stat().st_mode & 0o777 == 0o640


def test_atomic_write_text_no_partial_file_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If os.replace fails mid-write, the destination is left intact and no tmp leaks."""
    target = tmp_path / "out.txt"
    target.write_text("original")

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="simulated crash"):
        atomic_write_text(target, "should not land")

    # Destination is unchanged.
    assert target.read_text() == "original"
    # No leftover temp files in the parent directory.
    tmp_files = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert tmp_files == [], f"Unexpected leftover files: {tmp_files}"


def test_atomic_write_text_no_partial_file_when_target_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If os.replace fails and target did not exist, no partial file appears."""
    target = tmp_path / "out.txt"
    assert not target.exists()

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="simulated crash"):
        atomic_write_text(target, "should not land")

    assert not target.exists()
    leftover = list(tmp_path.iterdir())
    assert leftover == [], f"Unexpected leftover files: {leftover}"


def test_atomic_write_json_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    payload = {"b": [2, 3], "a": 1, "c": "x"}
    atomic_write_json(target, payload)
    # Same bytes that json_dumps would produce (sorted keys, indent=2).
    assert target.read_text() == json_dumps(payload)
    # And it parses back to the same data.
    assert json.loads(target.read_text()) == payload


def test_atomic_write_json_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"version": 1})
    atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text()) == {"version": 2}
