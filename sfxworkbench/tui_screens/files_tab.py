"""Page module for the Files tab.

Owns the searchable indexed-file browser. Per-tab decomposition pattern: see
:mod:`sfxworkbench.tui_screens.scan_tab`.

The actual fill logic for the files table (the largest of any tab's fill, with
sortable columns, compact vs. full layout, and tag rendering) stays on the
App as ``_fill_files`` because it touches several App-level helpers
(``_compact``, ``_sort_for_table``, ``_tags_cell``). This module just delegates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "files"
TITLE = "Files"
NOTE = "Browse and inspect indexed files. The search field above the list filters as you type; selection populates the detail panel below."


def compose(app) -> ComposeResult:
    from textual.widgets import DataTable, Input, Static

    yield from app._page_header(KEY)
    yield from app._button_flow(
        ("Clear Search", "files-clear-search"),
        ("Audition", "files-open-file"),
        ("Reveal in Files", "files-reveal-file"),
        ("Reveal Quarantine", "quarantine-reveal"),
        ("Plan Permanent Delete", "delete-plan"),
        ("Apply Permanent Delete", "delete-apply", "error"),
    )
    yield Input(placeholder="Search indexed files", id="file-search")
    yield DataTable(id="files-table")
    yield Static("", id="file-detail", classes="detail")


def fill(app) -> None:
    """Delegate to the App's existing ``_fill_files_impl``.

    The implementation lives on the App because it consults several
    instance attributes (``_compact``, ``_file_query``, ``_sort_state``)
    that would be awkward to pass through a module function. Future cleanup
    can lift this into the module once those attrs migrate to a per-tab
    state object.
    """
    app._fill_files_impl()
