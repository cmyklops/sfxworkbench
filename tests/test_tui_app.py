"""Tests for TUI operation wiring helpers."""

from __future__ import annotations

import os
from pathlib import Path

from sfxworkbench.tui_app import (
    _ACTION_BUTTON_IDS,
    _desktop_open_command,
    _finding_status,
    _latest_quarantine_dir_from_reports,
    _state_token,
)


def test_tui_operation_buttons_are_registered_for_running_state() -> None:
    expected = {
        "scan-run",
        "files-scan-library",
        "scan-full-audit",
        "clean-preview",
        "clean-apply",
        "dedupe-build",
        "dedupe-approve",
        "dedupe-apply",
        "pack-audit",
        "pack-plan",
        "pack-approve",
        "pack-apply",
        "organize-rename-preview",
        "organize-rename-apply",
        "organize-rename-undo",
        "organize-audit",
        "organize-approve",
        "organize-apply",
        "organize-undo",
        "organize-nesting-audit",
        "organize-nesting-plan",
        "organize-nesting-approve",
        "organize-nesting-apply",
        "organize-nesting-undo",
        "metadata-audit",
        "metadata-plan",
        "metadata-plan-synonyms",
        "metadata-approve",
        "metadata-apply",
        "metadata-sidecar",
        "metadata-write-plan",
        "metadata-write-approve",
        "metadata-write-apply",
        "metadata-write-undo",
        "quarantine-reveal",
        "delete-plan",
        "delete-approve",
        "delete-apply",
    }

    assert expected == _ACTION_BUTTON_IDS


def test_tui_cancelled_state_has_visible_token() -> None:
    assert "cancelled" in _state_token("cancelled").plain


def test_tui_zero_count_review_states_display_clear() -> None:
    assert _finding_status("review", 0) == "clear"
    assert _finding_status("warning", 0) == "clear"
    assert _finding_status("review", 2) == "review"
    assert _finding_status("info", 0) == "info"


def test_desktop_open_command_uses_windows_explorer() -> None:
    target = Path("C:/Users/Matt/Sounds/hit.wav")

    assert _desktop_open_command(target, platform="win32") == ["explorer", str(target)]
    assert _desktop_open_command(target, reveal=True, platform="win32") == ["explorer", f"/select,{target}"]


def test_desktop_open_command_uses_macos_open() -> None:
    target = Path("/Users/matt/Sounds/hit.wav")

    assert _desktop_open_command(target, platform="darwin") == ["open", str(target)]
    assert _desktop_open_command(target, reveal=True, platform="darwin") == ["open", "-R", str(target)]


def test_desktop_open_command_uses_xdg_open_when_available() -> None:
    target = Path("/home/matt/Sounds/hit.wav")

    def fake_which(name: str) -> str | None:
        assert name == "xdg-open"
        return "/usr/bin/xdg-open"

    assert _desktop_open_command(target, platform="linux", which=fake_which) == ["/usr/bin/xdg-open", str(target)]
    assert _desktop_open_command(target, reveal=True, platform="linux", which=fake_which) == [
        "/usr/bin/xdg-open",
        str(target.parent),
    ]


def test_desktop_open_command_reports_no_linux_opener() -> None:
    target = Path("/home/matt/Sounds/hit.wav")

    assert _desktop_open_command(target, platform="linux", which=lambda _: None) == []


def test_tui_quarantine_reveal_finds_legacy_quarantine_folder(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    legacy = reports / "wavwarden_quarantine_20260508_044220"
    current = reports / "sfxworkbench_quarantine_20260512_120000"
    legacy.mkdir(parents=True)
    current.mkdir()

    legacy_time = current.stat().st_mtime + 10
    legacy.touch()
    current.touch()
    os.utime(legacy, (legacy_time, legacy_time))

    assert _latest_quarantine_dir_from_reports([reports]) == legacy
