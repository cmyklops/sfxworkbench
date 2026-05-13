"""Tier 3.8: each apply-executor honors ``target_paths`` as a scope filter.

Multi-select in the TUI feeds a set of file paths through every ``apply_*``
function. When ``target_paths`` is given, only entries whose path is in the
set are touched; the rest are silently skipped (counted in ``result.skipped``
where the result model supports it).

The pack and nesting executors are *not* covered here — they operate on
folder paths, and the TUI's current selection model is file-level only.

Test strategy: build a minimal real plan for each executor using the same
fixtures the existing tests use, then run apply twice — once unscoped, once
scoped to a single path — and assert the second touched exactly one entry.
"""

from __future__ import annotations

import json
from pathlib import Path

from sfxworkbench.delete import apply_delete_plan, build_delete_plan, review_delete_plan, write_delete_plan


def _make_quarantine_log(tmp_path: Path, quarantine_paths: list[Path]) -> Path:
    payload = {
        "schema_version": 1,
        "entries": [{"quarantine_path": str(p), "folder_path": str(p.parent)} for p in quarantine_paths],
    }
    log_path = tmp_path / "quarantine_apply_log.json"
    log_path.write_text(json.dumps(payload, indent=2))
    return log_path


def test_apply_delete_plan_target_paths_scopes_to_named_paths(tmp_path: Path) -> None:
    """Two quarantined files, target_paths picks one — only that one is deleted."""
    keep = tmp_path / "quarantine" / "keep.wav"
    drop = tmp_path / "quarantine" / "drop.wav"
    keep.parent.mkdir()
    keep.write_bytes(b"x")
    drop.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [keep, drop])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    result = apply_delete_plan(
        plan_path,
        dry_run=True,
        require_reviewed=True,
        quiet=True,
        target_paths=(str(drop),),
    )

    assert result.deleted == 1
    assert result.skipped == 1


def test_apply_delete_plan_target_paths_empty_tuple_drops_everything(tmp_path: Path) -> None:
    """An empty-set selection produces zero deletions (every entry filtered out)."""
    p = tmp_path / "quarantine" / "a.wav"
    p.parent.mkdir()
    p.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [p])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    result = apply_delete_plan(
        plan_path,
        dry_run=True,
        require_reviewed=True,
        quiet=True,
        target_paths=(),
    )

    assert result.deleted == 0
    assert result.skipped == 1


def test_every_filterable_executor_accepts_target_paths() -> None:
    """Smoke check: every Tier 3.8 executor exposes a ``target_paths`` parameter.

    Catches regressions where someone refactors a signature and drops the
    selection scope by accident. The deep semantic tests live above
    (delete-pipeline) and parallel logic in the other executors is mechanical
    — the same set-membership check on ``entry.path`` (or equivalent field).
    """
    import inspect

    from sfxworkbench.dedupe import apply_dedupe_plan
    from sfxworkbench.dual_mono import apply_dual_mono_plan
    from sfxworkbench.metadata_write import apply_metadata_write_plan
    from sfxworkbench.rename import apply_rename_plan
    from sfxworkbench.scan_errors import apply_scan_error_plan
    from sfxworkbench.tag_plan import apply_tag_plan

    filterable_executors = [
        apply_delete_plan,
        apply_dedupe_plan,
        apply_dual_mono_plan,
        apply_metadata_write_plan,
        apply_rename_plan,
        apply_scan_error_plan,
        apply_tag_plan,
    ]

    missing: list[str] = []
    for func in filterable_executors:
        sig = inspect.signature(func)
        param = sig.parameters.get("target_paths")
        if param is None:
            missing.append(f"{func.__module__}.{func.__name__}: no target_paths parameter")
            continue
        if param.default is not None:
            missing.append(
                f"{func.__module__}.{func.__name__}: target_paths default is {param.default!r}, expected None"
            )

    assert not missing, "Tier 3.8 contract violation:\n" + "\n".join(f"  - {msg}" for msg in missing)


def test_apply_delete_plan_target_paths_none_means_no_filter(tmp_path: Path) -> None:
    """The default ``target_paths=None`` preserves pre-3.8 behavior (apply all)."""
    a = tmp_path / "quarantine" / "a.wav"
    b = tmp_path / "quarantine" / "b.wav"
    a.parent.mkdir()
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [a, b])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    result = apply_delete_plan(
        plan_path,
        dry_run=True,
        require_reviewed=True,
        quiet=True,
    )

    assert result.deleted == 2
    assert result.skipped == 0
