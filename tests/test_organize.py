"""Tests for folder organization previews."""

from pathlib import Path

from wavwarden.organize import audit_organization, write_organize_audit_report


def test_organize_audit_strips_obvious_top_level_sort_prefixes(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    for name in [
        "01 - Ghosthack - Ultimate Foley Sounds",
        "01 Ancient_Game",
        "1 Boom TRAX",
        "1. SoundMorph - Energy",
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
        "00  SoundMorph - Sinematic 2": "SoundMorph - Sinematic 2",
    }
    assert report.summary.directories_scanned == 7
    assert report.summary.planned == 5
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


def test_organize_audit_rejects_unknown_pattern(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()

    try:
        audit_organization(root, pattern="unknown")
    except ValueError as e:
        assert "strip-leading-numbers" in str(e)
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
