"""Tests for sfxworkbench.dedupe."""

import json
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.dedupe import (
    apply_dedupe_plan,
    find_duplicates,
    review_dedupe_plan,
    summarize_duplicates,
    write_dedupe_plan,
)
from sfxworkbench.delete import build_delete_plan


def _seed_files(tmp_db: Path, files: list[dict]) -> None:
    """Insert minimal file rows for testing."""
    conn = get_connection(tmp_db)
    for f in files:
        conn.execute(
            """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f["path"],
                Path(f["path"]).name,
                Path(f["path"]).stem,
                Path(f["path"]).suffix,
                f.get("size", 1024),
                0.0,
                f.get("md5"),
                "2026-01-01T00:00:00",
            ),
        )
    conn.commit()
    conn.close()


def test_find_duplicates_groups_by_md5(tmp_db: Path) -> None:
    _seed_files(
        tmp_db,
        [
            {"path": "/a/one.wav", "md5": "AAA", "size": 1000},
            {"path": "/b/one.wav", "md5": "AAA", "size": 1000},
            {"path": "/c/two.wav", "md5": "BBB", "size": 500},
        ],
    )
    groups = find_duplicates(tmp_db)
    assert len(groups) == 1
    assert groups[0].hash == "AAA"
    assert len(groups[0].files) == 2


def test_find_duplicates_ignores_singletons(tmp_db: Path) -> None:
    _seed_files(
        tmp_db,
        [
            {"path": "/a/unique.wav", "md5": "XXX"},
        ],
    )
    groups = find_duplicates(tmp_db)
    assert groups == []


def test_find_duplicates_skips_null_md5(tmp_db: Path) -> None:
    _seed_files(
        tmp_db,
        [
            {"path": "/a/no_hash.wav", "md5": None},
            {"path": "/b/no_hash.wav", "md5": None},
        ],
    )
    groups = find_duplicates(tmp_db)
    assert groups == []


def test_find_duplicates_sorts_by_size(tmp_db: Path) -> None:
    """Largest groups first so users see biggest wins at the top."""
    _seed_files(
        tmp_db,
        [
            {"path": "/a/small1.wav", "md5": "S", "size": 100},
            {"path": "/a/small2.wav", "md5": "S", "size": 100},
            {"path": "/a/big1.wav", "md5": "B", "size": 99999},
            {"path": "/a/big2.wav", "md5": "B", "size": 99999},
        ],
    )
    groups = find_duplicates(tmp_db)
    assert len(groups) == 2
    assert groups[0].hash == "B"
    assert groups[1].hash == "S"


def test_find_duplicates_deterministic_ordering(tmp_db: Path) -> None:
    """File ordering within a group should be deterministic across runs."""
    _seed_files(
        tmp_db,
        [
            {"path": "/z/last.wav", "md5": "M"},
            {"path": "/a/first.wav", "md5": "M"},
            {"path": "/m/middle.wav", "md5": "M"},
        ],
    )
    groups1 = find_duplicates(tmp_db)
    groups2 = find_duplicates(tmp_db)
    assert groups1[0].files == groups2[0].files
    assert groups1[0].files == sorted(groups1[0].files)


def test_find_duplicates_handles_pipe_in_path(tmp_db: Path) -> None:
    """Paths containing the legacy '|||' separator must not corrupt the group."""
    _seed_files(
        tmp_db,
        [
            {"path": "/odd/with|||pipe.wav", "md5": "P"},
            {"path": "/odd/normal.wav", "md5": "P"},
        ],
    )
    groups = find_duplicates(tmp_db)
    assert len(groups) == 1
    assert "/odd/with|||pipe.wav" in groups[0].files
    assert "/odd/normal.wav" in groups[0].files


def test_summarize_duplicates(tmp_db: Path) -> None:
    _seed_files(
        tmp_db,
        [
            {"path": "/a/one.wav", "md5": "A", "size": 100},
            {"path": "/b/one.wav", "md5": "A", "size": 100},
            {"path": "/c/two.wav", "md5": "B", "size": 250},
            {"path": "/d/two.wav", "md5": "B", "size": 250},
            {"path": "/e/two.wav", "md5": "B", "size": 250},
        ],
    )
    summary = summarize_duplicates(find_duplicates(tmp_db))

    assert summary.duplicate_groups == 2
    assert summary.duplicate_files == 5
    assert summary.extra_copies == 3
    assert summary.wasted_bytes == 600
    assert summary.largest_group_bytes == 500
    assert summary.largest_group_copies == 3


def test_write_dedupe_plan(tmp_db: Path, tmp_path: Path) -> None:
    _seed_files(
        tmp_db,
        [
            {"path": "/a/one.wav", "md5": "AAA", "size": 100},
            {"path": "/b/one.wav", "md5": "AAA", "size": 100},
            {"path": "/c/one.wav", "md5": "AAA", "size": 100},
        ],
    )
    groups = find_duplicates(tmp_db)
    plan_path = tmp_path / "plan.json"
    write_dedupe_plan(groups, plan_path)

    plan = json.loads(plan_path.read_text())
    assert plan["schema_version"] == 1
    assert plan["tool"] == "sfxworkbench"
    assert "groups" in plan
    assert len(plan["groups"]) == 1
    actions = [e["action"] for e in plan["groups"][0]]
    assert actions.count("keep") == 1
    assert actions.count("remove") == 2


def test_write_dedupe_plan_prefers_safe_folder_keep_and_ignores_protected_copies(tmp_db: Path, tmp_path: Path) -> None:
    safe = tmp_path / "Master"
    protected_keep = safe / "a.wav"
    protected_duplicate = safe / "b.wav"
    duplicate = tmp_path / "Imports" / "c.wav"
    _seed_files(
        tmp_db,
        [
            {"path": str(duplicate), "md5": "AAA", "size": 100},
            {"path": str(protected_duplicate), "md5": "AAA", "size": 100},
            {"path": str(protected_keep), "md5": "AAA", "size": 100},
        ],
    )
    groups = find_duplicates(tmp_db)
    plan_path = tmp_path / "plan.json"

    write_dedupe_plan(groups, plan_path, safe_folders=[safe], quiet=True)

    plan = json.loads(plan_path.read_text())
    entries = plan["groups"][0]
    assert plan["safe_folders"] == [str(safe.resolve())]
    assert entries[0]["path"] == str(protected_keep)
    assert entries[0]["action"] == "keep"
    assert entries[0]["protected_by"] == str(safe.resolve())
    assert entries[1]["path"] == str(protected_duplicate)
    assert entries[1]["action"] == "ignore"
    assert entries[1]["reason"].startswith("file is inside safe folder")
    assert entries[2]["path"] == str(duplicate)
    assert entries[2]["action"] == "remove"
    assert entries[2]["keep_protected_by"] == str(safe.resolve())


def test_write_dedupe_plan_uses_config_safe_folder(tmp_db: Path, tmp_path: Path) -> None:
    safe = tmp_path / "Master"
    protected = safe / "a.wav"
    duplicate = tmp_path / "Imports" / "a.wav"
    _seed_files(
        tmp_db,
        [
            {"path": str(duplicate), "md5": "AAA", "size": 100},
            {"path": str(protected), "md5": "AAA", "size": 100},
        ],
    )
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(safe)]}))
    plan_path = tmp_path / "plan.json"

    write_dedupe_plan(find_duplicates(tmp_db), plan_path, config_path=config_path, quiet=True)

    plan = json.loads(plan_path.read_text())
    assert plan["safe_folders"] == [str(safe.resolve())]
    assert plan["groups"][0][0]["path"] == str(protected)
    assert plan["groups"][0][0]["action"] == "keep"
    assert plan["groups"][0][1]["path"] == str(duplicate)
    assert plan["groups"][0][1]["action"] == "remove"


def test_write_dedupe_plan_uses_preferred_folder_and_extension(tmp_db: Path, tmp_path: Path) -> None:
    preferred = tmp_path / "Preferred"
    wav = preferred / "sound.wav"
    aif = tmp_path / "Imports" / "sound.aif"
    flac = tmp_path / "Imports" / "sound.flac"
    _seed_files(
        tmp_db,
        [
            {"path": str(aif), "md5": "AAA", "size": 100},
            {"path": str(flac), "md5": "AAA", "size": 100},
            {"path": str(wav), "md5": "AAA", "size": 100},
        ],
    )
    groups = find_duplicates(tmp_db)
    plan_path = tmp_path / "plan.json"

    write_dedupe_plan(groups, plan_path, prefer_folders=[preferred], prefer_extensions=["wav"], quiet=True)

    entries = json.loads(plan_path.read_text())["groups"][0]
    assert entries[0]["path"] == str(wav)
    assert entries[0]["action"] == "keep"
    assert entries[0]["preservation_evidence"] == [
        {"rule": "prefer_folder", "value": str(preferred.resolve())},
        {"rule": "prefer_extension", "value": ".wav"},
    ]
    assert entries[1]["keep_preservation_evidence"] == entries[0]["preservation_evidence"]


def test_review_dedupe_plan_approves_all_groups(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [{"path": "/a.wav", "action": "keep"}, {"path": "/b.wav", "action": "remove"}],
                    [{"path": "/c.wav", "action": "keep"}, {"path": "/d.wav", "action": "remove"}],
                ]
            }
        )
    )

    result = review_dedupe_plan(plan_path, approve_all=True)
    plan = json.loads(plan_path.read_text())

    assert result.total_groups == 2
    assert result.approved_groups == 2
    assert plan["review"]["status"] == "approved"
    assert plan["review"]["approved_groups"] == [0, 1]


def test_review_dedupe_plan_marks_selected_groups(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "reviewed.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [{"path": "/a.wav", "action": "keep"}],
                    [{"path": "/b.wav", "action": "keep"}],
                ]
            }
        )
    )

    result = review_dedupe_plan(plan_path, output_path=output_path, groups=[2, 9])
    plan = json.loads(output_path.read_text())

    assert result.approved_groups == 1
    assert result.invalid_groups == [9]
    assert plan["review"]["status"] == "partially_approved"
    assert plan["review"]["approved_groups"] == [1]


def test_apply_dedupe_dry_run_makes_no_changes(tmp_path: Path) -> None:
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(b"audio")
    b.write_bytes(b"audio")

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(a), "action": "keep", "size_bytes": 5},
                        {"path": str(b), "action": "remove", "size_bytes": 5},
                    ]
                ]
            }
        )
    )

    result = apply_dedupe_plan(plan_path, dry_run=True)
    assert result.dry_run is True
    assert result.removed == 1
    assert a.exists() and b.exists(), "Dry run should not delete anything"


def test_apply_dedupe_can_require_reviewed_plan(tmp_path: Path) -> None:
    a = tmp_path / "keep.wav"
    b = tmp_path / "drop.wav"
    a.write_bytes(b"audio")
    b.write_bytes(b"audio")

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(a), "action": "keep", "size_bytes": 5},
                        {"path": str(b), "action": "remove", "size_bytes": 5},
                    ]
                ]
            }
        )
    )

    blocked = apply_dedupe_plan(plan_path, dry_run=False, quarantine_dir=tmp_path / "q", require_reviewed=True)
    assert blocked.errors
    assert b.exists()

    review_dedupe_plan(plan_path, approve_all=True)
    applied = apply_dedupe_plan(plan_path, dry_run=False, quarantine_dir=tmp_path / "q", require_reviewed=True)

    assert applied.errors == []
    assert applied.quarantined == 1
    assert not b.exists()


def test_apply_dedupe_refuses_cli_safe_folder_even_for_old_plan(tmp_path: Path) -> None:
    a = tmp_path / "keep.wav"
    b = tmp_path / "Protected" / "drop.wav"
    a.parent.mkdir(parents=True, exist_ok=True)
    b.parent.mkdir(parents=True, exist_ok=True)
    a.write_bytes(b"audio")
    b.write_bytes(b"audio")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(a), "action": "keep", "size_bytes": 5},
                        {"path": str(b), "action": "remove", "size_bytes": 5},
                    ]
                ]
            }
        )
    )
    review_dedupe_plan(plan_path, approve_all=True, quiet=True)

    result = apply_dedupe_plan(
        plan_path,
        dry_run=False,
        quarantine_dir=tmp_path / "q",
        require_reviewed=True,
        safe_folders=[b.parent],
        quiet=True,
    )

    assert result.quarantined == 0
    assert b.exists()
    assert result.errors == [
        {
            "path": str(b),
            "safe_folder": str(b.parent.resolve()),
            "error": "file is protected by safe folder",
        }
    ]


def test_apply_dedupe_refuses_config_safe_folder_even_for_old_plan(tmp_path: Path) -> None:
    a = tmp_path / "keep.wav"
    b = tmp_path / "Protected" / "drop.wav"
    b.parent.mkdir(parents=True, exist_ok=True)
    a.write_bytes(b"audio")
    b.write_bytes(b"audio")
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(b.parent)]}))
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(a), "action": "keep", "size_bytes": 5},
                        {"path": str(b), "action": "remove", "size_bytes": 5},
                    ]
                ]
            }
        )
    )
    review_dedupe_plan(plan_path, approve_all=True, quiet=True)

    result = apply_dedupe_plan(
        plan_path,
        dry_run=False,
        quarantine_dir=tmp_path / "q",
        require_reviewed=True,
        config_path=config_path,
        quiet=True,
    )

    assert result.quarantined == 0
    assert b.exists()
    assert result.errors[0]["safe_folder"] == str(b.parent.resolve())


def test_apply_dedupe_removes_files_and_updates_db(tmp_db: Path, tmp_path: Path) -> None:
    """After --apply, removed files should be quarantined AND deleted from the index."""
    a = tmp_path / "keep.wav"
    b = tmp_path / "drop.wav"
    a.write_bytes(b"audio")
    b.write_bytes(b"audio")

    _seed_files(
        tmp_db,
        [
            {"path": str(a), "md5": "AAA"},
            {"path": str(b), "md5": "AAA"},
        ],
    )

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(a), "action": "keep", "size_bytes": 5},
                        {"path": str(b), "action": "remove", "size_bytes": 5},
                    ]
                ]
            }
        )
    )

    quarantine = tmp_path / "quarantine"
    result = apply_dedupe_plan(plan_path, db_path=tmp_db, dry_run=False, quarantine_dir=quarantine)
    assert result.dry_run is False
    assert result.removed == 1
    assert result.quarantined == 1
    assert a.exists()
    assert not b.exists(), "Removed file should be moved from original location"
    assert any(p.name == "drop.wav" for p in quarantine.rglob("*"))

    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    paths = [row["path"] for row in rows]
    conn.close()
    assert str(a) in paths
    assert str(b) not in paths, "Removed file should also be deleted from the index"


def test_apply_dedupe_writes_quarantine_log_for_delete_planning(tmp_path: Path) -> None:
    keep = tmp_path / "keep.wav"
    drop = tmp_path / "drop.wav"
    keep.write_bytes(b"audio")
    drop.write_bytes(b"audio")
    plan_path = tmp_path / "plan.json"
    log_path = tmp_path / "dedupe_quarantine_log.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(keep), "action": "keep", "size_bytes": 5},
                        {"path": str(drop), "action": "remove", "size_bytes": 5},
                    ]
                ]
            }
        )
    )

    result = apply_dedupe_plan(plan_path, dry_run=False, quarantine_dir=tmp_path / "q", log_path=log_path)
    payload = json.loads(log_path.read_text())
    delete_plan = build_delete_plan(log_path)

    assert result.log_path == str(log_path)
    assert payload["entries"][0]["path"] == str(drop)
    assert Path(payload["entries"][0]["quarantine_path"]).exists()
    assert delete_plan.summary.candidate_entries == 1
    assert delete_plan.entries[0].source_path == str(drop)


def test_apply_dedupe_records_errors(tmp_path: Path) -> None:
    """Missing files should produce errors but not crash."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(tmp_path / "keep.wav"), "action": "keep", "size_bytes": 5},
                        {"path": str(tmp_path / "missing.wav"), "action": "remove", "size_bytes": 5},
                    ]
                ]
            }
        )
    )
    result = apply_dedupe_plan(plan_path, dry_run=False)
    assert len(result.errors) == 1


def test_apply_dedupe_validates_size_before_quarantine(tmp_path: Path) -> None:
    drop = tmp_path / "drop.wav"
    drop.write_bytes(b"audio")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "groups": [
                    [
                        {"path": str(drop), "action": "remove", "size_bytes": 999, "hash": None},
                    ]
                ]
            }
        )
    )

    result = apply_dedupe_plan(plan_path, dry_run=False, quarantine_dir=tmp_path / "q")

    assert len(result.errors) == 1
    assert drop.exists()
