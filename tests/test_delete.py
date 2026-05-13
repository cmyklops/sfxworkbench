"""Workflow + idempotency tests for sfxworkbench.delete (PR #9).

Covers the dry-run path of the reviewed permanent-delete pipeline:
``build_delete_plan`` → ``review_delete_plan`` → ``apply_delete_plan`` (dry-run).
Real deletion (``--apply --i-understand-permanent-delete``) is exercised
indirectly through the existing CLI integration tests; this file focuses on
the helper-level contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from sfxworkbench.delete import (
    apply_delete_plan,
    build_delete_plan,
    load_delete_plan,
    review_delete_plan,
    write_delete_plan,
)


def _make_quarantine_log(tmp_path: Path, quarantine_paths: list[Path]) -> Path:
    """Write a minimal quarantine-log JSON in the format ``delete`` expects."""
    payload = {
        "schema_version": 1,
        "entries": [{"quarantine_path": str(p), "folder_path": str(p.parent)} for p in quarantine_paths],
    }
    log_path = tmp_path / "quarantine_apply_log.json"
    log_path.write_text(json.dumps(payload, indent=2))
    return log_path


# -- build_delete_plan ------------------------------------------------------


def test_build_delete_plan_drops_missing_quarantine_paths(tmp_path: Path) -> None:
    real = tmp_path / "quarantine" / "duplicate.wav"
    real.parent.mkdir()
    real.write_bytes(b"x")
    missing = tmp_path / "quarantine" / "gone.wav"
    log = _make_quarantine_log(tmp_path, [real, missing])

    plan = build_delete_plan(log)

    assert plan.summary.candidate_entries == 1
    assert plan.entries[0].path == str(real)
    assert any("does not exist" in err["error"] for err in plan.errors)


def test_build_delete_plan_marks_safe_folder_entries_as_errors(tmp_path: Path) -> None:
    protected = tmp_path / "protected"
    protected.mkdir()
    file_inside = protected / "important.wav"
    file_inside.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [file_inside])

    plan = build_delete_plan(log, safe_folders=[protected])

    assert plan.summary.candidate_entries == 0
    assert plan.errors
    assert plan.errors[0]["error"] == "protected by safe folder"


# -- review_delete_plan -----------------------------------------------------


def test_review_delete_plan_approve_all_marks_every_entry(tmp_path: Path) -> None:
    files = []
    for name in ("a.wav", "b.wav", "c.wav"):
        f = tmp_path / "quarantine" / name
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"data")
        files.append(f)
    log = _make_quarantine_log(tmp_path, files)
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)

    review_delete_plan(plan_path, approve_all=True, quiet=True)

    loaded = load_delete_plan(plan_path)
    assert all(e.review_status == "approved" for e in loaded.entries)


def test_review_delete_plan_can_reject_specific_entries(tmp_path: Path) -> None:
    a = tmp_path / "quarantine" / "a.wav"
    b = tmp_path / "quarantine" / "b.wav"
    a.parent.mkdir()
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [a, b])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)

    review_delete_plan(plan_path, entries=[1], reject_entries=[2], quiet=True)

    loaded = load_delete_plan(plan_path)
    by_id = {e.entry_id: e.review_status for e in loaded.entries}
    assert by_id == {1: "approved", 2: "rejected"}


# -- apply_delete_plan ------------------------------------------------------


def test_apply_delete_plan_dry_run_does_not_touch_files(tmp_path: Path) -> None:
    target = tmp_path / "quarantine" / "doomed.wav"
    target.parent.mkdir()
    target.write_bytes(b"goodbye")
    log = _make_quarantine_log(tmp_path, [target])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    result = apply_delete_plan(plan_path, dry_run=True, require_reviewed=True, quiet=True)

    assert result.dry_run is True
    assert result.deleted == 1
    assert result.bytes_deleted == len(b"goodbye")
    # File still on disk.
    assert target.exists()


def test_apply_delete_plan_refuses_real_run_without_confirmation(tmp_path: Path) -> None:
    target = tmp_path / "quarantine" / "doomed.wav"
    target.parent.mkdir()
    target.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [target])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    result = apply_delete_plan(
        plan_path,
        dry_run=False,
        require_reviewed=True,
        understand_permanent_delete=False,
        quiet=True,
    )

    assert result.deleted == 0
    assert any("missing explicit permanent-delete confirmation" in err["error"] for err in result.errors)
    # File still on disk — the confirmation gate held.
    assert target.exists()


# -- Idempotency ------------------------------------------------------------


def test_apply_delete_plan_dry_run_is_idempotent(tmp_path: Path) -> None:
    """Two consecutive dry-runs produce the same result. No state should accumulate."""
    target = tmp_path / "quarantine" / "doomed.wav"
    target.parent.mkdir()
    target.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [target])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    first = apply_delete_plan(plan_path, dry_run=True, require_reviewed=True, quiet=True)
    second = apply_delete_plan(plan_path, dry_run=True, require_reviewed=True, quiet=True)

    assert first.deleted == second.deleted
    assert first.skipped == second.skipped
    assert first.bytes_deleted == second.bytes_deleted
    assert first.errors == second.errors
    assert target.exists()


def test_apply_delete_plan_skips_rejected_entries(tmp_path: Path) -> None:
    a = tmp_path / "quarantine" / "a.wav"
    b = tmp_path / "quarantine" / "b.wav"
    a.parent.mkdir()
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    log = _make_quarantine_log(tmp_path, [a, b])
    plan = build_delete_plan(log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, entries=[1], reject_entries=[2], quiet=True)

    result = apply_delete_plan(plan_path, dry_run=True, require_reviewed=True, quiet=True)

    assert result.deleted == 1
    assert result.skipped == 1
