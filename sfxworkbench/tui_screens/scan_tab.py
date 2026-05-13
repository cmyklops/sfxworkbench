"""Page module for the Scan tab.

Decomposed from the monolithic ``tui_app.SfxworkbenchTui`` class. The App calls
:func:`compose` inside its ``ContentSwitcher`` to lay out the tab's widgets and
:func:`fill` from its global refresh path to repopulate them.

Per the decomposition pattern, page modules:

- Stay framework-aware (they import Textual widgets) but app-agnostic.
- Use the App as a service locator: helpers like ``app._button_row`` and
  ``app._fill_findings`` live there; the page calls them.
- Carry no instance state of their own. Anything stateful sits on the App
  (filter inputs, sort order, etc.).

This makes per-tab Pilot tests straightforward: pass a fake/mock app object
that records the calls and assert on the calls + yielded widgets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "scan"
TITLE = "Scan and Audit"
NOTE = (
    "Index the library and run a full audit. Scan refreshes file metadata; Full Audit "
    "writes read-only reports for health, metadata, duplicates, packs, groups, format, "
    "and UCS coverage."
)


def compose(app) -> ComposeResult:
    """Yield the Scan tab's widgets in order."""
    from textual.widgets import DataTable, Static

    yield from app._page_header(KEY)
    yield from app._button_row(
        ("Scan Library", "scan-run"),
        ("Full Audit", "scan-full-audit"),
        ("Refresh", "scan-refresh"),
    )
    yield Static("", id="scan-note", classes="note")
    yield DataTable(id="scan-findings-table")
    yield from app._titled_table("History", "scan-reports-table")
    yield from app._titled_table("History Detail", "scan-report-detail-table")


def fill(app) -> None:
    """Populate the Scan tab's tables from the active index + reports.

    The note text is set here rather than at compose time so it stays in sync
    with the rest of the tab's content on refresh.
    """
    from textual.widgets import Static

    from sfxworkbench.tui_data import scan_findings

    app.query_one("#scan-note", Static).update(
        "Full Audit refreshes the index and writes read-only reports for "
        "health, metadata, duplicates, packs, groups, format, and UCS."
    )
    app._fill_findings(
        "scan-findings-table",
        scan_findings(db_path=app.db_path, config_path=app.config_path),
    )
