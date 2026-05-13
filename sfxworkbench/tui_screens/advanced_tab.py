"""Page module for the Advanced tab.

The grab-bag of less-frequent workflows: embedded metadata writes, permanent
delete from quarantine, plus the action-result detail panel that mirrors the
last completed worker. Anything that's destructive on real files lives here
gated behind explicit confirmation modals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "advanced"
TITLE = "Advanced"
NOTE = "Embedded metadata writes, permanent delete from quarantine logs, and the last-action detail viewer."


def compose(app) -> ComposeResult:
    from textual.widgets import DataTable, Static

    yield from app._page_header(KEY)
    yield Static(
        "Index/cache controls, permanent delete, embedded metadata writes, "
        "compare, processed variants, and dual-mono stay here.",
        classes="note",
    )
    yield from app._button_row(
        ("Plan Embedded Metadata", "metadata-write-plan"),
        ("Approve Embedded Metadata", "metadata-write-approve"),
        ("Apply Embedded Metadata", "metadata-write-apply", "warning"),
        ("Undo Embedded Metadata", "metadata-write-undo"),
    )
    yield from app._button_row(
        ("Reveal Quarantine", "quarantine-reveal"),
        ("Plan Permanent Delete", "delete-plan"),
        ("Approve Permanent Delete", "delete-approve"),
        ("Apply Permanent Delete", "delete-apply", "error"),
    )
    yield DataTable(id="advanced-findings-table")
    yield from app._titled_table_pair(
        "History",
        "advanced-reports-table",
        "History Detail",
        "advanced-report-detail-table",
    )
    yield from app._titled_table("Last Action", "action-result-table")


def fill(app) -> None:
    from sfxworkbench.tui_data import advanced_findings

    app._fill_findings(
        "advanced-findings-table",
        advanced_findings(db_path=app.db_path, config_path=app.config_path),
    )
