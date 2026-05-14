"""Tests for TUI operation wiring helpers."""

from __future__ import annotations

import os
from pathlib import Path

from sfxworkbench.tui_app import (
    _ACTION_BUTTON_IDS,
    _desktop_open_command,
    _finding_status,
    _latest_metadata_tag_plan,
    _latest_quarantine_dir_from_reports,
    _state_token,
    _tag_text,
)
from sfxworkbench.tui_screens._tabs import TAB_REGISTRY


def test_tui_operation_buttons_are_registered_for_running_state() -> None:
    # The standalone Approve buttons were rolled into their matching Apply
    # buttons: Apply now auto-approves any pending entries before writing,
    # so the dedicated Approve handlers are no longer wired up.
    expected = {
        "scan-run",
        "files-scan-library",
        "scan-full-audit",
        "clean-preview",
        "clean-apply",
        "dedupe-build",
        "dedupe-apply",
        "pack-audit",
        "pack-plan",
        "pack-apply",
        "organize-rename-preview",
        "organize-rename-apply",
        "organize-rename-undo",
        "organize-audit",
        "organize-apply",
        "organize-undo",
        "organize-nesting-audit",
        "organize-nesting-plan",
        "organize-nesting-apply",
        "organize-nesting-undo",
        "metadata-audit",
        "metadata-plan",
        "metadata-plan-synonyms",
        "metadata-apply",
        "metadata-sidecar",
        "metadata-write-apply",
        "metadata-write-undo",
        "quarantine-reveal",
        "delete-plan",
        "delete-apply",
    }

    assert expected == _ACTION_BUTTON_IDS


def test_tui_tab_registry_places_files_between_metadata_and_history() -> None:
    assert [spec.key for spec in TAB_REGISTRY] == [
        "scan",
        "clean",
        "dedupe",
        "metadata",
        "files",
        "history",
    ]


def test_feature_tabs_no_longer_embed_history_tables() -> None:
    repo_root = Path(__file__).parents[1]
    tab_paths = [
        repo_root / "sfxworkbench" / "tui_screens" / "scan_tab.py",
        repo_root / "sfxworkbench" / "tui_screens" / "clean_tab.py",
        repo_root / "sfxworkbench" / "tui_screens" / "dedupe_tab.py",
        repo_root / "sfxworkbench" / "tui_screens" / "metadata_tab.py",
        repo_root / "sfxworkbench" / "tui_screens" / "files_tab.py",
    ]

    for tab_path in tab_paths:
        text = tab_path.read_text()
        assert "reports-table" not in text
        assert "report-detail-table" not in text
        assert "_titled_table_pair" not in text


def test_top_meta_group_precedes_tabs() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    assert app_source.index('with Vertical(id="meta-status-group")') < app_source.index(
        "yield Tabs(*(Tab(label, id=key) for key, label in _FEATURES)"
    )
    assert app_source.index('id="library-path-input"') < app_source.index('id="status-strip"')
    assert app_source.index("yield Tabs(*(Tab(label, id=key) for key, label in _FEATURES)") < app_source.index(
        'id="operation-row"'
    )
    assert 'yield Static(title, classes="page-title")' not in app_source
    assert '("library: ", "bold")' not in app_source
    assert '"  reports: "' in app_source

    status_strip = app_source[
        app_source.index("def _fill_status_strip") : app_source.index("def _fill_operation_strip")
    ]
    assert status_strip.index("for index, page in enumerate(pages):") < status_strip.index('"  reports: "')


def test_tab_hotkeys_are_hidden_from_footer() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    for action in ("focus_scan", "focus_clean", "focus_dedupe", "focus_metadata", "focus_files", "focus_history"):
        assert f'"{action}"' in app_source
    assert app_source.count("show=False") >= 6


def test_advanced_actions_moved_to_metadata_and_files_tabs() -> None:
    repo_root = Path(__file__).parents[1]
    metadata_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_tab.py").read_text()
    files_text = (repo_root / "sfxworkbench" / "tui_screens" / "files_tab.py").read_text()
    registry_text = (repo_root / "sfxworkbench" / "tui_screens" / "_tabs.py").read_text()

    # ``metadata-apply`` now covers what was the old DB apply + the standalone
    # Plan Embedded Metadata button (chained into one click).
    assert "metadata-apply" in metadata_text
    assert "metadata-write-apply" in metadata_text
    assert "delete-plan" in files_text
    assert "delete-apply" in files_text
    assert "advanced_tab" not in registry_text


def test_metadata_review_navigation_buttons_are_visible() -> None:
    repo_root = Path(__file__).parents[1]
    metadata_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_tab.py").read_text()
    app_text = (repo_root / "sfxworkbench" / "tui_app.py").read_text()

    for button_id in ("metadata-review-open", "metadata-page-prev", "metadata-page-next", "metadata-page-random"):
        assert button_id in metadata_text
        assert button_id in app_text

    # The redundant filter Input was retired; the review/paging buttons now
    # sit directly above the prioritized-files table.
    assert 'id="metadata-search"' not in metadata_text
    assert metadata_text.index('"metadata-page-random"') < metadata_text.index('"metadata-rows-table"')
    assert "Source symbols: # filename" in metadata_text


def test_tui_popup_open_actions_are_single_instance_guards() -> None:
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    assert "def _screen_open" in app_text
    assert "def _push_unique_screen" in app_text
    assert '_push_unique_screen("command-palette"' in app_text
    assert 'if self._screen_open("metadata-review")' in app_text
    assert '"confirm-action"' in app_text
    assert app_text.index('if self._screen_open("metadata-review")') < app_text.index(
        "build_metadata_review_screen(plan_path"
    )


def test_metadata_review_uses_canonical_metadata_tag_plan(tmp_path: Path) -> None:
    canonical = tmp_path / "metadata_tag_plan.json"
    fallback = tmp_path / "tag_plan_newer.json"
    canonical.write_text('{"entries": []}')
    fallback.write_text('{"entries": []}')

    assert _latest_metadata_tag_plan(tmp_path) == canonical

    canonical.unlink()
    assert _latest_metadata_tag_plan(tmp_path) == fallback


def test_tui_popup_factories_expose_unique_keys(tmp_path: Path, tmp_db: Path) -> None:
    import importlib.util

    if importlib.util.find_spec("textual") is None:
        import pytest

        pytest.skip("Textual is not installed; install the `tui` extra to exercise this test.")

    from sfxworkbench.tui_screens.command_palette import build_command_palette
    from sfxworkbench.tui_screens.confirm_action import build_confirm_action_screen
    from sfxworkbench.tui_screens.metadata_review import build_metadata_review_screen

    assert build_command_palette({}).POPUP_KEY == "command-palette"
    assert build_confirm_action_screen("Confirm", "Continue?").POPUP_KEY == "confirm-action"
    assert build_metadata_review_screen(tmp_path / "missing_plan.json", db_path=tmp_db).POPUP_KEY == "metadata-review"


def test_feature_findings_render_before_action_buttons() -> None:
    repo_root = Path(__file__).parents[1]
    tab_to_finding = {
        "scan_tab.py": "scan-findings-table",
        "clean_tab.py": "clean-findings-table",
        "dedupe_tab.py": "dedupe-findings-table",
        "metadata_tab.py": "metadata-findings-table",
    }

    for tab_name, finding_id in tab_to_finding.items():
        text = (repo_root / "sfxworkbench" / "tui_screens" / tab_name).read_text()
        assert text.index("_page_header(KEY)") < text.index(f'id="{finding_id}"')
        assert text.index(f'id="{finding_id}"') < text.index("_button_row(")


def test_tui_cancelled_state_has_visible_token() -> None:
    assert "cancelled" in _state_token("cancelled").plain


def test_tui_zero_count_review_states_display_clear() -> None:
    assert _finding_status("review", 0) == "clear"
    assert _finding_status("warning", 0) == "clear"
    assert _finding_status("review", 2) == "review"
    assert _finding_status("info", 0) == "info"


def test_tag_text_uses_symbols_not_status_or_source_words() -> None:
    text = _tag_text("Crowd Chatter", "description", status="pending", source="group")

    assert "Crowd Chatter" in text.plain
    assert "pending" not in text.plain
    assert "group" not in text.plain
    assert "[" not in text.plain


def test_desktop_open_command_reveals_via_windows_explorer() -> None:
    target = Path("C:/Users/Matt/Sounds/hit.wav")

    assert _desktop_open_command(target, reveal=True, platform="win32") == ["explorer", f"/select,{target}"]


def test_desktop_open_command_reveals_via_macos_open() -> None:
    target = Path("/Users/matt/Sounds/hit.wav")

    assert _desktop_open_command(target, reveal=True, platform="darwin") == ["open", "-R", str(target)]


def test_desktop_open_command_reveals_via_xdg_open() -> None:
    target = Path("/home/matt/Sounds/hit.wav")

    def fake_which(name: str) -> str | None:
        assert name == "xdg-open"
        return "/usr/bin/xdg-open"

    assert _desktop_open_command(target, reveal=True, platform="linux", which=fake_which) == [
        "/usr/bin/xdg-open",
        str(target.parent),
    ]


def test_desktop_open_command_reveal_reports_no_linux_opener() -> None:
    target = Path("/home/matt/Sounds/hit.wav")
    assert _desktop_open_command(target, reveal=True, platform="linux", which=lambda _: None) == []


def test_audition_uses_afplay_on_macos() -> None:
    """Audition (non-reveal) routes through a CLI audio player to bypass
    LaunchServices — otherwise ``.wav`` lands on Music.app on macOS.
    """
    target = Path("/Users/matt/Sounds/hit.wav")

    assert _desktop_open_command(target, platform="darwin") == ["afplay", str(target)]


def test_audition_uses_powershell_soundplayer_on_windows() -> None:
    target = Path("C:/Users/Matt/Sounds/hit.wav")

    command = _desktop_open_command(target, platform="win32")
    assert command[0] == "powershell"
    assert "-Command" in command
    assert str(target) in command[-1]


def test_audition_prefers_paplay_then_aplay_then_sox_play_on_linux() -> None:
    """Linux probes for audio players in preference order. ``paplay`` (Pulse)
    is preferred since it works on most modern desktops; ``aplay`` (ALSA)
    is the next fallback; ``play`` (sox) closes out for systems without
    either system audio stack installed.
    """
    target = Path("/home/matt/Sounds/hit.wav")

    def only(found: str) -> object:
        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name == found else None

        return fake_which

    assert _desktop_open_command(target, platform="linux", which=only("paplay")) == [
        "/usr/bin/paplay",
        str(target),
    ]
    assert _desktop_open_command(target, platform="linux", which=only("aplay")) == [
        "/usr/bin/aplay",
        str(target),
    ]
    assert _desktop_open_command(target, platform="linux", which=only("play")) == [
        "/usr/bin/play",
        str(target),
    ]


def test_audition_reports_no_linux_player() -> None:
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
