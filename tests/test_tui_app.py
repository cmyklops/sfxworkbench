"""Tests for TUI operation wiring helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sfxworkbench.desktop import DesktopIntegration
from sfxworkbench.tui_app import (
    _ACTION_BUTTON_IDS,
    ButtonLockSnapshot,
    _action_result_table_rows,
    _button_flow_rows,
    _button_lock_state,
    _clean_preview_table_rows,
    _cleanup_preview_table_rows,
    _cleanup_preview_title,
    _desktop_open_command,
    _finding_status,
    _fmt_finding_count,
    _fmt_indexed_size,
    _format_duration,
    _latest_clean_preview_details,
    _latest_cleanup_preview_details,
    _latest_metadata_tag_plan,
    _latest_quarantine_dir_from_reports,
    _progress_eta_label,
    _progress_phase_label,
    _progress_rate_label,
    _progress_unit,
    _quarantine_dir_template,
    _state_token,
    _tag_text,
    _TuiInstanceLock,
)
from sfxworkbench.tui_lock import process_is_running
from sfxworkbench.tui_screens._tabs import TAB_REGISTRY


def test_tui_size_formatting_uses_tb_for_large_totals() -> None:
    assert _fmt_indexed_size(999.9) == "999.9 GB"
    assert _fmt_indexed_size(1000.0) == "1.0 TB"
    assert _fmt_finding_count("Wasted size", 1024**4) == "1.0 TB"


def test_tui_operation_buttons_are_registered_for_running_state() -> None:
    # The standalone Approve buttons were rolled into their matching Apply
    # buttons: Apply now auto-approves any pending entries before writing,
    # so the dedicated Approve handlers are no longer wired up.
    expected = {
        "scan-run",
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
        "metadata-apply",
        "metadata-sidecar",
        "metadata-write-apply",
        "metadata-write-undo",
        "quarantine-reveal",
        "delete-plan",
        "delete-apply",
    }

    assert expected == _ACTION_BUTTON_IDS


def test_scan_tab_uses_quick_index_label() -> None:
    scan_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_screens" / "scan_tab.py").read_text()
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    assert '("Quick Index", "scan-run")' in scan_text
    assert '"Quick Index"' in app_text
    assert '"Scan Library"' not in scan_text


def test_tui_buttons_avoid_unicode_border_glyphs() -> None:
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()
    button_block = app_text[app_text.index("Button {") : app_text.index("#library-controls Button")]

    assert "border: none;" in button_block


def test_progress_helpers_show_phase_rate_and_eta() -> None:
    assert _progress_phase_label("scanning") == "Scanning"
    assert _progress_phase_label("metadata_write") == "Metadata Write"
    assert _progress_unit("scanning") == "files"
    assert _progress_unit("applying") == "items"
    assert _format_duration(75) == "1m 15s"
    assert _progress_rate_label(500, 10, unit="files") == "50 files/s"
    assert _progress_eta_label(500, 1000, 10) == "ETA 10s"


def test_tui_button_locks_apply_until_required_plan_exists(tmp_path: Path, tmp_db: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()

    locked = _button_lock_state(
        "dedupe-apply",
        library_path=tmp_path,
        report_dir=report_dir,
        db_path=tmp_db,
    )
    assert locked.locked
    assert "dedupe plan" in locked.reason

    (report_dir / "dedupe_plan.json").write_text('{"groups": [{"id": 1}]}', encoding="utf-8")

    unlocked = _button_lock_state(
        "dedupe-apply",
        library_path=tmp_path,
        report_dir=report_dir,
        db_path=tmp_db,
    )
    assert not unlocked.locked


def test_tui_button_locks_file_actions_when_empty(tmp_path: Path, tmp_db: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()

    file_lock = _button_lock_state(
        "files-open-file",
        library_path=tmp_path,
        report_dir=report_dir,
        db_path=tmp_db,
        selected_file_available=False,
    )

    assert file_lock.locked
    assert "indexed file" in file_lock.reason


def test_tui_button_locks_permanent_delete_until_quarantine_exists(tmp_path: Path, tmp_db: Path) -> None:
    report_dir = tmp_path / "reports"
    log_dir = report_dir / "apply_logs"
    log_dir.mkdir(parents=True)

    locked = _button_lock_state(
        "delete-plan",
        library_path=tmp_path,
        report_dir=report_dir,
        db_path=tmp_db,
    )
    assert locked.locked

    (log_dir / "dedupe_quarantine_log_20260515_120000.json").write_text(
        '{"entries": [{"path": "/old.wav", "quarantine_path": "/quarantine/old.wav"}]}',
        encoding="utf-8",
    )

    unlocked = _button_lock_state(
        "delete-plan",
        library_path=tmp_path,
        report_dir=report_dir,
        db_path=tmp_db,
    )
    assert not unlocked.locked


def test_tui_button_flow_wraps_by_available_width() -> None:
    specs = (
        ("Preview Junk", "clean-preview"),
        ("Apply Junk Cleanup", "clean-apply", "warning"),
        ("Preview Name Cleanup", "organize-rename-preview"),
        ("Apply Name Cleanup", "organize-rename-apply", "warning"),
    )

    narrow = _button_flow_rows(specs, available_width=45)
    wide = _button_flow_rows(specs, available_width=160)

    assert len(narrow) > 1
    assert wide == [specs]


def test_clean_preview_table_rows_show_only_kind_and_relative_path(tmp_path: Path) -> None:
    library = tmp_path / "library"
    details = {
        "removed_files": [str(library / "Pack" / "._Hit.wav")],
        "removed_dirs": [str(library / "Pack" / "_wfCache")],
    }

    rows, remaining = _clean_preview_table_rows(details, library_path=library)

    assert rows == [("file", str(Path("Pack") / "._Hit.wav")), ("folder", f"{Path('Pack') / '_wfCache'}/")]
    assert remaining == 0


def test_cleanup_preview_table_rows_follow_rename_preview(tmp_path: Path) -> None:
    library = tmp_path / "library"
    details = {
        "entries": [
            {
                "old_path": str(library / "Bad Names" / " bad hit.wav"),
                "new_path": str(library / "Bad Names" / "bad hit.wav"),
            }
        ]
    }

    rows, remaining = _cleanup_preview_table_rows("rename_preview", details, library_path=library)

    assert _cleanup_preview_title("rename_preview") == "Previewed Name Cleanup"
    assert rows == [("rename", f"{Path('Bad Names') / ' bad hit.wav'} -> {Path('Bad Names') / 'bad hit.wav'}")]
    assert remaining == 0


def test_cleanup_result_rows_surface_action_issues() -> None:
    from sfxworkbench.tui_actions import ActionResult

    result = ActionResult(
        action="organize_nesting_apply",
        status="applied",
        message="Flattened 1 nested folder(s), moved 1 path(s), skipped 1 issue(s).",
        output_path="reports/apply_logs/nesting_log_20260517.json",
        errors=("target exists",),
        details={"flattened": 1, "moved": 1},
    )

    rows, remaining = _action_result_table_rows(result)

    assert _cleanup_preview_title("organize_nesting_apply") == "Nesting Apply Results"
    assert ("status", result.message) in rows
    assert ("summary", "flattened 1, moved 1") in rows
    assert ("issue", "target exists") in rows
    assert remaining == 0


def test_latest_cleanup_preview_uses_most_recent_preview_file(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    clean_preview = report_dir / "clean_preview_20260515_120000.json"
    rename_preview = report_dir / "portable_rename_plan.json"
    clean_preview.write_text(json.dumps({"dry_run": True, "removed_files": ["._Hit.wav"]}), encoding="utf-8")
    rename_preview.write_text(
        json.dumps({"entries": [{"old_path": "bad.wav", "new_path": "good.wav"}]}), encoding="utf-8"
    )
    os.utime(clean_preview, (100.0, 100.0))
    os.utime(rename_preview, (200.0, 200.0))

    action, details, stale = _latest_cleanup_preview_details([report_dir])

    assert action == "rename_preview"
    assert details is not None
    assert details["entries"]
    assert stale is False


def test_latest_clean_preview_ignores_preview_after_newer_apply(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    preview = report_dir / "clean_preview_20260515_120000.json"
    apply = report_dir / "clean_apply_20260515_120100.json"
    preview.write_text(json.dumps({"dry_run": True, "removed_files": ["._Hit.wav"]}), encoding="utf-8")
    apply.write_text(json.dumps({"dry_run": False, "removed_files": ["._Hit.wav"]}), encoding="utf-8")
    os.utime(preview, (100.0, 100.0))
    os.utime(apply, (200.0, 200.0))

    details, stale = _latest_clean_preview_details([report_dir])

    assert details is None
    assert stale is True


def test_tui_button_locks_can_use_precomputed_snapshot(tmp_path: Path, tmp_db: Path) -> None:
    snapshot = ButtonLockSnapshot(
        has_library=True,
        has_indexed_files=True,
        accepted_tag_count=0,
        has_dedupe_plan=True,
        has_pack_report=False,
        has_pack_plan=False,
        has_rename_plan=False,
        has_rename_log=False,
        has_organize_report=False,
        has_organize_log=False,
        has_nesting_report=False,
        has_nesting_plan=False,
        has_nesting_log=False,
        has_metadata_tag_plan=False,
        has_metadata_write_plan=False,
        has_metadata_write_log=False,
        has_quarantine=False,
        has_delete_plan=False,
    )

    lock = _button_lock_state(
        "dedupe-apply",
        library_path=tmp_path / "missing",
        report_dir=tmp_path / "missing-reports",
        db_path=tmp_db,
        snapshot=snapshot,
    )

    assert not lock.locked


def test_tui_instance_lock_blocks_second_instance(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    db_path.touch()
    lock = _TuiInstanceLock(db_path)
    lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            _TuiInstanceLock(db_path).acquire()
    finally:
        lock.release()

    assert not lock.lock_path.exists()


def test_tui_instance_lock_recovers_stale_lock(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    db_path.touch()
    lock = _TuiInstanceLock(db_path)
    lock.lock_path.write_text("\ufeffpid=99999999\n", encoding="utf-8")

    lock.acquire()
    try:
        assert f"pid={os.getpid()}" in lock.lock_path.read_text(encoding="utf-8")
    finally:
        lock.release()

    assert not lock.lock_path.exists()


def test_tui_instance_lock_uses_injected_process_checker(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    db_path.touch()
    lock = _TuiInstanceLock(db_path, process_checker=lambda pid: pid == 1234)
    lock.lock_path.write_text("pid=1234\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="pid 1234"):
        lock.acquire()


def test_windows_process_check_uses_kernel_wait_state() -> None:
    class Kernel32:
        def __init__(self, wait_result: int) -> None:
            self.wait_result = wait_result
            self.closed: list[int] = []

        def OpenProcess(self, _access: int, _inherit: bool, pid: int) -> int:
            return pid

        def WaitForSingleObject(self, _handle: int, _timeout: int) -> int:
            return self.wait_result

        def CloseHandle(self, handle: int) -> None:
            self.closed.append(handle)

    running = Kernel32(0x00000102)
    stopped = Kernel32(0)

    assert process_is_running(4242, platform="win32", kernel32=running)
    assert running.closed == [4242]
    assert not process_is_running(4242, platform="win32", kernel32=stopped)
    assert stopped.closed == [4242]


def test_tui_tab_registry_places_files_between_metadata_and_history() -> None:
    assert [spec.key for spec in TAB_REGISTRY] == [
        "start",
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
        repo_root / "sfxworkbench" / "tui_screens" / "start_tab.py",
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
    assert 'yield Static("Library", classes="control-label")' in app_source
    assert "Paste or drag a folder path" in app_source
    assert 'yield Button("Browse...", id="library-browse")' in app_source
    assert 'yield Button("Use Path", id="set-library-path")' not in app_source
    assert 'yield Button("Use Last Scan", id="use-indexed-root")' in app_source
    assert "def _fill_library_status" in app_source
    assert "sfxworkbench_quarantine" in app_source
    assert "YYYYMMDD_HHMMSS" in app_source
    assert 'yield Button("Cancel", id="cancel-action", disabled=True)' in app_source
    assert app_source.index("yield Tabs(*(Tab(label, id=key) for key, label in _FEATURES)") < app_source.index(
        'id="operation-row"'
    )
    assert 'yield Static(title, classes="page-title")' not in app_source
    assert '("library: ", "bold")' not in app_source
    assert '"  reports dir: "' in app_source
    assert '"  indexed size: "' in app_source
    assert "metric_labels" in app_source

    status_strip = app_source[
        app_source.index("def _fill_status_strip") : app_source.index("def _fill_operation_strip")
    ]
    assert status_strip.index("for index, page in enumerate(pages):") < status_strip.index('"  reports dir: "')


def test_worker_completion_clears_running_strip_before_post_action_bookkeeping() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()
    finish_block = app_source[app_source.index("def _finish_running_action") : app_source.index("def _run_action")]

    assert "self._last_action = result" in finish_block
    assert finish_block.index("self._fill_operation_strip()") < finish_block.index("self.set_timer")
    assert "self.set_timer(0.01, lambda: self._run_action(result, job_id=job_id))" in finish_block


def test_tui_mount_restores_previous_session_before_initial_load() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()
    on_mount_source = app_source[app_source.index("def on_mount") : app_source.index("def _start_initial_load")]

    assert "self._restore_previous_session_state()" in on_mount_source
    assert on_mount_source.index("self._restore_previous_session_state()") < on_mount_source.index(
        "self._start_artifact_sync"
    )
    assert "interrupt_running_jobs(db_path)" in app_source
    assert "read_latest_action_history(self._history_report_paths())" in app_source


def test_keybind_footer_is_hidden_on_startup() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    textual_import = app_source[
        app_source.index("from textual.widgets import") : app_source.index("from textual.worker import")
    ]
    assert "Footer" not in textual_import
    assert "yield Footer()" not in app_source
    assert 'id="mini-footer"' not in app_source
    assert "_FOOTER_TEXT" not in app_source


def test_windows_tui_hides_textual_scrollbars() -> None:
    repo_root = Path(__file__).parents[1]
    app_source = (repo_root / "sfxworkbench" / "tui_app.py").read_text()
    review_source = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_review.py").read_text()

    assert 'if sys.platform == "win32":' in app_source
    assert "CSS +=" in app_source
    assert "VerticalScroll," in app_source
    assert "DataTable {" in app_source
    assert "scrollbar-visibility: hidden;" in app_source
    assert 'if sys.platform == "win32":' in review_source
    assert "DEFAULT_CSS +=" in review_source
    assert "MetadataReviewScreen VerticalScroll," in review_source
    assert "MetadataReviewScreen DataTable {" in review_source
    assert "scrollbar-visibility: hidden;" in review_source


def test_tab_hotkeys_are_hidden_from_binding_discovery() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    for action in (
        "focus_start",
        "focus_scan",
        "focus_clean",
        "focus_dedupe",
        "focus_metadata",
        "focus_files",
        "focus_history",
    ):
        assert f'"{action}"' in app_source
    assert app_source.count("show=False") >= 7


def test_tui_startup_path_does_not_call_heavy_adapters() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    run_tui_prefix = app_source[app_source.index("def run_tui") : app_source.index("try:")]
    on_mount_source = app_source[app_source.index("def on_mount") : app_source.index("def _start_initial_load")]
    finish_source = app_source[app_source.index("def _finish_initial_load") : app_source.index("def on_resize")]

    for heavy_call in (
        "report_search_paths(",
        "feature_pages(",
        "indexed_library_size_gb(",
        "scan_findings(",
        "review_queues(",
        "discover_plan_files(",
        "list_files(",
        "_refresh(",
    ):
        assert heavy_call not in run_tui_prefix
        assert heavy_call not in on_mount_source
        assert heavy_call not in finish_source

    initial_load_source = app_source[
        app_source.index("def _start_initial_load") : app_source.index("def _finish_initial_load")
    ]
    assert "threading.Thread(target=_load, daemon=True).start()" in initial_load_source


def test_history_tab_uses_artifact_registry_not_json_discovery() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()
    history_source = app_source[
        app_source.index("def _fill_history_impl") : app_source.index("def _fill_action_result")
    ]

    assert "list_artifacts(" in history_source
    assert "discover_plan_files(" not in history_source
    assert "plan_detail_rows(" not in history_source


def test_tui_lazy_mounts_inactive_tab_widgets() -> None:
    app_source = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    compose_source = app_source[app_source.index("def compose") : app_source.index("def _page_widget")]
    assert 'with ContentSwitcher(initial="start-page", id="feature-pages")' in compose_source
    assert 'self._page_widget("start", self._start_page)' in compose_source
    for inactive_key in ("scan", "clean", "dedupe", "metadata", "files", "history"):
        assert f'self._page_widget("{inactive_key}"' not in compose_source

    assert "def _ensure_page_mounted" in app_source
    assert "switcher.mount(self._page_widget(key, factory))" in app_source
    assert "mounted_now = self._ensure_page_mounted(tab_id)" in app_source


def test_advanced_actions_moved_to_metadata_and_files_tabs() -> None:
    repo_root = Path(__file__).parents[1]
    metadata_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_tab.py").read_text()
    files_text = (repo_root / "sfxworkbench" / "tui_screens" / "files_tab.py").read_text()
    registry_text = (repo_root / "sfxworkbench" / "tui_screens" / "_tabs.py").read_text()

    # ``metadata-apply`` accepts DB tags and prepares the embedded write plan;
    # the actual file-write remains a separate confirmed action.
    assert "metadata-apply" in metadata_text
    assert "Accept Tags & Prepare Write" in metadata_text
    assert "metadata-write-apply" in metadata_text
    assert "Write Metadata to Files" in metadata_text
    assert '("Undo File Writes", "metadata-write-undo", "primary")' in metadata_text
    assert '("Save Tags", "metadata-sidecar")' not in metadata_text
    assert "metadata-page-prev" not in metadata_text
    assert "metadata-page-next" not in metadata_text
    assert "metadata-page-random" not in metadata_text
    assert "delete-plan" in files_text
    assert "delete-apply" in files_text
    assert "advanced_tab" not in registry_text


def test_undo_buttons_use_primary_variant() -> None:
    repo_root = Path(__file__).parents[1]
    clean_text = (repo_root / "sfxworkbench" / "tui_screens" / "clean_tab.py").read_text()
    metadata_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_tab.py").read_text()

    for button_id in (
        "organize-rename-undo",
        "organize-undo",
        "organize-nesting-undo",
    ):
        assert f'"{button_id}", "primary"' in clean_text
    assert '"metadata-write-undo", "primary"' in metadata_text


def test_cleanup_workflow_labels_do_not_expand_rows() -> None:
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()
    label_block = app_text[app_text.index(".cleanup-workflow-label {") : app_text.index(".cleanup-workflow-title {")]

    assert "height: auto;" in label_block


def test_metadata_paging_buttons_live_only_in_review_screen() -> None:
    repo_root = Path(__file__).parents[1]
    app_text = (repo_root / "sfxworkbench" / "tui_app.py").read_text()
    metadata_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_tab.py").read_text()
    review_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_review.py").read_text()

    assert "metadata-page-prev" not in app_text
    assert "metadata-page-next" not in app_text
    assert "metadata-page-random" not in app_text
    assert "metadata-page-prev" not in metadata_text
    assert "metadata-page-next" not in metadata_text
    assert "metadata-page-random" not in metadata_text
    assert "review-page-prev" in review_text
    assert "review-page-next" in review_text
    assert "review-page-random" in review_text


def test_metadata_review_navigation_buttons_are_visible() -> None:
    repo_root = Path(__file__).parents[1]
    metadata_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_tab.py").read_text()
    review_text = (repo_root / "sfxworkbench" / "tui_screens" / "metadata_review.py").read_text()

    for button_id in ("metadata-review-open",):
        assert button_id in metadata_text
    for button_id in ("review-page-prev", "review-page-next", "review-page-random"):
        assert button_id in review_text

    # The redundant filter Input and paging buttons stay out of the main
    # Metadata tab; page navigation belongs to the dedicated review screen.
    assert 'id="metadata-search"' not in metadata_text
    assert "metadata-page-" not in metadata_text
    assert "Source symbols: # filename" in metadata_text


def test_generate_suggestions_includes_synonyms_by_default_from_tui() -> None:
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()
    metadata_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_screens" / "metadata_tab.py").read_text()

    handler = app_text[app_text.index('handlers["metadata-plan"]') - 300 : app_text.index('handlers["metadata-plan"]')]
    assert "include_synonyms=True" in handler
    assert "cancel_requested=cancel" in handler
    assert "metadata-plan-synonyms" not in app_text
    assert "Generate Synonyms" not in metadata_text


def test_tui_popup_open_actions_are_single_instance_guards() -> None:
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    assert "def _screen_open" in app_text
    assert "def _push_unique_screen" in app_text
    assert '_push_unique_screen("command-palette"' in app_text
    assert '"action-issues"' in app_text
    assert 'if self._screen_open("metadata-review")' in app_text
    assert '"confirm-action"' in app_text
    assert app_text.index('if self._screen_open("metadata-review")') < app_text.index(
        "build_metadata_review_screen(plan_path"
    )


def test_tui_action_issues_are_reviewable_after_completion() -> None:
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text(encoding="utf-8")
    issues_text = (
        Path(__file__).parents[1] / "sfxworkbench" / "tui_screens" / "action_issues.py"
    ).read_text(encoding="utf-8")
    run_action_source = app_text[app_text.index("def _run_action") : app_text.index("def _refresh")]
    operation_source = app_text[app_text.index("def _fill_operation_strip") : app_text.index("def _progress_line")]

    assert "self._last_action_history_path = history_path" in run_action_source
    assert "self._maybe_show_action_issues(self._last_action, history_path)" in run_action_source
    assert 'choice == "history"' in app_text
    assert "self._open_action_history(history_path)" in app_text
    assert "issue(s) recorded" in operation_source
    assert 'issue_class = "issue-error" if self._status == "error" else "issue-warning"' in issues_text
    assert issues_text.index('Button("Review History", id="action-issues-review")') < issues_text.index(
        'Button("Dismiss", id="action-issues-dismiss", variant="warning")'
    )
    assert "#ff7b72" in issues_text
    assert "#d29922" in issues_text


def test_dedupe_table_surfaces_apply_issues_above_live_groups() -> None:
    text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_screens" / "dedupe_tab.py").read_text()

    assert 'last_action.action in {"dedupe_apply", "pack_apply"}' in text
    assert "Review History for apply issues." in text
    assert text.index("Review History for apply issues.") < text.index("rows = dedupe_group_rows")


def test_dedupe_table_surfaces_pack_audit_feedback() -> None:
    from sfxworkbench.tui_actions import ActionResult
    from sfxworkbench.tui_screens.dedupe_tab import pack_audit_feedback_row

    result = ActionResult(
        action="pack_audit",
        status="ok",
        message="Pack audit found 0 exact duplicate group(s) and 2 overlap candidate(s).",
        details={
            "summary": {
                "exact_duplicate_groups": 0,
                "overlap_candidates": 2,
                "folders_analyzed": 8,
                "indexed_files_considered": 120,
            }
        },
    )

    row = pack_audit_feedback_row(result)

    assert row == (
        "pack audit",
        "0",
        "2",
        "",
        "",
        "review",
        "Pack audit found 0 exact folder group(s), 2 overlap candidate(s), 8 folder(s), 120 indexed file(s).",
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

    from sfxworkbench.tui_screens.action_issues import build_action_issues_screen
    from sfxworkbench.tui_screens.command_palette import build_command_palette
    from sfxworkbench.tui_screens.confirm_action import build_confirm_action_screen
    from sfxworkbench.tui_screens.metadata_review import build_metadata_review_screen

    assert build_command_palette({}).POPUP_KEY == "command-palette"
    assert build_confirm_action_screen("Confirm", "Continue?").POPUP_KEY == "confirm-action"
    assert (
        build_action_issues_screen(
            action="pack_apply",
            status="applied",
            message="Quarantined 18 pack folder(s).",
            errors=("file does not exist",),
            output_path="reports/apply_logs/pack.json",
        ).POPUP_KEY
        == "action-issues"
    )
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
        finding_index = text.index(f'id="{finding_id}"')
        candidates = [
            text.find("_button_flow(", finding_index),
            text.find("_button_row(", finding_index),
            text.find("workflow_row(", finding_index),
        ]
        button_index = min(index for index in candidates if index >= 0)
        assert finding_index < button_index


def test_large_workbench_tables_get_flexible_height() -> None:
    app_text = (Path(__file__).parents[1] / "sfxworkbench" / "tui_app.py").read_text()

    for table_id in ("#clean-items-table", "#files-table", "#metadata-rows-table"):
        assert table_id in app_text
    flexible_block = app_text[app_text.index("#clean-items-table,") : app_text.index("#scan-findings-table,")]
    assert "height: 1fr;" in flexible_block
    assert "min-height: 18;" in flexible_block


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


def test_desktop_open_command_reveals_windows_paths_with_spaces_apostrophes_and_unc() -> None:
    quoted = Path("C:/Users/Matt/Sound Libraries/Matt's Hits/hit one.wav")
    unc = Path("//Studio NAS/SFX Share/Impacts/hit one.wav")

    assert _desktop_open_command(quoted, reveal=True, platform="win32") == ["explorer", f"/select,{quoted}"]
    assert _desktop_open_command(unc, reveal=True, platform="win32") == ["explorer", f"/select,{unc}"]


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
    target = Path("C:/Users/Matt/Sound Libraries/Matt's hit.wav")

    command = _desktop_open_command(target, platform="win32")
    assert command[0] == "powershell"
    assert "-Command" in command
    assert "Matt''s hit.wav" in command[-1]
    assert str(target) not in command[-1]


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


def test_desktop_choose_directory_uses_windows_folder_picker() -> None:
    calls = []

    class Completed:
        stdout = "C:\\SFX Library"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    selected = DesktopIntegration(platform="win32", run=fake_run).choose_directory(Path("C:/Start"))

    assert selected == Path("C:/SFX Library")
    command, kwargs = calls[0]
    assert command[:3] == ["powershell", "-NoProfile", "-STA"]
    assert "FolderBrowserDialog" in command[-1]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_quarantine_dir_template_names_library_root_destination(tmp_path: Path) -> None:
    root = tmp_path / "library"

    assert _quarantine_dir_template(root) == root / "sfxworkbench_quarantine_YYYYMMDD_HHMMSS"
    assert _quarantine_dir_template(root, kind="pack") == root / "sfxworkbench_quarantine_YYYYMMDD_HHMMSS"


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


def test_tui_quarantine_reveal_finds_log_destination_outside_reports(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    log_dir = reports / "apply_logs"
    log_dir.mkdir(parents=True)
    quarantine = tmp_path / "library" / "sfxworkbench_quarantine_20260516_105918"
    quarantined_file = quarantine / "one.wav"
    quarantined_file.parent.mkdir(parents=True)
    quarantined_file.write_bytes(b"audio")
    (log_dir / "dedupe_quarantine_log_20260516_105918.json").write_text(
        json.dumps({"entries": [{"path": "/old/one.wav", "quarantine_path": str(quarantined_file)}]}),
        encoding="utf-8",
    )

    assert _latest_quarantine_dir_from_reports([reports]) == quarantine


def test_tui_quarantine_reveal_finds_pack_log_folder_destination(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    log_dir = reports / "apply_logs"
    log_dir.mkdir(parents=True)
    quarantine = tmp_path / "library" / "sfxworkbench_quarantine_20260516_105918"
    quarantined_folder = quarantine / "B Pack"
    quarantined_folder.mkdir(parents=True)
    (log_dir / "pack_quarantine_log_20260516_105918.json").write_text(
        json.dumps({"entries": [{"folder_path": "/old/B Pack", "quarantine_path": str(quarantined_folder)}]}),
        encoding="utf-8",
    )

    assert _latest_quarantine_dir_from_reports([reports]) == quarantine
