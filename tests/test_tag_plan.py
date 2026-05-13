"""Tests for sfxworkbench.tag_plan focused on PR #2 safety fixes.

Broader coverage of ``apply_tag_plan`` lives in PR #9.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfxworkbench.db import connection
from sfxworkbench.models import (
    TagPlan,
    TagPlanEntry,
    TagPlanSummary,
    TagSuggestion,
    TagSuggestionEntry,
    TagSuggestionReport,
    TagSuggestionSummary,
)
from sfxworkbench.tag_plan import (
    _validate_plan_entry,
    apply_tag_plan,
    build_tag_plan,
    review_tag_plan,
    write_tag_plan,
)


def _seed_files_row(db_path: Path, *, file_id: int, path: Path, mtime: float, size: int, md5: str) -> None:
    with connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO files (id, path, filename, stem, size_bytes, mtime, md5, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '2026-05-12T00:00:00Z')
            """,
            (file_id, str(path), path.name, path.stem, size, mtime, md5),
        )
        conn.commit()


def test_validate_plan_entry_tolerates_mtime_json_round_trip(tmp_path: Path, tmp_db: Path) -> None:
    """mtime stored as a float survives JSON round-trip and reapply without 'mtime changed'.

    Pre-fix this asserted exact equality (``stat.st_mtime != entry.mtime``) which
    failed intermittently because some filesystems carry sub-microsecond mtime
    precision that JSON's IEEE-754 round-trip can't preserve.
    """
    audio = tmp_path / "AMB_RAIN_01.wav"
    audio.write_bytes(b"fake wave data")
    stat = audio.stat()
    # Round-trip the float through JSON the same way a plan file would.
    serialized_mtime = json.loads(json.dumps(stat.st_mtime))

    _seed_files_row(
        tmp_db,
        file_id=1,
        path=audio,
        mtime=serialized_mtime,
        size=stat.st_size,
        md5="0" * 32,
    )

    entry = TagPlanEntry(
        entry_id=1,
        file_id=1,
        path=str(audio),
        filename=audio.name,
        size_bytes=stat.st_size,
        mtime=serialized_mtime,
        md5=None,  # skip MD5 path so we don't have to compute it
        field="description",
        action="add",
        existing_values=[],
        proposed_value="rain ambience",
        source="filename",
        method="heuristic",
        confidence=0.9,
        evidence=["test"],
    )

    with connection(tmp_db) as conn:
        result = _validate_plan_entry(conn, entry)
    assert result is None, f"expected validation to pass, got {result!r}"


def test_validate_plan_entry_still_detects_real_mtime_change(tmp_path: Path, tmp_db: Path) -> None:
    """The tolerance is narrow enough that a real edit is still detected."""
    audio = tmp_path / "real_change.wav"
    audio.write_bytes(b"original")
    stat = audio.stat()

    _seed_files_row(
        tmp_db,
        file_id=2,
        path=audio,
        mtime=stat.st_mtime,
        size=stat.st_size,
        md5="0" * 32,
    )

    # Stored mtime diverges from the filesystem by more than the tolerance.
    drifted_mtime = stat.st_mtime + 5.0

    entry = TagPlanEntry(
        entry_id=2,
        file_id=2,
        path=str(audio),
        filename=audio.name,
        size_bytes=stat.st_size,
        mtime=drifted_mtime,
        md5=None,
        field="description",
        action="add",
        existing_values=[],
        proposed_value="x",
        source="filename",
        method="heuristic",
        confidence=0.9,
        evidence=["test"],
    )

    with connection(tmp_db) as conn:
        result = _validate_plan_entry(conn, entry)
    assert result is not None
    assert "mtime" in result


# ---------------------------------------------------------------------------
# Idempotency / resumability of apply_tag_plan (PR #16 follow-up to PR #9)
# ---------------------------------------------------------------------------


def _make_plan_from_suggestion(
    tmp_path: Path,
    *,
    file_id: int,
    path: Path,
    field: str,
    value: str,
) -> Path:
    """Build a tag plan for a single file/field/value triple and write it to disk."""
    stat = path.stat()
    report = TagSuggestionReport(
        generated_at="2026-05-12T00:00:00+00:00",
        tool_version="test",
        root=str(path.parent),
        db_path=str(path.parent / "ignored.db"),
        min_confidence=0.0,
        sources=[],
        fields=[],
        limit=0,
        summary=TagSuggestionSummary(
            files_considered=1,
            files_with_suggestions=1,
            suggestions_total=1,
            by_source={"filename": 1},
            by_field={field: 1},
            by_confidence_bucket={"hi": 1},
        ),
        entries=[
            TagSuggestionEntry(
                file_id=file_id,
                path=str(path),
                filename=path.name,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                md5=None,
                suggestions=[
                    TagSuggestion(
                        field=field,
                        value=value,
                        source="filename",
                        method="heuristic",
                        confidence=0.95,
                        evidence=["fixture"],
                    )
                ],
            )
        ],
    )
    # build_tag_plan accepts a report path (we'll fake one by writing the report to JSON).
    # Easier: construct the TagPlan directly and write it.
    plan = TagPlan(
        generated_at="2026-05-12T00:00:00+00:00",
        tool_version="test",
        root=str(path.parent),
        db_path=str(path.parent / "ignored.db"),
        source_report=None,
        target="db",
        min_confidence=0.0,
        sources=[],
        fields=[],
        limit=0,
        summary=TagPlanSummary(files_considered=1, candidate_entries=1, add_entries=1, skip_existing_entries=0),
        entries=[
            TagPlanEntry(
                entry_id=1,
                file_id=file_id,
                path=str(path),
                filename=path.name,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                md5=None,
                field=field,
                action="add",
                existing_values=[],
                proposed_value=value,
                source="filename",
                method="heuristic",
                confidence=0.95,
                evidence=["fixture"],
            )
        ],
    )
    plan_path = tmp_path / "tag_plan.json"
    write_tag_plan(plan, plan_path, quiet=True)
    review_tag_plan(plan_path, approve_all=True, quiet=True)
    # Silence unused-imports for the report scaffolding above (kept so future
    # tests can build from a report path instead).
    _ = (report, build_tag_plan)
    return plan_path


def test_apply_tag_plan_is_idempotent_at_the_db(tmp_path: Path, tmp_db: Path) -> None:
    """Running ``apply_tag_plan`` twice produces the same DB state.

    ``apply_tag_plan`` uses ``INSERT ... ON CONFLICT(file_id, field, value) DO
    UPDATE SET ...``, so re-running is safe by design — the row's
    ``updated_at`` advances but the (file_id, field, value) row count stays
    at one. This is the "resumability" property the safety story promises:
    if a previous run was interrupted, a second run can be re-issued without
    causing duplicate writes.
    """
    audio = tmp_path / "AMB_RAIN_01.wav"
    audio.write_bytes(b"x")
    _seed_files_row(
        tmp_db,
        file_id=100,
        path=audio,
        mtime=audio.stat().st_mtime,
        size=audio.stat().st_size,
        md5="0" * 32,
    )

    plan_path = _make_plan_from_suggestion(tmp_path, file_id=100, path=audio, field="description", value="Rain Heavy")

    first = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)
    second = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)

    # First run inserts; second run detects the value is already accepted and skips.
    # Both outcomes are valid "applied successfully" — neither produces errors and
    # the DB state is identical.
    assert first.applied == 1
    assert second.applied == 0
    assert second.skipped == 1
    assert first.errors == [] == second.errors
    # The DB should have exactly one accepted_tags row for this (file_id, field, value).
    with connection(tmp_db) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM accepted_tags WHERE file_id = ? AND field = ? AND value = ?",
            (100, "description", "Rain Heavy"),
        ).fetchone()
    assert rows[0] == 1


def test_apply_tag_plan_partial_interruption_is_recoverable(tmp_path: Path, tmp_db: Path, monkeypatch) -> None:
    """Simulate a mid-run interruption and verify resumability.

    The apply loop wraps INSERTs in a single SQLite transaction that's
    committed at the very end. If anything raises before the commit, all
    pending INSERTs roll back on connection close. Re-running the same plan
    therefore produces the correct final state — no orphaned rows, no
    duplicates. This is the same invariant a real SIGTERM-mid-run would
    test, but reliably timed.
    """
    from sfxworkbench import tag_plan as tag_plan_module

    audio = tmp_path / "AMB_RAIN_03.wav"
    audio.write_bytes(b"x")
    _seed_files_row(
        tmp_db,
        file_id=200,
        path=audio,
        mtime=audio.stat().st_mtime,
        size=audio.stat().st_size,
        md5="0" * 32,
    )
    plan_path = _make_plan_from_suggestion(tmp_path, file_id=200, path=audio, field="description", value="Steady Rain")

    # Stub the per-entry validator to raise on its first invocation, simulating
    # a hard interruption (e.g. SIGTERM, hardware failure) before any INSERT
    # could be committed.
    real_validate = tag_plan_module._validate_plan_entry
    call_count = {"n": 0}

    def boom(*args, **kwargs):
        call_count["n"] += 1
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(tag_plan_module, "_validate_plan_entry", boom)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)

    # The interruption fired; nothing committed.
    with connection(tmp_db) as conn:
        before = conn.execute("SELECT COUNT(*) FROM accepted_tags WHERE file_id = ?", (200,)).fetchone()
    assert before[0] == 0

    # Restore the real validator and re-run; the DB should converge to the
    # state the user originally intended.
    monkeypatch.setattr(tag_plan_module, "_validate_plan_entry", real_validate)
    result = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=False, require_reviewed=True, quiet=True)
    assert result.applied == 1

    with connection(tmp_db) as conn:
        after = conn.execute(
            "SELECT COUNT(*) FROM accepted_tags WHERE file_id = ? AND field = ? AND value = ?",
            (200, "description", "Steady Rain"),
        ).fetchone()
    assert after[0] == 1


def test_apply_tag_plan_dry_run_idempotent(tmp_path: Path, tmp_db: Path) -> None:
    """Dry-run apply is also idempotent — counts match across consecutive runs."""
    audio = tmp_path / "AMB_RAIN_02.wav"
    audio.write_bytes(b"x")
    _seed_files_row(
        tmp_db,
        file_id=101,
        path=audio,
        mtime=audio.stat().st_mtime,
        size=audio.stat().st_size,
        md5="0" * 32,
    )
    plan_path = _make_plan_from_suggestion(tmp_path, file_id=101, path=audio, field="description", value="Light Rain")

    first = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=True, require_reviewed=True, quiet=True)
    second = apply_tag_plan(plan_path, db_path=tmp_db, dry_run=True, require_reviewed=True, quiet=True)

    assert first.applied == second.applied
    assert first.skipped == second.skipped
    assert first.errors == second.errors
