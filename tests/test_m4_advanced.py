"""Tests for M4 advanced maintenance workflows."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf
from sfxworkbench.compare import build_compare_plan, build_compare_report, write_compare_report
from sfxworkbench.db import get_connection
from sfxworkbench.delete import apply_delete_plan, build_delete_plan, review_delete_plan, write_delete_plan
from sfxworkbench.dual_mono import (
    apply_dual_mono_plan,
    build_dual_mono_plan,
    build_dual_mono_report,
    review_dual_mono_plan,
    write_dual_mono_plan,
    write_dual_mono_report,
)
from sfxworkbench.preservation import build_preservation_rules, score_explanation
from sfxworkbench.processed import build_processed_file_report


def _seed_file(tmp_db: Path, path: Path, *, md5: str | None = None, channels: int = 2) -> None:
    conn = get_connection(tmp_db)
    conn.execute(
        """
        INSERT INTO files (
            path, filename, stem, extension, size_bytes, mtime, md5,
            sample_rate, bit_depth, channels, duration_s, scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path),
            path.name,
            path.stem,
            path.suffix.lower(),
            path.stat().st_size if path.exists() else 100,
            path.stat().st_mtime if path.exists() else 0.0,
            md5,
            48000,
            24,
            channels,
            1.0,
            "2026",
        ),
    )
    conn.commit()
    conn.close()


def test_compare_report_and_plan_detect_exact_import_duplicates(tmp_path: Path, tmp_db: Path) -> None:
    master = tmp_path / "master.wav"
    incoming = tmp_path / "incoming" / "copy.wav"
    incoming.parent.mkdir()
    payload = b"same audio bytes"
    master.write_bytes(payload)
    incoming.write_bytes(payload)
    import hashlib

    _seed_file(tmp_db, master, md5=hashlib.md5(payload).hexdigest())

    report = build_compare_report(incoming.parent, against_db=tmp_db)
    report_path = tmp_path / "compare.json"
    write_compare_report(report, report_path, quiet=True)
    plan = build_compare_plan(report_path)

    assert report.summary.exact_duplicate_files == 1
    assert report.entries[0].status == "exact_duplicate"
    assert plan.summary.skip_import_entries == 1
    assert plan.entries[0].action == "skip_import"


def test_processed_report_groups_rendered_variant_with_source(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "Door Slam.wav"
    processed = root / "Door Slam Rendered.wav"
    source.write_bytes(b"source")
    processed.write_bytes(b"processed")
    _seed_file(tmp_db, source)
    _seed_file(tmp_db, processed)

    report = build_processed_file_report(root, db_path=tmp_db)

    assert report.summary.candidates == 1
    assert report.summary.grouped_with_source == 1
    assert report.entries[0].likely_source_path == str(source)
    assert report.entries[0].processed_tokens == ["rendered"]


def test_delete_plan_review_apply_deletes_only_quarantine_log_paths(tmp_path: Path) -> None:
    quarantine = tmp_path / "quarantine" / "old.wav"
    quarantine.parent.mkdir()
    quarantine.write_bytes(b"delete me")
    source_log = tmp_path / "pack_quarantine_log.json"
    source_log.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "folder_path": str(tmp_path / "original" / "old.wav"),
                        "quarantine_path": str(quarantine),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = build_delete_plan(source_log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    dry = apply_delete_plan(
        plan_path,
        dry_run=True,
        require_reviewed=True,
        understand_permanent_delete=False,
        quiet=True,
    )
    result = apply_delete_plan(
        plan_path,
        dry_run=False,
        require_reviewed=True,
        understand_permanent_delete=True,
        log_path=tmp_path / "delete_log.json",
        quiet=True,
    )

    assert dry.deleted == 1
    assert result.deleted == 1
    assert not quarantine.exists()
    assert result.log_path is not None


def test_delete_plan_blocks_safe_folder(tmp_path: Path) -> None:
    safe = tmp_path / "safe"
    quarantined = safe / "old.wav"
    safe.mkdir()
    quarantined.write_bytes(b"protected")
    source_log = tmp_path / "pack_quarantine_log.json"
    source_log.write_text(json.dumps({"entries": [{"quarantine_path": str(quarantined)}]}), encoding="utf-8")

    plan = build_delete_plan(source_log, safe_folders=[safe])

    assert plan.entries == []
    assert plan.errors[0]["safe_folder"] == str(safe.resolve())


def test_dual_mono_audit_plan_and_copy_output_apply(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Dual Mono.wav"
    signal = np.linspace(-0.5, 0.5, 64, dtype=np.float32)
    sf.write(audio, np.column_stack([signal, signal]), 48000, subtype="PCM_16")
    _seed_file(tmp_db, audio, channels=2)

    report = build_dual_mono_report(root, db_path=tmp_db)
    report_path = tmp_path / "dual_mono_report.json"
    write_dual_mono_report(report, report_path, quiet=True)
    plan = build_dual_mono_plan(report_path)
    plan_path = tmp_path / "dual_mono_plan.json"
    write_dual_mono_plan(plan, plan_path, quiet=True)
    review_dual_mono_plan(plan_path, approve_all=True, quiet=True)
    output_root = tmp_path / "converted"
    result = apply_dual_mono_plan(
        plan_path,
        output_root=output_root,
        dry_run=False,
        require_reviewed=True,
        log_path=tmp_path / "dual_mono_log.json",
        quiet=True,
    )

    converted = output_root / "Dual Mono.mono.wav"
    data, _sample_rate = sf.read(converted, always_2d=True)
    assert report.summary.candidates == 1
    assert result.written == 1
    assert audio.exists()
    assert converted.exists()
    assert data.shape[1] == 1


def test_dual_mono_plan_blocks_safe_folder(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Protected.wav"
    signal = np.ones(32, dtype=np.float32)
    sf.write(audio, np.column_stack([signal, signal]), 48000)
    _seed_file(tmp_db, audio, channels=2)
    report = build_dual_mono_report(root, db_path=tmp_db)
    report_path = tmp_path / "dual_mono_report.json"
    write_dual_mono_report(report, report_path, quiet=True)

    plan = build_dual_mono_plan(report_path, safe_folders=[root])

    assert plan.entries == []
    assert plan.errors[0]["safe_folder"] == str(root.resolve())


def test_preservation_score_explanation_reports_ordered_rules(tmp_path: Path) -> None:
    safe = tmp_path / "safe"
    preferred = tmp_path / "preferred"
    target = preferred / "sound.wav"
    safe.mkdir()
    preferred.mkdir()
    target.write_bytes(b"x")

    rules = build_preservation_rules(safe_folders=[safe], prefer_folders=[preferred], prefer_extensions=["wav"])
    explanation = score_explanation(target, rules)

    assert explanation["score"] == [1, 0, 0]
    assert explanation["evidence"] == [
        {"rule": "prefer_folder", "value": str(preferred.resolve())},
        {"rule": "prefer_extension", "value": ".wav"},
    ]


def test_delete_apply_can_remove_quarantined_directory(tmp_path: Path) -> None:
    quarantined = tmp_path / "quarantine" / "folder"
    quarantined.mkdir(parents=True)
    (quarantined / "a.wav").write_bytes(b"a")
    source_log = tmp_path / "pack_quarantine_log.json"
    source_log.write_text(json.dumps({"entries": [{"quarantine_path": str(quarantined)}]}), encoding="utf-8")
    plan = build_delete_plan(source_log)
    plan_path = tmp_path / "delete_plan.json"
    write_delete_plan(plan, plan_path, quiet=True)
    review_delete_plan(plan_path, approve_all=True, quiet=True)

    result = apply_delete_plan(
        plan_path,
        dry_run=False,
        require_reviewed=True,
        understand_permanent_delete=True,
        quiet=True,
    )

    assert result.deleted == 1
    assert not quarantined.exists()
    assert not (tmp_path / "quarantine").exists() or not any((tmp_path / "quarantine").iterdir())


def test_dual_mono_apply_refuses_existing_output(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    audio = root / "Dual Mono.wav"
    signal = np.ones(16, dtype=np.float32)
    sf.write(audio, np.column_stack([signal, signal]), 48000)
    _seed_file(tmp_db, audio, channels=2)
    report_path = tmp_path / "dual_mono_report.json"
    write_dual_mono_report(build_dual_mono_report(root, db_path=tmp_db), report_path, quiet=True)
    plan_path = tmp_path / "dual_mono_plan.json"
    write_dual_mono_plan(build_dual_mono_plan(report_path), plan_path, quiet=True)
    review_dual_mono_plan(plan_path, approve_all=True, quiet=True)
    output = tmp_path / "converted" / "Dual Mono.mono.wav"
    output.parent.mkdir()
    output.write_bytes(b"existing")

    result = apply_dual_mono_plan(
        plan_path,
        output_root=tmp_path / "converted",
        dry_run=False,
        require_reviewed=True,
        quiet=True,
    )

    assert result.written == 0
    assert result.errors[0]["error"] == "output file already exists"


def test_delete_plan_directory_size_is_recursive(tmp_path: Path) -> None:
    quarantined = tmp_path / "quarantine" / "folder"
    quarantined.mkdir(parents=True)
    (quarantined / "a.wav").write_bytes(b"aaa")
    (quarantined / "b.wav").write_bytes(b"bb")
    source_log = tmp_path / "pack_quarantine_log.json"
    source_log.write_text(json.dumps({"entries": [{"quarantine_path": str(quarantined)}]}), encoding="utf-8")

    plan = build_delete_plan(source_log)

    assert plan.entries[0].path_type == "dir"
    assert plan.entries[0].size_bytes == 5


def test_compare_ignores_junk_audio_sidecars(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "incoming"
    root.mkdir()
    (root / "._bad.wav").write_bytes(b"junk")
    report = build_compare_report(root, against_db=tmp_db)

    assert report.summary.files_considered == 0


def teardown_module() -> None:
    # Keep pytest's temp cleanup deterministic if a failed test leaves converted trees.
    shutil.rmtree("/tmp/sfxworkbench-unused", ignore_errors=True)
