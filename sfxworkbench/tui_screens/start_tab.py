"""Page module for the first-run Start tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "start"
TITLE = "Start"
NOTE = (
    "A guided first pass for copied libraries: choose a folder, build the index, "
    "then review the highest-value cleanup queues before applying anything."
)


def compose(app) -> ComposeResult:
    """Yield the Start tab widgets in order."""
    from textual.widgets import DataTable, Static

    yield from app._page_header(KEY)
    yield Static("", id="start-note", classes="note")
    yield DataTable(id="start-steps-table")
    yield from app._button_row(
        ("Quick Index", "scan-run"),
        ("Smart Full Audit", "scan-full-audit"),
    )


def fill(app) -> None:
    """Populate the first-run worklist from indexed state and review queues."""
    from sfxworkbench.tui_data import start_steps

    fill_rows(app, start_steps(db_path=app.db_path, library_path=app._library_path))


def fill_loading(app) -> None:
    """Paint the Start shell without touching DB/report adapters."""
    from textual.widgets import Static

    app.query_one("#start-note", Static).update("Loading first-run worklist...")
    table = app._reset_table(
        "start-steps-table",
        (
            ("Step", "step", 22),
            ("Payoff", "payoff", 10),
            ("State", "state", 12),
            ("Signal", "signal", 28),
            ("Why it matters", "reason"),
            ("Next action", "next"),
        ),
    )
    table.add_row("Loading", "", "", "Index summary", "The worklist will fill in shortly.", "")


def fill_rows(app, rows) -> None:
    """Paint already-computed Start rows from a background load."""
    from textual.widgets import Static

    from sfxworkbench.tui_app import _fmt, _state_token

    app._start_rows = list(rows or [])
    app.query_one("#start-note", Static).update(
        "Start here for a safe first pass. Select a row to jump to the matching workbench tab."
    )
    table = app._reset_table(
        "start-steps-table",
        (
            ("Step", "step", 22),
            ("Payoff", "payoff", 10),
            ("State", "state", 12),
            ("Signal", "signal", 28),
            ("Why it matters", "reason"),
            ("Next action", "next"),
        ),
    )
    if not app._start_rows:
        table.add_row("No steps", "", _state_token("clear"), "", "Nothing needs attention yet.", "")
        return
    for row in app._start_rows:
        table.add_row(
            f"{row.order}. {row.label}",
            row.payoff,
            _state_token(row.status),
            _fmt(row.detail),
            row.reason,
            row.next_action,
        )
