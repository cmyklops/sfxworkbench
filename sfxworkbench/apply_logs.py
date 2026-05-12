"""Shared paths for apply and undo logs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

APPLY_LOG_DIR_NAME = "apply_logs"


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def apply_log_dir(base_dir: Path | None = None) -> Path:
    """Return the standard folder for apply logs."""
    if base_dir is None:
        return Path(APPLY_LOG_DIR_NAME)
    return Path(base_dir) / APPLY_LOG_DIR_NAME


def default_apply_log_path(prefix: str, *, base_dir: Path | None = None) -> Path:
    """Build a timestamped apply log path under the standard log folder."""
    return apply_log_dir(base_dir) / f"{prefix}_{_now_stamp()}.json"


def default_apply_log_path_for_plan(plan_path: Path, prefix: str) -> Path:
    """Build a timestamped apply log path beside a plan/report file."""
    return default_apply_log_path(prefix, base_dir=Path(plan_path).expanduser().parent)
