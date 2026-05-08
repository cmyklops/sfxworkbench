"""Tests for wavwarden.dedupe."""

import json
from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.dedupe import find_duplicates, write_dedupe_plan, apply_dedupe_plan


def _seed_files(tmp_db: Path, files: list[dict]) -> None:
    """Insert minimal file rows for testing."""
    conn = get_connection(tmp_db)
    for f in files:
        conn.execute(
            """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f["path"], Path(f["path"]).name, Path(f["path"]).stem,
                Path(f["path"]).suffix, f.get("size", 1024), 0.0,
                f.get("md5"), "2026-01-01T00:00:00",
            ),
        )
    conn.commit()
    conn.close()


def test_find_duplicates_groups_by_md5(tmp_db: Path) -> None:
    _seed_files(tmp_db, [
        {"path": "/a/one.wav", "md5": "AAA", "size": 1000},
        {"path": "/b/one.wav", "md5": "AAA", "size": 1000},
        {"path": "/c/two.wav", "md5": "BBB", "size": 500},
    ])
    groups = find_duplicates(tmp_db)
    assert len(groups) == 1
    assert groups[0].hash == "AAA"
    assert len(groups[0].files) == 2


def test_find_duplicates_ignores_singletons(tmp_db: Path) -> None:
    _seed_files(tmp_db, [
        {"path": "/a/unique.wav", "md5": "XXX"},
    ])
    groups = find_duplicates(tmp_db)
    assert groups == []


def test_find_duplicates_skips_null_md5(tmp_db: Path) -> None:
    _seed_files(tmp_db, [
        {"path": "/a/no_hash.wav", "md5": None},
        {"path": "/b/no_hash.wav", "md5": None},
    ])
    groups = find_duplicates(tmp_db)
    assert groups == []


def test_find_duplicates_sorts_by_size(tmp_db: Path) -> None:
    """Largest groups first so users see biggest wins at the top."""
    _seed_files(tmp_db, [
        {"path": "/a/small1.wav", "md5": "S", "size": 100},
        {"path": "/a/small2.wav", "md5": "S", "size": 100},
        {"path": "/a/big1.wav", "md5": "B", "size": 99999},
        {"path": "/a/big2.wav", "md5": "B", "size": 99999},
    ])
    groups = find_duplicates(tmp_db)
    assert len(groups) == 2
    assert groups[0].hash == "B"
    assert groups[1].hash == "S"


def test_find_duplicates_deterministic_ordering(tmp_db: Path) -> None:
    """File ordering within a group should be deterministic across runs."""
    _seed_files(tmp_db, [
        {"path": "/z/last.wav", "md5": "M"},
        {"path": "/a/first.wav", "md5": "M"},
        {"path": "/m/middle.wav", "md5": "M"},
    ])
    groups1 = find_duplicates(tmp_db)
    groups2 = find_duplicates(tmp_db)
    assert groups1[0].files == groups2[0].files
    assert groups1[0].files == sorted(groups1[0].files)


def test_find_duplicates_handles_pipe_in_path(tmp_db: Path) -> None:
    """Paths containing the legacy '|||' separator must not corrupt the group."""
    _seed_files(tmp_db, [
        {"path": "/odd/with|||pipe.wav", "md5": "P"},
        {"path": "/odd/normal.wav", "md5": "P"},
    ])
    groups = find_duplicates(tmp_db)
    assert len(groups) == 1
    assert "/odd/with|||pipe.wav" in groups[0].files
    assert "/odd/normal.wav" in groups[0].files


def test_write_dedupe_plan(tmp_db: Path, tmp_path: Path) -> None:
    _seed_files(tmp_db, [
        {"path": "/a/one.wav", "md5": "AAA", "size": 100},
        {"path": "/b/one.wav", "md5": "AAA", "size": 100},
        {"path": "/c/one.wav", "md5": "AAA", "size": 100},
    ])
    groups = find_duplicates(tmp_db)
    plan_path = tmp_path / "plan.json"
    write_dedupe_plan(groups, plan_path)

    plan = json.loads(plan_path.read_text())
    assert "groups" in plan
    assert len(plan["groups"]) == 1
    actions = [e["action"] for e in plan["groups"][0]]
    assert actions.count("keep") == 1
    assert actions.count("remove") == 2


def test_apply_dedupe_dry_run_makes_no_changes(tmp_path: Path) -> None:
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(b"audio")
    b.write_bytes(b"audio")

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "groups": [[
            {"path": str(a), "action": "keep", "size_bytes": 5},
            {"path": str(b), "action": "remove", "size_bytes": 5},
        ]]
    }))

    result = apply_dedupe_plan(plan_path, dry_run=True)
    assert result.dry_run is True
    assert result.removed == 1
    assert a.exists() and b.exists(), "Dry run should not delete anything"


def test_apply_dedupe_removes_files_and_updates_db(tmp_db: Path, tmp_path: Path) -> None:
    """After --apply, removed files should be unlinked AND deleted from the index."""
    a = tmp_path / "keep.wav"
    b = tmp_path / "drop.wav"
    a.write_bytes(b"audio")
    b.write_bytes(b"audio")

    _seed_files(tmp_db, [
        {"path": str(a), "md5": "AAA"},
        {"path": str(b), "md5": "AAA"},
    ])

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "groups": [[
            {"path": str(a), "action": "keep", "size_bytes": 5},
            {"path": str(b), "action": "remove", "size_bytes": 5},
        ]]
    }))

    result = apply_dedupe_plan(plan_path, db_path=tmp_db, dry_run=False)
    assert result.dry_run is False
    assert result.removed == 1
    assert a.exists()
    assert not b.exists(), "Removed file should be unlinked from disk"

    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    paths = [row["path"] for row in rows]
    conn.close()
    assert str(a) in paths
    assert str(b) not in paths, "Removed file should also be deleted from the index"


def test_apply_dedupe_records_errors(tmp_path: Path) -> None:
    """Missing files should produce errors but not crash."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "groups": [[
            {"path": str(tmp_path / "keep.wav"), "action": "keep", "size_bytes": 5},
            {"path": str(tmp_path / "missing.wav"), "action": "remove", "size_bytes": 5},
        ]]
    }))
    result = apply_dedupe_plan(plan_path, dry_run=False)
    assert len(result.errors) == 1
