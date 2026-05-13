"""Tests for shared apply-log path defaults."""

from __future__ import annotations

from pathlib import Path

from sfxworkbench.apply_logs import APPLY_LOG_DIR_NAME, default_apply_log_path, default_apply_log_path_for_plan


def _assert_log_path(path: Path, *, parent: Path, prefix: str) -> None:
    assert path.parent == parent
    assert path.name.startswith(prefix + "_")
    assert path.suffix == ".json"


def test_default_apply_log_path_uses_dedicated_folder(tmp_path: Path) -> None:
    path = default_apply_log_path("rename_log", base_dir=tmp_path)

    _assert_log_path(path, parent=tmp_path / APPLY_LOG_DIR_NAME, prefix="rename_log")


def test_default_apply_log_path_for_plan_lives_beside_plan(tmp_path: Path) -> None:
    plan = tmp_path / "reports" / "tag_plan.json"

    path = default_apply_log_path_for_plan(plan, "tag_apply_log")

    _assert_log_path(path, parent=tmp_path / "reports" / APPLY_LOG_DIR_NAME, prefix="tag_apply_log")


def test_command_default_apply_logs_are_grouped_by_plan_parent(tmp_path: Path) -> None:
    plan = tmp_path / "reports" / "plan.json"
    expected_parent = plan.parent / APPLY_LOG_DIR_NAME

    prefixes = [
        "metadata_write_apply_log",
        "tag_apply_log",
        "pack_quarantine_log",
        "nesting_log",
        "delete_apply_log",
        "dual_mono_apply_log",
    ]

    for prefix in prefixes:
        _assert_log_path(default_apply_log_path_for_plan(plan, prefix), parent=expected_parent, prefix=prefix)


def test_direct_rename_default_apply_log_uses_grouped_relative_folder() -> None:
    _assert_log_path(default_apply_log_path("rename_log"), parent=Path(APPLY_LOG_DIR_NAME), prefix="rename_log")
