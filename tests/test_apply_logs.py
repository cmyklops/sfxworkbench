"""Tests for shared apply-log path defaults."""

from __future__ import annotations

from pathlib import Path

from sfxworkbench.apply_logs import APPLY_LOG_DIR_NAME, default_apply_log_path, default_apply_log_path_for_plan
from sfxworkbench.delete import _default_delete_log_path
from sfxworkbench.dual_mono import _default_log_path as default_dual_mono_log_path
from sfxworkbench.metadata_write import _default_apply_log_path as default_metadata_write_log_path
from sfxworkbench.organize import _default_nesting_log_path
from sfxworkbench.packs import _default_pack_log_path
from sfxworkbench.rename import _default_log_path as default_rename_log_path
from sfxworkbench.tag_plan import _default_log_path as default_tag_log_path


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

    defaults = [
        (default_metadata_write_log_path(plan), "metadata_write_apply_log"),
        (default_tag_log_path(plan), "tag_apply_log"),
        (_default_pack_log_path(plan), "pack_quarantine_log"),
        (_default_nesting_log_path(plan), "nesting_log"),
        (_default_delete_log_path(plan), "delete_apply_log"),
        (default_dual_mono_log_path(plan), "dual_mono_apply_log"),
    ]

    for path, prefix in defaults:
        _assert_log_path(path, parent=expected_parent, prefix=prefix)


def test_direct_rename_default_apply_log_uses_grouped_relative_folder() -> None:
    _assert_log_path(default_rename_log_path(), parent=Path(APPLY_LOG_DIR_NAME), prefix="rename_log")
