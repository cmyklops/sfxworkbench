"""Textual alpha operations workbench for sfxworkbench."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from rich.text import Text

from sfxworkbench.db import DEFAULT_DB_PATH
from sfxworkbench.tui_actions import (
    ActionResult,
    apply_dedupe_plan_action,
    apply_delete_plan_action,
    apply_embedded_metadata_action,
    apply_nesting_action,
    apply_organize_action,
    apply_pack_plan_action,
    apply_rename_action,
    apply_tag_plan_action,
    approve_dedupe_plan_action,
    approve_delete_plan_action,
    approve_embedded_metadata_action,
    approve_organize_action,
    approve_pack_plan_action,
    approve_tag_plan_action,
    build_dedupe_plan_action,
    build_delete_plan_action,
    build_embedded_metadata_plan_action,
    build_nesting_plan_action,
    clean_action,
    export_sidecar_action,
    full_audit_action,
    metadata_audit_action,
    operation_report_dir,
    organize_audit_action,
    pack_audit_action,
    pack_plan_action,
    rename_preview_action,
    scan_action,
    tag_plan_action,
    undo_embedded_metadata_action,
    undo_nesting_action,
    undo_organize_action,
    undo_rename_action,
    write_action_history,
)
from sfxworkbench.tui_data import (
    advanced_findings,
    clean_findings,
    dedupe_findings,
    dedupe_group_rows,
    discover_plan_files,
    feature_pages,
    file_detail,
    indexed_library_size_gb,
    library_root,
    list_files,
    metadata_findings,
    metadata_workbench_rows,
    plan_detail_rows,
    preferred_library_path,
    report_search_paths,
    save_library_path,
    scan_findings,
)

_FEATURES: tuple[tuple[str, str], ...] = (
    ("scan", "Scan"),
    ("files", "Files"),
    ("clean", "Declutter"),
    ("dedupe", "Dedupe"),
    ("metadata", "Metadata"),
    ("advanced", "Advanced"),
)

_REPORT_QUERIES = {
    "scan": "audit scan metadata format groups ucs pack",
    "files": "scan metadata",
    "clean": "clean scan_error rename organize nesting",
    "dedupe": "dedupe pack quarantine",
    "metadata": "metadata tag sidecar",
    "advanced": "delete dual_mono metadata_write compare processed",
}

_PAGE_HEADERS = {
    "scan": (
        "Scan",
        "Refresh the SQLite index and generate read-only reports that feed the rest of the workbench.",
    ),
    "files": (
        "Files",
        "Browse indexed files, search filenames, audition audio, and inspect per-file facts.",
    ),
    "clean": (
        "Declutter",
        "Find removable junk, risky names, long paths, and folder-structure cleanup plans before applying changes.",
    ),
    "dedupe": (
        "Dedupe",
        "Review exact duplicate files and overlapping packs before any quarantine action.",
    ),
    "metadata": (
        "Metadata",
        "Compare embedded search fields, proposed DB tags, accepted tags, and file-level evidence in one place.",
    ),
    "advanced": (
        "Advanced",
        "Use guarded workflows that require reviewed plans, logs, safe folders, or external tools.",
    ),
}

_ACTION_BUTTON_IDS = {
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


def _fmt(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if value is None:
        return ""
    return str(value)


def _clip_middle(value: str, *, width: int = 88) -> str:
    if len(value) <= width:
        return value
    half = max(8, (width - 3) // 2)
    return f"{value[:half]}...{value[-half:]}"


def _short_path(path: str | Path, *, width: int = 64) -> str:
    text = str(path)
    home = str(Path.home())
    if text == home:
        text = "~"
    elif text.startswith(home + "/"):
        text = "~/" + text[len(home) + 1 :]
    return _clip_middle(text, width=width)


def _desktop_open_command(
    target: Path,
    *,
    reveal: bool = False,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Return a best-effort desktop file-browser command for the current OS."""
    if platform == "darwin":
        return ["open", "-R", str(target)] if reveal else ["open", str(target)]
    if platform == "win32":
        return ["explorer", f"/select,{target}"] if reveal else ["explorer", str(target)]

    opener = which("xdg-open")
    if opener is None:
        return []
    return [opener, str(target.parent if reveal else target)]


def _state_token(state: str) -> Text:
    tokens = {
        "clear": ("✓ clear", "green"),
        "safe": ("✓ safe", "green"),
        "ok": ("✓ ok", "green"),
        "dry_run": ("· preview", "cyan"),
        "applied": ("✓ applied", "bold cyan"),
        "approved": ("✓ approved", "bold blue"),
        "accepted": ("✓ accepted", "bold blue"),
        "rejected": ("x rejected", "red"),
        "info": ("· info", "dim"),
        "pending": ("! pending", "yellow"),
        "needs review": ("! review", "yellow"),
        "review": ("! review", "yellow"),
        "warning": ("! warning", "yellow"),
        "error": ("! error", "red"),
        "cancelled": ("x cancelled", "yellow"),
        "ready": ("> ready", "cyan"),
        "available": ("> ready", "cyan"),
        "not started": ("○ not started", "dim"),
    }
    text, style = tokens.get(state, (state, ""))
    return Text(text, style=style)


def _finding_status(status: str, count: object) -> str:
    if status in {"info", "safe"}:
        return status
    if isinstance(count, int) and count == 0:
        return "clear"
    return status


_TAG_FIELD_STYLES = {
    "description": "cyan",
    "icmt": "cyan",
    "keywords": "magenta",
    "ikey": "magenta",
    "category": "green",
    "ignr": "green",
    "subcategory": "blue",
    "ucs_category": "yellow",
    "ucs_subcategory": "yellow",
    "title": "white",
    "inam": "white",
    "comment": "dim cyan",
    "isbj": "blue",
}


def _tag_text(value: str, field: str, *, status: str = "", source: str = "") -> Text:
    style = _TAG_FIELD_STYLES.get(field.lower(), "white")
    if status == "pending":
        style = f"bold {style}"
    text = Text(value, style=style)
    suffix_parts = [part for part in (status if status not in {"", "approved"} else "", source) if part]
    if suffix_parts:
        text.append(f" [{' / '.join(suffix_parts)}]", style="dim")
    return text


def _tags_cell(row) -> Text:
    if not row.tag_items:
        return Text("No searchable tags found", style="dim")
    text = Text()
    for index, item in enumerate(row.tag_items):
        if index:
            text.append("  |  ", style="dim")
        text.append_text(
            _tag_text(
                item.value,
                item.field,
                status=item.status if item.source == "plan" else "",
                source=item.evidence_source if item.source == "plan" else "",
            )
        )
    return text


def _feature_query(feature: str) -> str:
    return _REPORT_QUERIES.get(feature, feature)


def _latest_quarantine_dir_from_reports(report_paths: list[Path]) -> Path | None:
    """Return the newest known quarantine folder across current and legacy names."""
    candidates: list[Path] = []
    patterns = (
        "sfxworkbench*_quarantine_*",
        "wavwarden*_quarantine_*",
    )
    for report_path in report_paths:
        if not report_path.exists():
            continue
        for pattern in patterns:
            candidates.extend(path for path in report_path.glob(pattern) if path.is_dir())
    matches = sorted(set(candidates), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _sort_text(value: object) -> str:
    if isinstance(value, Text):
        return value.plain.casefold()
    return str(value or "").casefold()


def _sort_number(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    text = str(value or "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def run_tui(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    config_path: Path | None = None,
    report_paths: list[Path] | None = None,
) -> None:
    """Run the Textual app, importing Textual only for this optional command."""
    initial_library_path = preferred_library_path(db_path)
    initial_report_paths = report_search_paths(
        db_path=db_path,
        report_paths=report_paths,
        library_path=initial_library_path,
    )
    try:
        from textual import events
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.screen import ModalScreen
        from textual.widgets import Button, ContentSwitcher, DataTable, Input, Static, Tab, Tabs
        from textual.worker import Worker, WorkerState

        if sys.platform == "win32":
            LinuxDriver = None
        else:
            from textual.drivers.linux_driver import LinuxDriver
    except ImportError as e:
        raise RuntimeError("Textual is not installed. Install with: uv sync --extra tui --extra dev") from e

    if LinuxDriver is None:
        SfxworkbenchDriver = None
    else:

        class SfxworkbenchDriver(LinuxDriver):
            """Avoid startup capability probes that some terminals render as a stray 'p'."""

            def _query_in_band_window_resize(self) -> None:
                return

            def _request_terminal_sync_mode_support(self) -> None:
                return

    class ConfirmActionScreen(ModalScreen[bool]):
        CSS = """
        ConfirmActionScreen {
            align: center middle;
        }
        #confirm-dialog {
            width: 72;
            max-width: 90%;
            height: auto;
            border: heavy #d29922;
            background: #101923;
            padding: 1 2;
        }
        #confirm-title {
            text-style: bold;
            color: #f8fafc;
            margin-bottom: 1;
        }
        #confirm-message {
            color: #d7dee7;
            margin-bottom: 1;
        }
        #confirm-actions {
            height: auto;
            margin-top: 1;
        }
        """

        def __init__(self, title: str, message: str) -> None:
            super().__init__()
            self._title = title
            self._message = message

        def compose(self) -> ComposeResult:
            with Vertical(id="confirm-dialog"):
                yield Static(self._title, id="confirm-title")
                yield Static(self._message, id="confirm-message")
                with Horizontal(id="confirm-actions"):
                    yield Button("Cancel", id="confirm-cancel")
                    yield Button("Continue", id="confirm-continue", variant="warning")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            self.dismiss(event.button.id == "confirm-continue")

    class SfxworkbenchTui(App):
        theme = "textual-dark"
        CSS = """
        Screen {
            background: #0b1117;
            color: #e6edf3;
        }
        Tabs {
            background: #111a23;
            color: #e6edf3;
        }
        Footer {
            background: #111a23;
            color: #f8fafc;
        }
        #library-controls {
            height: 3;
            padding: 0 1;
            background: #111a23;
        }
        #library-path-input {
            width: 1fr;
            margin-right: 1;
        }
        #status-strip {
            height: 3;
            padding: 0 1;
            background: #0f1720;
            border-bottom: solid #263647;
        }
        #operation-row {
            height: 3;
            background: #101923;
            border-bottom: solid #263647;
        }
        #operation-strip {
            height: 3;
            width: 1fr;
            padding: 0 1;
            background: #101923;
            color: #d7dee7;
        }
        #cancel-action {
            margin: 0 1 0 0;
            min-width: 16;
        }
        .page {
            padding: 1;
        }
        #loading-page {
            align: center middle;
        }
        #loading-title {
            text-style: bold;
            color: #f8fafc;
            margin-bottom: 1;
        }
        #loading-note {
            color: #d7dee7;
        }
        .page-header {
            height: auto;
            margin-bottom: 1;
        }
        .page-title {
            text-style: bold;
            color: #f8fafc;
        }
        .workflow-note {
            color: #d7dee7;
            margin-bottom: 1;
        }
        .button-row {
            height: auto;
            margin-bottom: 1;
        }
        Button {
            margin-right: 1;
            min-width: 13;
        }
        DataTable {
            height: auto;
            margin-bottom: 1;
            border: solid #263647;
        }
        #files-table, #dedupe-groups-table {
            height: 16;
        }
        #metadata-findings-table {
            height: 6;
        }
        #metadata-rows-table {
            height: 1fr;
            min-height: 24;
        }
        .pane-title {
            text-style: bold;
            color: #f8fafc;
            margin: 1 0 0 0;
        }
        .note {
            color: #9fb0c1;
            margin-bottom: 1;
        }
        .detail {
            border: solid #263647;
            padding: 1;
            color: #d7dee7;
        }
        #mini-footer {
            height: 1;
            padding: 0 1;
            background: #111a23;
            color: #9fb0c1;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
            ("1", "focus_scan", "Scan"),
            ("2", "focus_files", "Files"),
            ("3", "focus_clean", "Declutter"),
            ("4", "focus_dedupe", "Dedupe"),
            ("5", "focus_metadata", "Metadata"),
            ("6", "focus_advanced", "Advanced"),
            ("s", "focus_file_search", "File Search"),
        ]

        def __init__(self) -> None:
            super().__init__(driver_class=SfxworkbenchDriver)
            self._library_path = initial_library_path
            self._resolved_report_paths = list(initial_report_paths)
            self._report_dir = operation_report_dir(
                db_path,
                library_path=self._library_path,
                report_paths=report_paths,
            )
            self._file_query = ""
            self._last_action: ActionResult | None = None
            self._running_worker: Worker[ActionResult] | None = None
            self._running_action = ""
            self._running_label = ""
            self._cancel_requested = False
            self._progress_phase = ""
            self._progress_completed = 0
            self._progress_total: int | None = None
            self._progress_message = ""
            self._file_rows = []
            self._report_rows: dict[str, list] = {}
            self._sort_state: dict[str, tuple[str, bool]] = {}
            self._last_compact = False
            self._session_started_at = time.time()

        def compose(self) -> ComposeResult:
            yield Tabs(*(Tab(label, id=key) for key, label in _FEATURES), active="scan", id="feature-tabs")
            with Horizontal(id="library-controls"):
                yield Input(
                    value="" if self._library_path == "PATH" else self._library_path,
                    placeholder="Library path",
                    id="library-path-input",
                )
                yield Button("Set Library", id="set-library-path")
                yield Button("Use Indexed Root", id="use-indexed-root")
                yield Button("Refresh", id="refresh-all")
            yield Static("", id="status-strip")
            with Horizontal(id="operation-row"):
                yield Static("", id="operation-strip")
                yield Button("Request Cancel", id="cancel-action", disabled=True)
            with ContentSwitcher(initial="loading-page", id="feature-pages"):
                yield from self._loading_page()
                yield from self._page("scan", self._scan_page)
                yield from self._page("files", self._files_page)
                yield from self._page("clean", self._clean_page)
                yield from self._page("dedupe", self._dedupe_page)
                yield from self._page("metadata", self._metadata_page)
                yield from self._page("advanced", self._advanced_page)
            yield Static("q Quit", id="mini-footer")

        def _page(self, key: str, factory) -> ComposeResult:
            with VerticalScroll(id=f"{key}-page", classes="page"):
                yield from factory()

        def _loading_page(self) -> ComposeResult:
            with Vertical(id="loading-page", classes="page"):
                yield Static("Loading SFX Workbench", id="loading-title")
                yield Static("Opening the index and preparing review tables...", id="loading-note")

        def _page_header(self, key: str) -> ComposeResult:
            title, note = _PAGE_HEADERS[key]
            with Vertical(classes="page-header"):
                yield Static(title, classes="page-title")
                yield Static(note, classes="workflow-note")

        def _scan_page(self) -> ComposeResult:
            yield from self._page_header("scan")
            with Horizontal(classes="button-row"):
                yield Button("Scan Library", id="scan-run")
                yield Button("Full Audit", id="scan-full-audit")
                yield Button("Refresh", id="scan-refresh")
            yield Static("", id="scan-note", classes="note")
            yield DataTable(id="scan-findings-table")
            yield Static("History", classes="pane-title")
            yield DataTable(id="scan-reports-table")
            yield Static("History Detail", classes="pane-title")
            yield DataTable(id="scan-report-detail-table")

        def _files_page(self) -> ComposeResult:
            yield from self._page_header("files")
            yield Input(placeholder="Search indexed files", id="file-search")
            with Horizontal(classes="button-row"):
                yield Button("Clear Search", id="files-clear-search")
                yield Button("Scan Library", id="files-scan-library")
                yield Button("Audition", id="files-open-file")
                yield Button("Reveal in Files", id="files-reveal-file")
            yield DataTable(id="files-table")
            yield Static("", id="file-detail", classes="detail")

        def _clean_page(self) -> ComposeResult:
            yield from self._page_header("clean")
            with Horizontal(classes="button-row"):
                yield Button("Preview Junk", id="clean-preview")
                yield Button("Apply Junk Cleanup", id="clean-apply", variant="warning")
                yield Button("Preview Name Cleanup", id="organize-rename-preview")
                yield Button("Apply Name Cleanup", id="organize-rename-apply", variant="warning")
                yield Button("Undo Name Cleanup", id="organize-rename-undo")
                yield Button("Refresh", id="clean-refresh")
            with Horizontal(classes="button-row"):
                yield Button("Preview Folder Cleanup", id="organize-audit")
                yield Button("Approve Folder Cleanup", id="organize-approve")
                yield Button("Apply Folder Cleanup", id="organize-apply", variant="warning")
                yield Button("Undo Folder Cleanup", id="organize-undo")
            with Horizontal(classes="button-row"):
                yield Button("Find Nested Folders", id="organize-nesting-audit")
                yield Button("Build Nesting Plan", id="organize-nesting-plan")
                yield Button("Approve Nesting", id="organize-nesting-approve")
                yield Button("Apply Nesting", id="organize-nesting-apply", variant="warning")
                yield Button("Undo Nesting", id="organize-nesting-undo")
            yield DataTable(id="clean-findings-table")
            yield Static("Previewed Junk", classes="pane-title")
            yield DataTable(id="clean-items-table")
            yield Static("History", classes="pane-title")
            yield DataTable(id="clean-reports-table")
            yield Static("History Detail", classes="pane-title")
            yield DataTable(id="clean-report-detail-table")

        def _dedupe_page(self) -> ComposeResult:
            yield from self._page_header("dedupe")
            with Horizontal(classes="button-row"):
                yield Button("Build Dedupe Plan", id="dedupe-build")
                yield Button("Approve Dedupe", id="dedupe-approve")
                yield Button("Apply Quarantine", id="dedupe-apply", variant="warning")
                yield Button("Pack Audit", id="pack-audit")
                yield Button("Build Pack Plan", id="pack-plan")
                yield Button("Approve Pack", id="pack-approve")
                yield Button("Apply Pack", id="pack-apply", variant="warning")
            yield DataTable(id="dedupe-findings-table")
            yield Static("Exact Duplicate Groups", classes="pane-title")
            yield DataTable(id="dedupe-groups-table")
            yield Static("History", classes="pane-title")
            yield DataTable(id="dedupe-reports-table")
            yield Static("History Detail", classes="pane-title")
            yield DataTable(id="dedupe-report-detail-table")

        def _metadata_page(self) -> ComposeResult:
            yield from self._page_header("metadata")
            with Horizontal(classes="button-row"):
                yield Button("Metadata Audit", id="metadata-audit")
                yield Button("Generate Suggestions", id="metadata-plan")
                yield Button("Generate Synonyms", id="metadata-plan-synonyms")
                yield Button("Approve DB Tags", id="metadata-approve")
                yield Button("Apply DB Tags", id="metadata-apply", variant="warning")
                yield Button("Export Sidecar", id="metadata-sidecar")
            yield DataTable(id="metadata-findings-table")
            yield Static("Metadata Values - First 100 Prioritized Files", classes="pane-title")
            yield DataTable(id="metadata-rows-table")
            yield Static("History", classes="pane-title")
            yield DataTable(id="metadata-reports-table")
            yield Static("History Detail", classes="pane-title")
            yield DataTable(id="metadata-report-detail-table")

        def _advanced_page(self) -> ComposeResult:
            yield from self._page_header("advanced")
            yield Static(
                "Index/cache controls, permanent delete, embedded metadata writes, compare, processed variants, and dual-mono stay here.",
                classes="note",
            )
            with Horizontal(classes="button-row"):
                yield Button("Plan Embedded Metadata", id="metadata-write-plan")
                yield Button("Approve Embedded Metadata", id="metadata-write-approve")
                yield Button("Apply Embedded Metadata", id="metadata-write-apply", variant="warning")
                yield Button("Undo Embedded Metadata", id="metadata-write-undo")
            with Horizontal(classes="button-row"):
                yield Button("Reveal Quarantine", id="quarantine-reveal")
                yield Button("Plan Permanent Delete", id="delete-plan")
                yield Button("Approve Permanent Delete", id="delete-approve")
                yield Button("Apply Permanent Delete", id="delete-apply", variant="error")
            yield DataTable(id="advanced-findings-table")
            yield Static("History", classes="pane-title")
            yield DataTable(id="advanced-reports-table")
            yield Static("History Detail", classes="pane-title")
            yield DataTable(id="advanced-report-detail-table")
            yield Static("Last Action", classes="pane-title")
            yield DataTable(id="action-result-table")

        def on_mount(self) -> None:
            self._last_compact = self._compact
            self.query_one("#status-strip", Static).update("Loading index...")
            self.query_one("#operation-strip", Static).update("Preparing review tables...")
            self.query_one("#feature-tabs", Tabs).focus()
            self.set_timer(0.05, self._finish_initial_load)

        def _finish_initial_load(self) -> None:
            self._refresh()
            self.query_one("#feature-pages", ContentSwitcher).current = "scan-page"
            self.query_one("#feature-tabs", Tabs).focus()

        def on_resize(self, event: events.Resize) -> None:
            _ = event
            if not self.is_mounted:
                return
            compact = self._compact
            if compact != self._last_compact:
                self._last_compact = compact
                self._refresh()

        @property
        def _compact(self) -> bool:
            return self.size.width <= 105

        def action_refresh(self) -> None:
            self._refresh()

        def action_focus_scan(self) -> None:
            self._open_feature("scan")

        def action_focus_files(self) -> None:
            self._open_feature("files")

        def action_focus_clean(self) -> None:
            self._open_feature("clean")

        def action_focus_dedupe(self) -> None:
            self._open_feature("dedupe")

        def action_focus_metadata(self) -> None:
            self._open_feature("metadata")

        def action_focus_advanced(self) -> None:
            self._open_feature("advanced")

        def action_focus_file_search(self) -> None:
            self._open_feature("files")
            self.query_one("#file-search", Input).focus()

        def _open_feature(self, key: str) -> None:
            if key == "organize":
                key = "clean"
            self.query_one("#feature-tabs", Tabs).active = key
            self.query_one("#feature-pages", ContentSwitcher).current = f"{key}-page"

        def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
            tab_id = event.tab.id or "scan"
            self.query_one("#feature-pages", ContentSwitcher).current = f"{tab_id}-page"
            self._refresh_reports(tab_id)

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "file-search":
                self._file_query = event.value
                self._fill_files()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "library-path-input":
                self._set_library_path(event.value)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id or ""
            root = self._root_path()
            report_dir = self._report_dir
            if button_id == "set-library-path":
                self._set_library_path(self.query_one("#library-path-input", Input).value)
            elif button_id == "use-indexed-root":
                self._set_library_path(library_root(db_path))
            elif button_id == "cancel-action":
                self._cancel_running_action()
            elif button_id in {
                "refresh-all",
                "scan-refresh",
                "clean-refresh",
            }:
                self._refresh()
            elif button_id in {"scan-run", "files-scan-library"}:
                self._start_action(
                    "scan",
                    "Scan Library",
                    lambda: scan_action(
                        root,
                        db_path,
                        progress_callback=self._threadsafe_progress_callback,
                        cancel_requested=self._is_cancel_requested,
                    ),
                )
            elif button_id == "scan-full-audit":
                self._start_action(
                    "full_audit",
                    "Full Audit",
                    lambda: full_audit_action(
                        root,
                        db_path,
                        report_dir,
                        progress_callback=self._threadsafe_progress_callback,
                    ),
                )
            elif button_id == "files-clear-search":
                self._file_query = ""
                self.query_one("#file-search", Input).value = ""
                self._fill_files()
            elif button_id == "files-open-file":
                self._open_selected_file(reveal=False)
            elif button_id == "files-reveal-file":
                self._open_selected_file(reveal=True)
            elif button_id == "clean-preview":
                self._start_action(
                    "clean_preview",
                    "Preview Junk",
                    lambda: clean_action(
                        root,
                        report_dir,
                        apply=False,
                        progress_callback=self._threadsafe_progress_callback,
                    ),
                )
            elif button_id == "clean-apply":
                self._confirm_then_start(
                    "clean_apply",
                    "Apply Junk Cleanup",
                    "This removes known junk files and folders. Recommended first: run Preview Junk and inspect the Previewed Junk table.",
                    lambda: clean_action(
                        root,
                        report_dir,
                        apply=True,
                        progress_callback=self._threadsafe_progress_callback,
                    ),
                )
            elif button_id == "dedupe-build":
                self._start_action(
                    "dedupe_build", "Build Dedupe Plan", lambda: build_dedupe_plan_action(db_path, report_dir)
                )
            elif button_id == "dedupe-approve":
                self._start_action(
                    "dedupe_approve",
                    "Approve Dedupe",
                    lambda: approve_dedupe_plan_action(report_dir),
                )
            elif button_id == "dedupe-apply":
                self._confirm_then_start(
                    "dedupe_apply",
                    "Apply Dedupe",
                    "This quarantines approved duplicate files from the current dedupe plan. Required first: Build Dedupe Plan, then Approve Dedupe.",
                    lambda: apply_dedupe_plan_action(db_path, report_dir),
                )
            elif button_id == "pack-audit":
                self._start_action("pack_audit", "Pack Audit", lambda: pack_audit_action(root, db_path, report_dir))
            elif button_id == "pack-plan":
                self._start_action("pack_plan", "Build Pack Plan", lambda: pack_plan_action(report_dir))
            elif button_id == "pack-approve":
                self._start_action("pack_approve", "Approve Pack", lambda: approve_pack_plan_action(report_dir))
            elif button_id == "pack-apply":
                self._confirm_then_start(
                    "pack_apply",
                    "Apply Pack",
                    "This quarantines approved pack/folder overlaps from the current pack plan. Required first: Pack Audit, Build Pack Plan, then Approve Pack.",
                    lambda: apply_pack_plan_action(db_path, report_dir),
                )
            elif button_id == "organize-rename-preview":
                self._start_action(
                    "rename_preview",
                    "Preview Name Cleanup",
                    lambda: rename_preview_action(root, report_dir, pattern="portable"),
                )
            elif button_id == "organize-rename-apply":
                self._confirm_then_start(
                    "rename_apply",
                    "Apply Name Cleanup",
                    "This renames files on disk and updates indexed paths. Recommended first: Preview Name Cleanup and review the generated plan.",
                    lambda: apply_rename_action(db_path, report_dir, pattern="portable"),
                )
            elif button_id == "organize-rename-undo":
                self._start_action("rename_undo", "Undo Name Cleanup", lambda: undo_rename_action(db_path, report_dir))
            elif button_id == "organize-audit":
                self._start_action(
                    "organize_audit",
                    "Preview Folder Cleanup",
                    lambda: organize_audit_action(root, report_dir),
                )
            elif button_id == "organize-apply":
                self._confirm_then_start(
                    "organize_apply",
                    "Apply Folder Cleanup",
                    "This applies approved folder cleanup entries, renames folders on disk, and updates indexed paths. Required first: Preview Folder Cleanup, then Approve Folder Cleanup.",
                    lambda: apply_organize_action(db_path, report_dir),
                )
            elif button_id == "organize-approve":
                self._start_action(
                    "organize_approve",
                    "Approve Folder Cleanup",
                    lambda: approve_organize_action(report_dir),
                )
            elif button_id == "organize-undo":
                self._start_action(
                    "organize_undo",
                    "Undo Folder Cleanup",
                    lambda: undo_organize_action(db_path, report_dir),
                )
            elif button_id == "organize-nesting-audit":
                self._start_action(
                    "organize_nesting_audit",
                    "Find Nested Folders",
                    lambda: organize_audit_action(root, report_dir, pattern="redundant-nesting"),
                )
            elif button_id == "organize-nesting-plan":
                self._start_action(
                    "organize_nesting_plan",
                    "Build Nesting Plan",
                    lambda: build_nesting_plan_action(report_dir),
                )
            elif button_id == "organize-nesting-apply":
                self._confirm_then_start(
                    "organize_nesting_apply",
                    "Apply Nesting",
                    "This applies approved nesting entries, flattens nested folders on disk, and updates indexed paths. Required first: Find Nested Folders, Build Nesting Plan, then Approve Nesting.",
                    lambda: apply_nesting_action(db_path, report_dir),
                )
            elif button_id == "organize-nesting-approve":
                self._start_action(
                    "organize_nesting_approve",
                    "Approve Nesting",
                    lambda: approve_organize_action(report_dir, plan_name="nesting_plan.json"),
                )
            elif button_id == "organize-nesting-undo":
                self._start_action(
                    "organize_nesting_undo",
                    "Undo Nesting",
                    lambda: undo_nesting_action(db_path, report_dir),
                )
            elif button_id == "metadata-audit":
                self._start_action(
                    "metadata_audit", "Metadata Audit", lambda: metadata_audit_action(db_path, report_dir)
                )
            elif button_id == "metadata-plan":
                self._start_action(
                    "metadata_plan",
                    "Generate Suggestions",
                    lambda: tag_plan_action(root, db_path, report_dir),
                )
            elif button_id == "metadata-plan-synonyms":
                self._start_action(
                    "metadata_plan_synonyms",
                    "Generate Synonyms",
                    lambda: tag_plan_action(root, db_path, report_dir, include_synonyms=True),
                )
            elif button_id == "metadata-apply":
                self._confirm_then_start(
                    "metadata_apply",
                    "Apply DB Tags",
                    "This writes approved tag decisions into the SQLite index. Required first: Generate Suggestions, then Approve DB Tags.",
                    lambda: apply_tag_plan_action(db_path, report_dir),
                )
            elif button_id == "metadata-approve":
                self._start_action(
                    "metadata_approve",
                    "Approve DB Tags",
                    lambda: approve_tag_plan_action(report_dir),
                )
            elif button_id == "metadata-sidecar":
                self._start_action(
                    "metadata_sidecar", "Export Sidecar", lambda: export_sidecar_action(root, db_path, report_dir)
                )
            elif button_id == "metadata-write-plan":
                self._start_action(
                    "metadata_write_plan",
                    "Plan Embedded Metadata",
                    lambda: build_embedded_metadata_plan_action(root, db_path, report_dir),
                )
            elif button_id == "metadata-write-apply":
                self._confirm_then_start(
                    "metadata_write_apply",
                    "Apply Embedded Metadata",
                    "This writes approved embedded metadata entries into audio files, backs up originals, and verifies readback. Required first: Plan Embedded Metadata, then Approve Embedded Metadata.",
                    lambda: apply_embedded_metadata_action(db_path, report_dir),
                )
            elif button_id == "metadata-write-approve":
                self._start_action(
                    "metadata_write_approve",
                    "Approve Embedded Metadata",
                    lambda: approve_embedded_metadata_action(report_dir),
                )
            elif button_id == "metadata-write-undo":
                self._start_action(
                    "metadata_write_undo",
                    "Undo Embedded Metadata",
                    lambda: undo_embedded_metadata_action(db_path, report_dir),
                )
            elif button_id == "quarantine-reveal":
                self._reveal_latest_quarantine()
            elif button_id == "delete-plan":
                self._start_action(
                    "delete_plan",
                    "Plan Permanent Delete",
                    lambda: build_delete_plan_action(report_dir),
                )
            elif button_id == "delete-apply":
                self._confirm_then_start(
                    "delete_apply",
                    "Apply Permanent Delete",
                    "This permanently deletes approved paths from the current delete plan. This cannot be undone. Required first: Reveal Quarantine, Plan Permanent Delete, inspect History Detail, then Approve Permanent Delete.",
                    lambda: apply_delete_plan_action(report_dir),
                )
            elif button_id == "delete-approve":
                self._start_action(
                    "delete_approve",
                    "Approve Permanent Delete",
                    lambda: approve_delete_plan_action(report_dir),
                )

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "files-table":
                self._show_file_detail(event.cursor_row)
            elif str(event.data_table.id or "").endswith("-reports-table"):
                self._show_report_detail(str(event.data_table.id), event.cursor_row, event.row_key)

        def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
            if event.data_table.id == "files-table":
                self._show_file_detail(event.coordinate.row)
            elif str(event.data_table.id or "").endswith("-reports-table"):
                self._show_report_detail(str(event.data_table.id), event.coordinate.row, event.cell_key.row_key)

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            if event.data_table.id == "files-table":
                self._show_file_detail(event.cursor_row)
            elif str(event.data_table.id or "").endswith("-reports-table"):
                self._show_report_detail(str(event.data_table.id), event.cursor_row, event.row_key)

        def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
            table_id = event.data_table.id or ""
            column_key = str(event.column_key)
            previous_key, previous_reverse = self._sort_state.get(table_id, ("", False))
            self._sort_state[table_id] = (column_key, not previous_reverse if previous_key == column_key else False)
            if table_id == "files-table":
                self._fill_files()
            elif table_id == "metadata-rows-table":
                self._fill_metadata()
            else:
                event.data_table.sort(event.column_key, key=_sort_text, reverse=self._sort_state[table_id][1])

        def _root_path(self) -> Path:
            return Path(self._library_path).expanduser()

        def _set_library_path(self, value: str) -> None:
            text = value.strip() or "PATH"
            if text.startswith("~"):
                text = str(Path(text).expanduser())
            self._library_path = text
            save_library_path(db_path, self._library_path)
            self._resolved_report_paths = report_search_paths(
                db_path=db_path,
                report_paths=report_paths,
                library_path=self._library_path,
            )
            self._report_dir = operation_report_dir(db_path, library_path=self._library_path, report_paths=report_paths)
            self.query_one("#library-path-input", Input).value = (
                "" if self._library_path == "PATH" else self._library_path
            )
            self._refresh()

        def _start_action(self, action: str, label: str, run: Callable[[], ActionResult]) -> None:
            if self._running_worker is not None and not self._running_worker.is_finished:
                self._last_action = ActionResult(
                    action=action,
                    status="warning",
                    message=f"{self._running_label} is already running. Cancel it before starting another action.",
                )
                self._fill_status_strip()
                self._fill_operation_strip()
                self._fill_action_result()
                return
            self._running_action = action
            self._running_label = label
            self._cancel_requested = False
            self._reset_action_progress()
            self._progress_phase = "starting"
            self._progress_message = f"Starting {label}"
            self._set_action_buttons_disabled(True)
            self.query_one("#cancel-action", Button).disabled = False
            self._running_worker = self.run_worker(
                run, name=action, description=label, thread=True, exit_on_error=False
            )
            self._fill_status_strip()
            self._fill_operation_strip()

        def _confirm_then_start(
            self,
            action: str,
            label: str,
            message: str,
            run: Callable[[], ActionResult],
        ) -> None:
            if self._running_worker is not None and not self._running_worker.is_finished:
                self._start_action(action, label, run)
                return

            def after_confirm(confirmed: bool | None) -> None:
                if confirmed:
                    self._start_action(action, label, run)

            self.push_screen(ConfirmActionScreen(label, message), callback=after_confirm)

        def _cancel_running_action(self) -> None:
            if self._running_worker is None or self._running_worker.is_finished:
                return
            self._cancel_requested = True
            self.query_one("#cancel-action", Button).disabled = True
            self._fill_status_strip()
            self._fill_operation_strip()

        def _is_cancel_requested(self) -> bool:
            return self._cancel_requested

        def _reset_action_progress(self) -> None:
            self._progress_phase = ""
            self._progress_completed = 0
            self._progress_total = None
            self._progress_message = ""

        def _threadsafe_progress_callback(self, phase: str, completed: int, total: int | None, message: str) -> None:
            try:
                self.call_from_thread(self._update_action_progress, phase, completed, total, message)
            except RuntimeError:
                pass

        def _update_action_progress(self, phase: str, completed: int, total: int | None, message: str) -> None:
            self._progress_phase = phase
            self._progress_completed = completed
            self._progress_total = total
            self._progress_message = message
            self._fill_operation_strip()

        def _set_action_buttons_disabled(self, disabled: bool) -> None:
            for button in self.query(Button):
                if button.id in _ACTION_BUTTON_IDS:
                    button.disabled = disabled

        def _selected_file_path(self) -> Path | None:
            if not self._file_rows:
                return None
            try:
                cursor_row = self.query_one("#files-table", DataTable).cursor_row
            except Exception:
                cursor_row = 0
            if cursor_row is None or cursor_row < 0 or cursor_row >= len(self._file_rows):
                cursor_row = 0
            return Path(self._file_rows[cursor_row].path)

        def _open_selected_file(self, *, reveal: bool) -> None:
            selected = self._selected_file_path()
            action = "reveal_file" if reveal else "open_file"
            if selected is None:
                self._last_action = ActionResult(
                    action=action, status="warning", message="No indexed file is selected."
                )
                self._fill_status_strip()
                self._fill_operation_strip()
                self._fill_action_result()
                return

            command = _desktop_open_command(selected, reveal=reveal)

            if not command:
                self._last_action = ActionResult(
                    action=action,
                    status="error",
                    message="No desktop file opener is available.",
                    errors=("No desktop file opener is available.",),
                )
            else:
                try:
                    subprocess.Popen(command)
                except OSError as exc:
                    self._last_action = ActionResult(
                        action=action,
                        status="error",
                        message=str(exc),
                        errors=(str(exc),),
                    )
                else:
                    verb = "Revealed" if reveal else "Opened"
                    self._last_action = ActionResult(
                        action=action,
                        status="ok",
                        message=f"{verb} {_clip_middle(selected.name, width=56)}.",
                    )
            self._fill_status_strip()
            self._fill_operation_strip()
            self._fill_action_result()

        def _latest_quarantine_dir(self) -> Path | None:
            report_paths = list(self._resolved_report_paths)
            if self._report_dir.exists() and self._report_dir not in report_paths:
                report_paths.insert(0, self._report_dir)
            return _latest_quarantine_dir_from_reports(report_paths)

        def _reveal_latest_quarantine(self) -> None:
            selected = self._latest_quarantine_dir()
            if selected is None:
                self._last_action = ActionResult(
                    action="quarantine_reveal",
                    status="warning",
                    message="No quarantine folder found in the active report paths.",
                )
            else:
                command = _desktop_open_command(selected)
                if not command:
                    self._last_action = ActionResult(
                        action="quarantine_reveal",
                        status="error",
                        message="No desktop file opener is available.",
                        errors=("No desktop file opener is available.",),
                    )
                else:
                    try:
                        subprocess.Popen(command)
                    except OSError as exc:
                        self._last_action = ActionResult(
                            action="quarantine_reveal",
                            status="error",
                            message=str(exc),
                            errors=(str(exc),),
                        )
                    else:
                        self._last_action = ActionResult(
                            action="quarantine_reveal",
                            status="ok",
                            message=f"Opened quarantine folder {_clip_middle(selected.name, width=56)}.",
                            output_path=str(selected),
                        )
            self._fill_status_strip()
            self._fill_operation_strip()
            self._fill_action_result()

        def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
            if event.worker is not self._running_worker:
                return
            if event.state == WorkerState.RUNNING:
                self._fill_status_strip()
                self._fill_operation_strip()
                return
            if event.state == WorkerState.SUCCESS:
                self._finish_running_action(event.worker.result)
            elif event.state == WorkerState.CANCELLED:
                self._finish_running_action(
                    ActionResult(
                        action=self._running_action,
                        status="cancelled",
                        message=f"Cancelled {self._running_label}.",
                        refresh=("status",),
                    )
                )
            elif event.state == WorkerState.ERROR:
                error = event.worker.error
                self._finish_running_action(
                    ActionResult(
                        action=self._running_action,
                        status="error",
                        message=str(error),
                        errors=(str(error),),
                        refresh=("status",),
                    )
                )

        def _finish_running_action(self, result: ActionResult) -> None:
            self._running_worker = None
            self._running_action = ""
            self._running_label = ""
            self._cancel_requested = False
            self._reset_action_progress()
            self._set_action_buttons_disabled(False)
            self.query_one("#cancel-action", Button).disabled = True
            self._run_action(result)

        def _run_action(self, result: ActionResult) -> None:
            self._last_action = result
            try:
                write_action_history(result, self._report_dir)
            except OSError as e:
                self._last_action = ActionResult(
                    action=result.action,
                    status=result.status,
                    message=f"{result.message} History write failed: {e}",
                    output_path=result.output_path,
                    errors=(*result.errors, f"History write failed: {e}"),
                    refresh=result.refresh,
                    details=result.details,
                )
            self._resolved_report_paths = report_search_paths(
                db_path=db_path,
                report_paths=report_paths,
                library_path=self._library_path,
            )
            if self._report_dir.exists() and self._report_dir not in self._resolved_report_paths:
                self._resolved_report_paths.insert(0, self._report_dir)
            self._refresh()
            self._fill_action_result()

        def _refresh(self) -> None:
            self._fill_status_strip()
            self._fill_operation_strip()
            self._fill_scan()
            self._fill_files()
            self._fill_clean()
            self._fill_dedupe()
            self._fill_metadata()
            self._fill_advanced()
            self._refresh_reports(self._active_feature())
            self._fill_action_result()

        def _active_feature(self) -> str:
            active = self.query_one("#feature-tabs", Tabs).active
            return str(active or "scan")

        def _reset_table(
            self, table_id: str, columns: tuple[str | tuple[str, str] | tuple[str, str, int], ...]
        ) -> DataTable:
            table = self.query_one(f"#{table_id}", DataTable)
            table.clear(columns=True)
            for column in columns:
                if isinstance(column, tuple):
                    label, key, *rest = column
                    width = rest[0] if rest else None
                    table.add_column(label, key=key, width=width)
                else:
                    table.add_column(column)
            table.cursor_type = "row"
            table.fixed_columns = 1 if len(columns) > 1 else 0
            return table

        def _sort_for_table(self, table_id: str, rows: list, key_map: dict[str, Callable]) -> list:
            sort_key, reverse = self._sort_state.get(table_id, ("", False))
            key_func = key_map.get(sort_key)
            if key_func is None:
                return rows
            return sorted(rows, key=key_func, reverse=reverse)

        def _fill_status_strip(self) -> None:
            pages = feature_pages(db_path=db_path, config_path=config_path)
            indexed_gb = indexed_library_size_gb(db_path)
            status = Text.assemble(
                ("library: ", "bold"),
                (_short_path(self._library_path, width=58 if not self._compact else 30), "cyan"),
                ("  reports: ", "bold"),
                (_short_path(self._report_dir, width=52 if not self._compact else 26), "cyan"),
                ("  size: ", "bold"),
                (f"{indexed_gb:,.1f} GB", "yellow"),
                "\n",
            )
            for index, page in enumerate(pages):
                if index:
                    status.append("  ")
                status.append(page.label, style="bold")
                status.append(": ")
                status.append(
                    str(page.primary_count), style="yellow" if page.status in {"review", "warning"} else "green"
                )
            if self._last_action is not None:
                status.append("  last: ", style="bold")
                status.append(self._last_action.message, style="green" if self._last_action.ok else "red")
            if self._running_worker is not None and not self._running_worker.is_finished:
                status.append("  running: ", style="bold yellow")
                status.append(self._running_label, style="yellow")
            self.query_one("#status-strip", Static).update(status)

        def _fill_operation_strip(self) -> None:
            if self._running_worker is not None and not self._running_worker.is_finished:
                prefix = "Cancel requested" if self._cancel_requested else "Running"
                detail = (
                    "cancel requested; waiting for the current safe operation to finish"
                    if self._cancel_requested
                    else "cancel request is available"
                )
                progress_line = self._progress_line()
                message = Text.assemble(
                    (f"{prefix}: ", "bold yellow"),
                    (self._running_label, "yellow"),
                    ("  "),
                    (detail, "dim"),
                    "\n",
                    progress_line,
                )
            elif self._last_action is not None:
                style = (
                    "green" if self._last_action.ok else "yellow" if self._last_action.status == "cancelled" else "red"
                )
                message = Text.assemble(
                    ("Last action: ", "bold"),
                    (self._last_action.action, "cyan"),
                    ("  "),
                    (self._last_action.message, style),
                )
            else:
                message = Text("No action is running.", style="dim")
            self.query_one("#operation-strip", Static).update(message)

        def _progress_line(self) -> Text:
            if self._progress_total is None:
                message = self._progress_message or "Preparing..."
                return Text(f"Progress: {message}", style="dim")
            total = max(0, self._progress_total)
            completed = min(max(0, self._progress_completed), total)
            width = 28 if not self._compact else 16
            filled = width if total == 0 else int(width * completed / total)
            bar = "#" * filled + "-" * (width - filled)
            percent = 100 if total == 0 else int(100 * completed / total)
            detail = _clip_middle(self._progress_message, width=48 if not self._compact else 24)
            return Text.assemble(
                ("Progress: ", "bold"),
                (f"[{bar}]", "green"),
                (" "),
                (f"{completed:,}/{total:,}", "yellow"),
                (" "),
                (f"{percent:3d}%", "yellow"),
                ("  "),
                (detail, "dim"),
            )

        def _fill_findings(self, table_id: str, rows) -> None:
            table = self._reset_table(table_id, ("Finding", "Count", "State", "Detail"))
            if not rows:
                table.add_row("No findings", "0", _state_token("clear"), "")
                return
            for row in rows:
                table.add_row(
                    row.label, _fmt(row.count), _state_token(_finding_status(row.status, row.count)), row.detail
                )

        def _fill_scan(self) -> None:
            self.query_one("#scan-note", Static).update(
                "Full Audit refreshes the index and writes read-only reports for health, metadata, duplicates, packs, groups, format, and UCS."
            )
            self._fill_findings("scan-findings-table", scan_findings(db_path=db_path, config_path=config_path))

        def _fill_clean(self) -> None:
            self._fill_findings(
                "clean-findings-table",
                clean_findings(self._library_path, db_path=db_path, scan_junk=False),
            )
            self._fill_clean_items()

        def _fill_clean_items(self) -> None:
            table = self._reset_table("clean-items-table", ("Type", "Path"))
            if self._last_action is None or self._last_action.action not in {"clean_preview", "clean_apply"}:
                table.add_row("none", "Run Preview Junk to list the files and folders that cleanup would touch.")
                return
            if self._last_action.action == "clean_apply":
                table.add_row("applied", "Cleanup was applied; preview list cleared. Run Preview Junk to refresh.")
                return
            details = self._last_action.details or {}
            files = list(details.get("removed_files", []))
            dirs = list(details.get("removed_dirs", []))
            if not files and not dirs:
                table.add_row("clear", "No junk files or folders were found.")
                return
            root_path = Path(self._library_path).expanduser()

            def display(path: object) -> str:
                text = str(path)
                try:
                    return str(Path(text).relative_to(root_path))
                except ValueError:
                    return _short_path(text)

            for path in files[:100]:
                table.add_row("file", display(path))
            for path in dirs[:100]:
                table.add_row("folder", display(path) + "/")
            remaining = max(0, len(files) + len(dirs) - 200)
            if remaining:
                table.add_row("more", f"{remaining:,} additional item(s) in the generated cleanup log.")

        def _fill_dedupe(self) -> None:
            self._fill_findings("dedupe-findings-table", dedupe_findings(db_path=db_path))
            table = self._reset_table(
                "dedupe-groups-table",
                ("Group", "Copies", "Extra", "Size", "Wasted", "State", "Keep Path"),
            )
            rows = dedupe_group_rows(db_path=db_path, limit=100)
            if not rows:
                table.add_row("none", "0", "0", "0", "0", _state_token("clear"), "No exact duplicate groups indexed.")
                return
            for row in rows:
                table.add_row(
                    str(row.group_id),
                    _fmt(row.copies),
                    _fmt(row.extra_copies),
                    _fmt(row.size_bytes),
                    _fmt(row.wasted_bytes),
                    _state_token(row.status),
                    _clip_middle(row.keep_path),
                )

        def _fill_metadata(self) -> None:
            plan_path = self._report_dir / "metadata_tag_plan.json"
            self._fill_findings("metadata-findings-table", metadata_findings(db_path=db_path, plan_path=plan_path))
            table = self._reset_table(
                "metadata-rows-table",
                (
                    ("State", "state", 12),
                    ("Tags", "tags", 180),
                    ("Filename", "filename", 56),
                ),
            )
            rows = metadata_workbench_rows(db_path=db_path, plan_path=plan_path, limit=100)
            rows = self._sort_for_table(
                "metadata-rows-table",
                rows,
                {
                    "state": lambda row: _sort_text(row.status),
                    "tags": lambda row: _sort_text(row.tags_summary),
                    "filename": lambda row: _sort_text(row.filename),
                },
            )
            if not rows:
                table.add_row(_state_token("info"), "", "No indexed files")
                return
            for row in rows:
                table.add_row(
                    _state_token(row.status),
                    _tags_cell(row),
                    row.filename,
                )

        def _fill_advanced(self) -> None:
            self._fill_findings("advanced-findings-table", advanced_findings(db_path=db_path, config_path=config_path))

        def _fill_files(self) -> None:
            columns = (
                (
                    ("Filename", "filename"),
                    ("Rate", "sample_rate"),
                    ("Ch", "channels"),
                    ("Meta", "metadata_flags"),
                    ("Tags", "tags"),
                    ("Issues", "issues"),
                    ("Path", "path"),
                )
                if self._compact
                else (
                    ("Filename", "filename"),
                    ("Ext", "extension"),
                    ("Rate", "sample_rate"),
                    ("Depth", "bit_depth"),
                    ("Ch", "channels"),
                    ("BEXT", "bext"),
                    ("iXML", "ixml"),
                    ("UCS", "ucs"),
                    ("Tags", "tags"),
                    ("Fields", "fields"),
                    ("Issues", "issues"),
                    ("Path", "path"),
                )
            )
            table = self._reset_table("files-table", columns)
            self._file_rows = list_files(db_path=db_path, query=self._file_query, limit=100)
            self._file_rows = self._sort_for_table(
                "files-table",
                self._file_rows,
                {
                    "filename": lambda row: _sort_text(row.filename),
                    "extension": lambda row: _sort_text(row.extension),
                    "sample_rate": lambda row: _sort_number(row.sample_rate),
                    "bit_depth": lambda row: _sort_number(row.bit_depth),
                    "channels": lambda row: _sort_number(row.channels),
                    "metadata_flags": lambda row: _sort_text(
                        ("B" if row.has_bext else "-") + ("I" if row.has_ixml else "-")
                    ),
                    "bext": lambda row: _sort_text("yes" if row.has_bext else "no"),
                    "ixml": lambda row: _sort_text("yes" if row.has_ixml else "no"),
                    "ucs": lambda row: _sort_text("yes" if row.is_ucs else "no"),
                    "tags": lambda row: _sort_number(row.accepted_tag_count),
                    "fields": lambda row: _sort_number(row.metadata_field_count),
                    "issues": lambda row: _sort_number(row.issue_count),
                    "path": lambda row: _sort_text(row.path),
                },
            )
            if not self._file_rows:
                if self._compact:
                    table.add_row("No files indexed yet", "", "", "", "", "", "Use Scan Library.")
                else:
                    table.add_row("No files indexed yet", "", "", "", "", "", "", "", "", "", "", "Use Scan Library.")
                self.query_one("#file-detail", Static).update(
                    "No files indexed yet. Use Scan Library to populate this view."
                )
                return
            for row in self._file_rows:
                if self._compact:
                    meta = ("B" if row.has_bext else "-") + ("I" if row.has_ixml else "-")
                    table.add_row(
                        row.filename,
                        _fmt(row.sample_rate),
                        _fmt(row.channels),
                        meta,
                        _fmt(row.accepted_tag_count),
                        _fmt(row.issue_count),
                        _clip_middle(row.path),
                    )
                else:
                    table.add_row(
                        row.filename,
                        row.extension or "",
                        _fmt(row.sample_rate),
                        _fmt(row.bit_depth),
                        _fmt(row.channels),
                        "yes" if row.has_bext else "no",
                        "yes" if row.has_ixml else "no",
                        "yes" if row.is_ucs else "no",
                        _fmt(row.accepted_tag_count),
                        _fmt(row.metadata_field_count),
                        _fmt(row.issue_count),
                        _clip_middle(row.path),
                    )
            self._show_file_detail(0)

        def _show_file_detail(self, row_index: int | None) -> None:
            detail = self.query_one("#file-detail", Static)
            if row_index is None or row_index < 0 or row_index >= len(self._file_rows):
                detail.update("No indexed file selected.")
                return
            selected = self._file_rows[row_index]
            data = file_detail(
                db_path=db_path,
                path=selected.path,
                library_path=self._library_path,
                plan_path=self._report_dir / "metadata_tag_plan.json",
            )
            if data is None:
                detail.update("File detail unavailable.")
                return
            lines = [data.filename]
            for section in data.sections:
                rows = [(label, value) for label, value in section.rows if value]
                if not rows:
                    continue
                lines.extend(["", section.title])
                lines.extend(f"{label}: {value}" for label, value in rows[:12])
            if data.issues:
                lines.extend(["", "Filename Issues"])
                lines.extend(data.issues[:8])
            if data.tags:
                lines.extend(["", "Accepted Tags"])
                lines.extend(data.tags[:8])
            detail.update("\n".join(lines))

        def _report_feature_from_table(self, table_id: str) -> str | None:
            suffix = "-reports-table"
            if not table_id.endswith(suffix):
                return None
            return table_id[: -len(suffix)]

        def _show_report_detail(self, table_id: str, row_index: int | None, row_key=None) -> None:
            feature = self._report_feature_from_table(table_id)
            if feature is None:
                return
            selected_path = getattr(row_key, "value", None)
            self._fill_report_detail(feature, row_index, selected_path=selected_path)

        def _fill_report_detail(
            self, feature: str, row_index: int | None = None, *, selected_path: str | None = None
        ) -> None:
            table_id = f"{feature}-report-detail-table"
            try:
                table = self.query_one(f"#{table_id}", DataTable)
            except Exception:
                return
            table.clear(columns=True)
            table.add_columns("Kind", "Action", "Source", "Target", "State", "Detail")
            summaries = self._report_rows.get(feature, [])
            if selected_path:
                selected = next((summary for summary in summaries if summary.path == selected_path), None)
                if selected is not None:
                    row_index = summaries.index(selected)
            if row_index is None or row_index < 0 or row_index >= len(summaries):
                table.add_row("none", "", "", "", "", "Select a history row to inspect its report detail.")
                return
            summary = summaries[row_index]
            try:
                rows = plan_detail_rows(Path(summary.path), limit=80)
            except (OSError, ValueError):
                rows = []
            if not rows:
                table.add_row("empty", "", summary.title, "", "", "No detail rows available in this JSON file.")
                return
            for row in rows:
                table.add_row(
                    row.kind,
                    _clip_middle(row.action, width=28),
                    _clip_middle(row.source, width=76),
                    _clip_middle(row.target, width=76),
                    row.status,
                    _clip_middle(row.detail, width=96),
                )

        def _refresh_reports(self, feature: str) -> None:
            table_id = f"{feature}-reports-table"
            try:
                table = self.query_one(f"#{table_id}", DataTable)
            except Exception:
                return
            columns = (
                ("Kind", "Type", "Rows", "Err", "Title", "Path")
                if self._compact
                else (
                    "Kind",
                    "Report Type",
                    "Rows",
                    "Errors",
                    "Protected",
                    "Conflicts",
                    "Undo",
                    "Title",
                    "Path",
                )
            )
            table.clear(columns=True)
            table.add_columns(*columns)
            query = _feature_query(feature)
            report_paths = list(self._resolved_report_paths)
            if self._report_dir.exists() and self._report_dir not in report_paths:
                report_paths.insert(0, self._report_dir)
            summaries = discover_plan_files(report_paths, query=query, limit=40)
            self._report_rows[feature] = summaries
            if not summaries:
                if self._compact:
                    table.add_row("none", "none", "0", "0", "No generated reports found", "")
                else:
                    table.add_row("none", "none", "0", "0", "0", "0", "no", "No generated reports found", "")
                self._fill_report_detail(feature, None)
                return
            for summary in summaries:
                if self._compact:
                    table.add_row(
                        summary.category,
                        summary.kind,
                        _fmt(summary.entries),
                        _fmt(summary.errors),
                        summary.title,
                        _clip_middle(summary.path),
                        key=summary.path,
                    )
                else:
                    table.add_row(
                        summary.category,
                        summary.kind,
                        _fmt(summary.entries),
                        _fmt(summary.errors),
                        _fmt(summary.protected),
                        _fmt(summary.conflicts),
                        "yes" if summary.undoable else "no",
                        summary.title,
                        _clip_middle(summary.path),
                        key=summary.path,
                    )
            self._fill_report_detail(feature, 0)

        def _fill_action_result(self) -> None:
            try:
                table = self.query_one("#action-result-table", DataTable)
            except Exception:
                return
            table.clear(columns=True)
            table.add_columns("Field", "Value")
            if self._last_action is None:
                table.add_row("Status", "No action has run in this session.")
                return
            result = self._last_action
            table.add_row("Action", result.action)
            table.add_row("State", result.status)
            table.add_row("Message", result.message)
            table.add_row("Output", result.output_path or "")
            table.add_row("Refresh", ", ".join(result.refresh))
            if result.errors:
                table.add_row("Errors", "; ".join(result.errors[:6]))

    SfxworkbenchTui().run()
