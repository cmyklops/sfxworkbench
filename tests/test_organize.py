"""Tests for folder organization previews."""

from pathlib import Path

from wavwarden.db import get_connection
from wavwarden.models import NestingCandidate
from wavwarden.organize import (
    apply_nesting_plan,
    apply_organize_report,
    audit_organization,
    build_nesting_plan_from_report,
    review_organize_report,
    undo_nesting_log,
    undo_organize_log,
    write_organize_audit_report,
)


def test_organize_audit_strips_obvious_top_level_sort_prefixes(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    for name in [
        "01 - Ghosthack - Ultimate Foley Sounds",
        "01 Ancient_Game",
        "1 Boom TRAX",
        "1. SoundMorph - Energy",
        "[99Sounds]",
        "(A Sound Effect)",
        "[02 - SoundMorph - Impacts]",
        "00  SoundMorph - Sinematic 2",
        "10 Years Anniversary Addition - Cinematic Metal Impacts",
        "10000",
    ]:
        (root / name).mkdir()

    report = audit_organization(root)

    planned = {entry.old_name: entry.new_name for entry in report.entries}
    assert planned == {
        "01 - Ghosthack - Ultimate Foley Sounds": "Ghosthack - Ultimate Foley Sounds",
        "01 Ancient_Game": "Ancient_Game",
        "1 Boom TRAX": "Boom TRAX",
        "1. SoundMorph - Energy": "SoundMorph - Energy",
        "[99Sounds]": "99Sounds",
        "(A Sound Effect)": "A Sound Effect",
        "[02 - SoundMorph - Impacts]": "SoundMorph - Impacts",
        "00  SoundMorph - Sinematic 2": "SoundMorph - Sinematic 2",
    }
    assert report.summary.directories_scanned == 10
    assert report.summary.planned == 8
    assert report.summary.errors == 0


def test_organize_audit_reports_collisions(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "01 Boom").mkdir()
    (root / "Boom").mkdir()

    report = audit_organization(root)

    assert report.entries == []
    assert report.summary.errors == 1
    assert report.errors[0]["error"] == "target exists"


def test_organize_audit_respects_depth(tmp_path: Path) -> None:
    root = tmp_path / "library"
    nested = root / "Vendor" / "01 Pack"
    nested.mkdir(parents=True)

    top_report = audit_organization(root, depth=1)
    nested_report = audit_organization(root, depth=2)

    assert top_report.entries == []
    assert [entry.new_name for entry in nested_report.entries] == ["Pack"]


def test_vendor_product_folders_preview_known_vendors(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    for name in [
        "SoundMorph - Energy",
        "SoundMorph_Universe_Bundle_Free_Sounds",
        "1. Ghosthack - Ultimate Foley Sounds",
        "Ghosthack_-_Free_Whooshes_and_Impacts",
        "[A Sound Effect - Whooshes]",
        "Unknown Vendor - Pack",
    ]:
        (root / name).mkdir()

    report = audit_organization(root, pattern="vendor-product-folders")

    planned = {entry.old_name: entry.new_path for entry in report.entries}
    assert planned == {
        "SoundMorph - Energy": str(root.resolve() / "SoundMorph" / "Energy"),
        "SoundMorph_Universe_Bundle_Free_Sounds": str(root.resolve() / "SoundMorph" / "Universe_Bundle_Free_Sounds"),
        "1. Ghosthack - Ultimate Foley Sounds": str(root.resolve() / "Ghosthack" / "Ultimate Foley Sounds"),
        "Ghosthack_-_Free_Whooshes_and_Impacts": str(root.resolve() / "Ghosthack" / "Free_Whooshes_and_Impacts"),
        "[A Sound Effect - Whooshes]": str(root.resolve() / "A Sound Effect" / "Whooshes"),
    }
    assert report.summary.directories_scanned == 6
    assert report.summary.planned == 5
    assert report.summary.errors == 0


def test_vendor_product_folders_reports_collision(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "SoundMorph - Energy").mkdir()
    (root / "SoundMorph" / "Energy").mkdir(parents=True)

    report = audit_organization(root, pattern="vendor-product-folders")

    assert report.entries == []
    assert report.summary.errors == 1
    assert report.errors[0]["error"] == "target exists"


def test_common_prefix_folders_groups_gdc_family(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    for name in [
        "GDC 2015 - Soniss",
        "GDC 2016 - Soniss",
        "GDC SFX 2015",
        "GDC SFX 2017",
        "GDC+++Game+Audio+Bundle",
        "GDC2023",
        "Crowd",
    ]:
        (root / name).mkdir()

    report = audit_organization(root, pattern="common-prefix-folders")

    planned = {entry.old_name: entry.new_path for entry in report.entries}
    assert planned == {
        "GDC 2015 - Soniss": str(root.resolve() / "GDC" / "2015 - Soniss"),
        "GDC 2016 - Soniss": str(root.resolve() / "GDC" / "2016 - Soniss"),
        "GDC SFX 2015": str(root.resolve() / "GDC" / "SFX 2015"),
        "GDC SFX 2017": str(root.resolve() / "GDC" / "SFX 2017"),
        "GDC+++Game+Audio+Bundle": str(root.resolve() / "GDC" / "Game Audio Bundle"),
        "GDC2023": str(root.resolve() / "GDC" / "2023"),
    }
    assert report.summary.directories_scanned == 7
    assert report.summary.planned == 6
    assert report.summary.errors == 0


def test_common_prefix_folders_groups_numbered_family(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    for name in ["Creature Consolidated", "CreaturesCK_1", "CreaturesCK_2", "CreaturesCK_3", "Crowd"]:
        (root / name).mkdir()

    report = audit_organization(root, pattern="common-prefix-folders")

    planned = {entry.old_name: entry.new_path for entry in report.entries}
    assert planned == {
        "CreaturesCK_1": str(root.resolve() / "CreaturesCK" / "1"),
        "CreaturesCK_2": str(root.resolve() / "CreaturesCK" / "2"),
        "CreaturesCK_3": str(root.resolve() / "CreaturesCK" / "3"),
    }


def test_common_prefix_folders_requires_three_siblings(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "Tiny_1").mkdir()
    (root / "Tiny_2").mkdir()

    report = audit_organization(root, pattern="common-prefix-folders")

    assert report.entries == []
    assert report.summary.planned == 0


def test_common_prefix_folders_ignores_title_case_words(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    for name in ["Magic Arcane", "Magic Fire", "Magic Ice", "Dark Elements", "Dark Engine", "Dark Side"]:
        (root / name).mkdir()

    report = audit_organization(root, pattern="common-prefix-folders")

    assert report.entries == []


def test_numeric_series_folders_uses_known_catalog(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "6000").mkdir()
    (root / "9000").mkdir()

    report = audit_organization(root, pattern="numeric-series-folders")

    planned = {entry.old_name: entry.new_path for entry in report.entries}
    assert planned == {
        "6000": str(root.resolve() / "Sound Ideas" / "The General Series 6000"),
        "9000": str(root.resolve() / "Sound Ideas" / "Series 9000 Open and Close"),
    }
    assert report.summary.planned == 2
    assert report.summary.candidates == 0


def test_numeric_series_folders_infers_category_from_filenames(tmp_path: Path) -> None:
    root = tmp_path / "library"
    folder = root / "4242"
    folder.mkdir(parents=True)
    for name in ["bird_chirp_01.wav", "bird_wing_02.wav", "dog_bark_03.wav", "animal_scurry_04.wav"]:
        (folder / name).write_bytes(b"audio")

    report = audit_organization(root, pattern="numeric-series-folders")

    assert len(report.entries) == 1
    assert report.entries[0].old_name == "4242"
    assert report.entries[0].new_path == str(root.resolve() / "Animals" / "4242")
    assert report.entries[0].reason == "numeric_series_inferred_category"


def test_numeric_series_folders_reports_unknown_candidates(tmp_path: Path) -> None:
    root = tmp_path / "library"
    folder = root / "4242"
    folder.mkdir(parents=True)
    (folder / "mystery.wav").write_bytes(b"audio")

    report = audit_organization(root, pattern="numeric-series-folders")

    assert report.entries == []
    assert report.summary.candidates == 1
    assert report.candidates[0].kind == "numeric_series_unknown"


def test_organize_audit_rejects_unknown_pattern(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()

    try:
        audit_organization(root, pattern="unknown")
    except ValueError as e:
        assert "strip-leading-numbers" in str(e)
        assert "common-prefix-folders" in str(e)
        assert "numeric-series-folders" in str(e)
        assert "vendor-product-folders" in str(e)
        assert "redundant-nesting" in str(e)
    else:
        raise AssertionError("Expected ValueError")


def test_write_organize_audit_report(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "01 Pack").mkdir()
    report = audit_organization(root)
    out = tmp_path / "reports" / "organize.json"

    write_organize_audit_report(report, out, quiet=True)

    assert out.exists()
    assert '"new_name": "Pack"' in out.read_text()


def test_review_organize_report_approves_entries(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "01 Pack").mkdir()
    report = audit_organization(root)
    report_path = tmp_path / "organize.json"
    write_organize_audit_report(report, report_path, quiet=True)

    result = review_organize_report(report_path, approve_all=True, quiet=True)

    assert result.total_entries == 1
    assert result.approved_entries == 1
    assert '"approved_entries": [\n      0\n    ]' in report_path.read_text()


def test_apply_organize_report_requires_review(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "01 Pack"
    source.mkdir()
    report = audit_organization(root)
    report_path = tmp_path / "organize.json"
    write_organize_audit_report(report, report_path, quiet=True)

    result = apply_organize_report(report_path, require_reviewed=True, quiet=True)

    assert result.renamed == 0
    assert result.errors
    assert source.exists()


def test_apply_and_undo_vendor_product_folder_updates_filesystem_and_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    source = root / "SoundMorph - Energy"
    source.mkdir(parents=True)
    audio = source / "hit.wav"
    audio.write_bytes(b"audio")
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root, pattern="vendor-product-folders")
    report_path = tmp_path / "vendor_report.json"
    log_path = tmp_path / "vendor_log.json"
    write_organize_audit_report(report, report_path, quiet=True)
    review_organize_report(report_path, approve_all=True, quiet=True)

    result = apply_organize_report(report_path, db_path=tmp_db, log_path=log_path, require_reviewed=True, quiet=True)

    moved = root / "SoundMorph" / "Energy" / "hit.wav"
    assert result.renamed == 1
    assert moved.exists()
    conn = get_connection(tmp_db)
    indexed_path = conn.execute("SELECT path FROM files").fetchone()[0]
    conn.close()
    assert indexed_path == str(moved)

    undo = undo_organize_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.undone == 1
    assert audio.exists()
    assert not (root / "SoundMorph").exists()
    conn = get_connection(tmp_db)
    indexed_path = conn.execute("SELECT path FROM files").fetchone()[0]
    conn.close()
    assert indexed_path == str(audio)


def test_apply_common_prefix_folder_creates_parent_and_updates_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    for name in ["CreaturesCK_1", "CreaturesCK_2", "CreaturesCK_3"]:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "hit.wav").write_bytes(b"audio")
    audio = root / "CreaturesCK_1" / "hit.wav"
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root, pattern="common-prefix-folders")
    report_path = tmp_path / "common_prefix_report.json"
    write_organize_audit_report(report, report_path, quiet=True)
    review_organize_report(report_path, approve_all=True, quiet=True)

    result = apply_organize_report(
        report_path, db_path=tmp_db, log_path=tmp_path / "common_prefix_log.json", require_reviewed=True, quiet=True
    )

    moved = root / "CreaturesCK" / "1" / "hit.wav"
    assert result.renamed == 3
    assert moved.exists()
    conn = get_connection(tmp_db)
    indexed_path = conn.execute("SELECT path FROM files").fetchone()[0]
    conn.close()
    assert indexed_path == str(moved)


def test_apply_numeric_series_folder_creates_parent_and_updates_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    folder = root / "4242"
    folder.mkdir(parents=True)
    audio = folder / "bird_chirp_01.wav"
    audio.write_bytes(b"audio")
    for name in ["bird_wing_02.wav", "dog_bark_03.wav", "animal_scurry_04.wav"]:
        (folder / name).write_bytes(b"audio")
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root, pattern="numeric-series-folders")
    report_path = tmp_path / "numeric_series_report.json"
    write_organize_audit_report(report, report_path, quiet=True)
    review_organize_report(report_path, approve_all=True, quiet=True)

    result = apply_organize_report(
        report_path, db_path=tmp_db, log_path=tmp_path / "numeric_series_log.json", require_reviewed=True, quiet=True
    )

    moved = root / "Animals" / "4242" / "bird_chirp_01.wav"
    assert result.renamed == 1
    assert moved.exists()
    conn = get_connection(tmp_db)
    indexed_path = conn.execute("SELECT path FROM files").fetchone()[0]
    conn.close()
    assert indexed_path == str(moved)


def test_redundant_nesting_reports_repeated_folder_names(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "Vendor" / "Pack" / "Pack" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    report = audit_organization(root, pattern="redundant-nesting", depth=4)

    repeated = [candidate for candidate in report.candidates if candidate.kind == "repeated_folder_name"]
    assert report.entries == []
    assert report.summary.candidates >= 1
    assert repeated[0].path == str(audio.parent)
    assert repeated[0].target_path == str(audio.parent.parent)
    assert repeated[0].confidence == "high"


def test_redundant_nesting_reports_single_child_chains(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "Vendor" / "Wrapper" / "Only Child" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    report = audit_organization(root, pattern="redundant-nesting", depth=4)

    chains = [candidate for candidate in report.candidates if candidate.kind == "single_child_chain"]
    assert any(candidate.path == str(root / "Vendor" / "Wrapper") for candidate in chains)
    assert all(candidate.suggested_action == "review_collapse_wrapper" for candidate in chains)


def test_redundant_nesting_keeps_numeric_category_parents(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "Vehicles" / "13000" / "car.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    report = audit_organization(root, pattern="redundant-nesting", depth=2)

    assert not [candidate for candidate in report.candidates if candidate.path == str(root / "Vehicles")]


def test_redundant_nesting_reports_low_value_wrappers(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "Vendor" / "Pack" / "WAV" / "hit.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")

    report = audit_organization(root, pattern="redundant-nesting", depth=4)

    wrappers = [candidate for candidate in report.candidates if candidate.kind == "low_value_wrapper"]
    assert wrappers[0].path == str(audio.parent)
    assert wrappers[0].target_path == str(audio.parent.parent)
    assert wrappers[0].audio_files == 1


def test_redundant_nesting_report_is_not_applyable(tmp_path: Path) -> None:
    root = tmp_path / "library"
    wrapper = root / "Vendor" / "Wrapper" / "Only Child"
    wrapper.mkdir(parents=True)
    (wrapper / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting.json"
    write_organize_audit_report(report, report_path, quiet=True)

    result = apply_organize_report(report_path, require_reviewed=False, quiet=True)

    assert result.renamed == 0
    assert result.errors
    assert "report-only" in result.errors[0]["error"]
    assert wrapper.exists()


def test_build_nesting_plan_from_repeated_folder_report(tmp_path: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    (repeated / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    plan_path = tmp_path / "nesting_plan.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, output_path=plan_path, quiet=True)

    assert plan_path.exists()
    assert len(plan.entries) == 1
    assert plan.entries[0].source_path == str(repeated)
    assert plan.entries[0].target_path == str(repeated.parent)
    assert plan.entries[0].moves[0].new_path == str(repeated.parent / "hit.wav")
    assert plan.errors == []


def test_build_nesting_plan_reports_collisions(tmp_path: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    (repeated / "hit.wav").write_bytes(b"audio")
    (repeated.parent / "hit.wav").write_bytes(b"existing")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, quiet=True)

    assert plan.entries == []
    assert plan.errors[0]["error"] == "target exists"


def test_build_nesting_plan_from_single_child_chain(tmp_path: Path) -> None:
    root = tmp_path / "library"
    child = root / "Wrapper" / "Real Pack"
    child.mkdir(parents=True)
    (child / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=3)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, kind="single_child_chain", quiet=True)

    assert len(plan.entries) == 1
    assert plan.entries[0].source_path == str(root / "Wrapper")
    assert plan.entries[0].target_path == str(root)
    assert plan.entries[0].action == "collapse_single_child_wrapper"
    assert plan.entries[0].moves[0].old_path == str(child)
    assert plan.entries[0].moves[0].new_path == str(root / "Real Pack")
    assert plan.errors == []


def test_build_nesting_plan_skips_numeric_category_parents_from_older_reports(tmp_path: Path) -> None:
    root = tmp_path / "library"
    child = root / "Vehicles" / "13000"
    child.mkdir(parents=True)
    (child / "car.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=2)
    report.candidates.append(
        NestingCandidate(
            path=str(root / "Vehicles"),
            name="Vehicles",
            kind="single_child_chain",
            suggested_action="review_collapse_wrapper",
            reason="folder only contains one child folder and no direct files",
            depth=1,
            parent_path=str(root),
            target_path=str(child),
            child_dirs=1,
            direct_files=0,
            audio_files=1,
            confidence="medium",
        )
    )
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, kind="single_child_chain", quiet=True)

    assert plan.entries == []
    assert plan.errors == []


def test_build_nesting_plan_orders_nested_single_child_chains_deepest_first(tmp_path: Path) -> None:
    root = tmp_path / "library"
    child = root / "Wrapper" / "Nested Wrapper" / "Real Pack"
    child.mkdir(parents=True)
    (child / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, kind="single_child_chain", quiet=True)

    assert [Path(entry.source_path).name for entry in plan.entries] == ["Nested Wrapper", "Wrapper"]


def test_build_nesting_plan_single_child_chain_reports_collisions(tmp_path: Path) -> None:
    root = tmp_path / "library"
    child = root / "Wrapper" / "Real Pack"
    child.mkdir(parents=True)
    (child / "hit.wav").write_bytes(b"audio")
    (root / "Real Pack").mkdir()
    report = audit_organization(root, pattern="redundant-nesting", depth=3)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, kind="single_child_chain", quiet=True)

    assert plan.entries == []
    assert plan.errors[0]["error"] == "target exists"


def test_build_nesting_plan_from_low_value_leaf_wrapper(tmp_path: Path) -> None:
    root = tmp_path / "library"
    wrapper = root / "Pack" / "Samples"
    wrapper.mkdir(parents=True)
    audio = wrapper / "hit.wav"
    audio.write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=3)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, kind="low_value_wrapper", quiet=True)

    assert len(plan.entries) == 1
    assert plan.entries[0].source_path == str(wrapper)
    assert plan.entries[0].target_path == str(wrapper.parent)
    assert plan.entries[0].action == "flatten_low_value_leaf_wrapper"
    assert plan.entries[0].moves[0].old_path == str(audio)
    assert plan.entries[0].moves[0].new_path == str(wrapper.parent / "hit.wav")
    assert plan.errors == []


def test_build_nesting_plan_low_value_wrapper_skips_semantic_names_and_child_dirs(tmp_path: Path) -> None:
    root = tmp_path / "library"
    designed = root / "Pack" / "Designed"
    designed.mkdir(parents=True)
    (designed / "hit.wav").write_bytes(b"audio")
    samples = root / "Other Pack" / "Samples" / "Subfolder"
    samples.mkdir(parents=True)
    (samples / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, kind="low_value_wrapper", quiet=True)

    assert plan.entries == []
    assert plan.errors == []


def test_build_nesting_plan_low_value_wrapper_reports_collisions(tmp_path: Path) -> None:
    root = tmp_path / "library"
    wrapper = root / "Pack" / "Samples"
    wrapper.mkdir(parents=True)
    (wrapper / "hit.wav").write_bytes(b"audio")
    (wrapper.parent / "hit.wav").write_bytes(b"existing")
    report = audit_organization(root, pattern="redundant-nesting", depth=3)
    report_path = tmp_path / "nesting_report.json"
    write_organize_audit_report(report, report_path, quiet=True)

    plan = build_nesting_plan_from_report(report_path, kind="low_value_wrapper", quiet=True)

    assert plan.entries == []
    assert plan.errors[0]["error"] == "target exists"


def test_apply_nesting_plan_requires_review(tmp_path: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    (repeated / "hit.wav").write_bytes(b"audio")
    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    plan_path = tmp_path / "nesting_plan.json"
    write_organize_audit_report(report, report_path, quiet=True)
    build_nesting_plan_from_report(report_path, output_path=plan_path, quiet=True)

    result = apply_nesting_plan(plan_path, require_reviewed=True, dry_run=False, quiet=True)

    assert result.flattened == 0
    assert result.errors
    assert (repeated / "hit.wav").exists()


def test_apply_and_undo_nesting_plan_updates_filesystem_and_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    repeated = root / "Vendor" / "Pack" / "Pack"
    repeated.mkdir(parents=True)
    audio = repeated / "hit.wav"
    audio.write_bytes(b"audio")
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root, pattern="redundant-nesting", depth=4)
    report_path = tmp_path / "nesting_report.json"
    plan_path = tmp_path / "nesting_plan.json"
    log_path = tmp_path / "nesting_log.json"
    write_organize_audit_report(report, report_path, quiet=True)
    build_nesting_plan_from_report(report_path, output_path=plan_path, quiet=True)
    review_organize_report(plan_path, approve_all=True, quiet=True)

    result = apply_nesting_plan(
        plan_path, db_path=tmp_db, log_path=log_path, require_reviewed=True, dry_run=False, quiet=True
    )

    flattened_audio = repeated.parent / "hit.wav"
    assert result.flattened == 1
    assert result.moved == 1
    assert flattened_audio.exists()
    assert not repeated.exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(flattened_audio)]

    undo = undo_nesting_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.undone == 1
    assert audio.exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(audio)]


def test_apply_and_undo_single_child_nesting_plan_updates_filesystem_and_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    child = root / "Wrapper" / "Real Pack"
    child.mkdir(parents=True)
    audio = child / "hit.wav"
    audio.write_bytes(b"audio")
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root, pattern="redundant-nesting", depth=3)
    report_path = tmp_path / "nesting_report.json"
    plan_path = tmp_path / "single_child_plan.json"
    log_path = tmp_path / "single_child_log.json"
    write_organize_audit_report(report, report_path, quiet=True)
    build_nesting_plan_from_report(report_path, kind="single_child_chain", output_path=plan_path, quiet=True)
    review_organize_report(plan_path, approve_all=True, quiet=True)

    result = apply_nesting_plan(
        plan_path, db_path=tmp_db, log_path=log_path, require_reviewed=True, dry_run=False, quiet=True
    )

    flattened_audio = root / "Real Pack" / "hit.wav"
    assert result.flattened == 1
    assert result.moved == 1
    assert flattened_audio.exists()
    assert not (root / "Wrapper").exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(flattened_audio)]

    undo = undo_nesting_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.undone == 1
    assert audio.exists()


def test_apply_and_undo_organize_report_updates_filesystem_and_db(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    source = root / "01 Pack"
    source.mkdir(parents=True)
    audio = source / "sound.wav"
    audio.write_bytes(b"audio")
    conn = get_connection(tmp_db)
    conn.execute(
        """INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(audio), audio.name, audio.stem, audio.suffix, audio.stat().st_size, 0.0, "abc", "2026"),
    )
    conn.commit()
    conn.close()

    report = audit_organization(root)
    report_path = tmp_path / "organize.json"
    log_path = tmp_path / "organize_log.json"
    write_organize_audit_report(report, report_path, quiet=True)
    review_organize_report(report_path, approve_all=True, quiet=True)

    result = apply_organize_report(report_path, db_path=tmp_db, log_path=log_path, require_reviewed=True, quiet=True)

    target_audio = root / "Pack" / "sound.wav"
    assert result.renamed == 1
    assert target_audio.exists()
    assert not audio.exists()
    conn = get_connection(tmp_db)
    rows = conn.execute("SELECT path FROM files").fetchall()
    conn.close()
    assert [row["path"] for row in rows] == [str(target_audio)]

    undo = undo_organize_log(log_path, db_path=tmp_db, dry_run=False, quiet=True)

    assert undo.undone == 1
    assert audio.exists()
