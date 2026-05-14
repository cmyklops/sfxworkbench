"""Page module for the shared History tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "history"
TITLE = "History"
NOTE = "Browse generated reports, plans, logs, previews, and action history in one timeline."

# Dropdown choices for the Feature and Category filters. Kept here so tests can
# import them; the order also drives the order shown in the Select widgets.
HISTORY_FEATURE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("All features", "all"),
    ("Scan", "scan"),
    ("Files", "files"),
    ("Cleanup", "cleanup"),
    ("Dedupe", "dedupe"),
    ("Metadata", "metadata"),
)

HISTORY_CATEGORY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("All categories", "all"),
    ("Report", "report"),
    ("Plan", "plan"),
    ("Log", "log"),
    ("History", "history"),
    ("Preview", "preview"),
)


def compose(app) -> ComposeResult:
    from textual.containers import Horizontal, Vertical
    from textual.widgets import DataTable, Input, Select, Static

    yield from app._page_header(KEY)
    with Horizontal(classes="button-row"):
        yield Input(placeholder="Search history", id="history-search")
        yield Select(
            options=HISTORY_FEATURE_OPTIONS,
            value="all",
            allow_blank=False,
            id="history-feature-filter",
        )
        yield Select(
            options=HISTORY_CATEGORY_OPTIONS,
            value="all",
            allow_blank=False,
            id="history-category-filter",
        )
    with Horizontal(classes="history-pair"):
        with Vertical(classes="history-pane"):
            yield Static("All Recent History", classes="pane-title")
            yield DataTable(id="history-table")
        with Vertical(classes="history-pane"):
            yield Static("Selected Item Detail", classes="pane-title")
            yield DataTable(id="history-detail-table")


def fill(app) -> None:
    app._fill_history_impl()
