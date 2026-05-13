"""Page module for the Declutter (clean + organize) tab.

Houses the three-row button set: junk preview/apply + name cleanup + folder
cleanup + nesting. The findings table is the cross-page summary; the
``clean-items-table`` shows the most recent Preview Junk result so users can
audit before applying.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "clean"
TITLE = "Declutter"
NOTE = (
    "Junk cleanup, name normalization, folder cleanup, and nesting flatten. "
    "Every destructive button has a confirmation gate; previews are read-only."
)


def compose(app) -> ComposeResult:
    from textual.widgets import DataTable

    yield from app._page_header(KEY)
    yield from app._button_row(
        ("Preview Junk", "clean-preview"),
        ("Apply Junk Cleanup", "clean-apply", "warning"),
        ("Preview Name Cleanup", "organize-rename-preview"),
        ("Apply Name Cleanup", "organize-rename-apply", "warning"),
        ("Undo Name Cleanup", "organize-rename-undo"),
        ("Refresh", "clean-refresh"),
    )
    yield from app._button_row(
        ("Preview Folder Cleanup", "organize-audit"),
        ("Approve Folder Cleanup", "organize-approve"),
        ("Apply Folder Cleanup", "organize-apply", "warning"),
        ("Undo Folder Cleanup", "organize-undo"),
    )
    yield from app._button_row(
        ("Find Nested Folders", "organize-nesting-audit"),
        ("Build Nesting Plan", "organize-nesting-plan"),
        ("Approve Nesting", "organize-nesting-approve"),
        ("Apply Nesting", "organize-nesting-apply", "warning"),
        ("Undo Nesting", "organize-nesting-undo"),
    )
    yield DataTable(id="clean-findings-table")
    yield from app._titled_table("Previewed Junk", "clean-items-table")
    yield from app._titled_table("History", "clean-reports-table")
    yield from app._titled_table("History Detail", "clean-report-detail-table")


def fill(app) -> None:
    from sfxworkbench.tui_data import clean_findings

    app._fill_findings(
        "clean-findings-table",
        clean_findings(app._library_path, db_path=app.db_path, scan_junk=False),
    )
    app._fill_clean_items()
