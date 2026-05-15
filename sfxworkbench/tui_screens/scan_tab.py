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
    "Quick Index builds the searchable file list fast. Full Audit enriches audio, metadata, "
    "hashes, and writes read-only reports."
)


def compose(app) -> ComposeResult:
    """Yield the Scan tab's widgets in order."""
    from textual.widgets import DataTable, Static

    yield from app._page_header(KEY)
    yield Static("", id="scan-note", classes="note")
    yield DataTable(id="scan-findings-table")
    yield from app._button_row(
        ("Quick Index", "scan-run"),
        ("Full Audit", "scan-full-audit"),
    )


def fill(app) -> None:
    """Populate the Scan tab's tables from the active index + reports.

    The note text is set here rather than at compose time so it stays in sync
    with the rest of the tab's content on refresh.
    """
    from textual.widgets import Static

    from sfxworkbench.tui_data import scan_findings

    app.query_one("#scan-note", Static).update(
        "Quick Index builds the searchable file list fast. Full Audit enriches audio, metadata, "
        "hashes, and writes read-only reports."
    )
    app._fill_findings(
        "scan-findings-table",
        scan_findings(db_path=app.db_path, config_path=app.config_path),
    )


def fill_loading(app) -> None:
    """Paint the Scan shell without touching DB/report adapters."""
    from textual.widgets import Static

    app.query_one("#scan-note", Static).update("Loading index summary…")
    table = app._reset_table("scan-findings-table", ("Finding", "Count", "State", "Detail"))
    table.add_row("Loading index summary", "", "", "Counts will fill in shortly.")


def fill_rows(app, rows) -> None:
    """Paint already-computed Scan findings from a background load."""
    from textual.widgets import Static

    app.query_one("#scan-note", Static).update(
        "Quick Index builds the searchable file list fast. Full Audit enriches audio, metadata, "
        "hashes, and writes read-only reports."
    )
    app._fill_findings("scan-findings-table", rows)
