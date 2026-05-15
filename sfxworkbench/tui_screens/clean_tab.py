"""Page module for the Cleanup (clean + organize) tab.

Houses the three-row button set: junk preview/apply + name cleanup + folder
cleanup + nesting. The findings table is the cross-page summary; the
``clean-items-table`` follows the most recent cleanup preview so users can
audit the relevant paths before applying.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "clean"
TITLE = "Cleanup"
NOTE = (
    "Junk cleanup, name normalization, folder cleanup, and nesting flatten. "
    "Every destructive button has a confirmation gate; previews are read-only."
)


def compose(app) -> ComposeResult:
    from textual.containers import Horizontal, Vertical
    from textual.widgets import DataTable, Static

    def workflow_row(title: str, note: str, *buttons) -> ComposeResult:
        with Horizontal(classes="cleanup-workflow-row"):
            with Vertical(classes="cleanup-workflow-label"):
                yield Static(title, classes="cleanup-workflow-title")
                yield Static(note, classes="cleanup-workflow-note")
            with Horizontal(classes="cleanup-workflow-actions"):
                for spec in buttons:
                    yield app._button_from_spec(spec)

    yield from app._page_header(KEY)
    yield DataTable(id="clean-findings-table")
    yield from workflow_row(
        "Junk",
        "Known removable files and folders.",
        ("Preview Junk", "clean-preview"),
        ("Apply Junk Cleanup", "clean-apply", "warning"),
    )
    yield from workflow_row(
        "Names",
        "Portable filename normalization.",
        ("Preview Name Cleanup", "organize-rename-preview"),
        ("Apply Name Cleanup", "organize-rename-apply", "warning"),
        ("Undo Name Cleanup", "organize-rename-undo", "primary"),
    )
    yield from workflow_row(
        "Folders",
        "Top-level folder cleanup plans.",
        ("Preview Folder Cleanup", "organize-audit"),
        ("Apply Folder Cleanup", "organize-apply", "warning"),
        ("Undo Folder Cleanup", "organize-undo", "primary"),
    )
    yield from workflow_row(
        "Nesting",
        "Flatten redundant nested folders.",
        ("Find Nested Folders", "organize-nesting-audit"),
        ("Build Nesting Plan", "organize-nesting-plan"),
        ("Apply Nesting", "organize-nesting-apply", "warning"),
        ("Undo Nesting", "organize-nesting-undo", "primary"),
    )
    yield from app._titled_table("Latest Cleanup Preview", "clean-items-table")


def fill(app) -> None:
    from sfxworkbench.tui_data import clean_findings

    app._fill_findings(
        "clean-findings-table",
        clean_findings(app._library_path, db_path=app.db_path, scan_junk=False),
    )
    app._fill_clean_items()
