"""Tests for the command palette's filter/label logic (Tier 3.9)."""

from __future__ import annotations

from sfxworkbench.tui_screens.command_palette import filter_commands, label_for


def test_label_for_uses_lookup_first() -> None:
    assert label_for("scan-run") == "Scan library"
    assert label_for("metadata-write-apply") == "Write metadata to files"


def test_label_for_falls_back_to_title_case() -> None:
    assert label_for("custom-action-id") == "Custom Action Id"


def test_filter_commands_substring_match_is_case_insensitive() -> None:
    matches = filter_commands("scan", ["scan-run", "dedupe-build", "scan-full-audit"])
    paths = [pair[0] for pair in matches]
    assert "scan-run" in paths
    assert "scan-full-audit" in paths
    assert "dedupe-build" not in paths


def test_filter_commands_matches_by_button_id_too() -> None:
    """Users may search by the underlying button id, not just the label."""
    matches = filter_commands("nesting", ["organize-nesting-plan", "dedupe-build"])
    assert any(pair[0] == "organize-nesting-plan" for pair in matches)


def test_filter_commands_empty_returns_everything_sorted() -> None:
    ids = ["scan-run", "dedupe-build", "clean-preview"]
    matches = filter_commands("", ids)
    labels = [pair[1] for pair in matches]
    assert labels == sorted(labels)
    assert len(matches) == len(ids)


def test_filter_commands_strips_whitespace_in_query() -> None:
    assert filter_commands("  scan  ", ["scan-run", "dedupe-build"]) == [("scan-run", "Scan library")]
