"""Page module for the Metadata tab.

Metadata audit + tag suggestion + DB tag apply + tag-file export. The
metadata-rows-table shows the first 500 prioritized files with their pending
vs. existing tag state, mirroring what the standalone ``MetadataReviewScreen``
shows but inline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "metadata"
TITLE = "Metadata"
NOTE = (
    "Find reviewable tags, accept the good ones into the index, then write accepted metadata to files."
)


def compose(app) -> ComposeResult:
    from textual.widgets import DataTable, Static

    yield from app._page_header(KEY)
    yield DataTable(id="metadata-findings-table")
    yield from app._button_row(
        ("Metadata Audit", "metadata-audit"),
        ("Find Tags", "metadata-plan"),
        ("Review Tags", "metadata-review-open"),
        ("Accept Tags & Prepare Write", "metadata-apply", "warning"),
    )
    yield from app._button_row(
        ("Write Metadata to Files", "metadata-write-apply", "warning"),
        ("Undo File Writes", "metadata-write-undo"),
        ("Save Tags File", "metadata-sidecar"),
    )
    yield from app._button_row(
        ("Previous 500", "metadata-page-prev"),
        ("Next 500", "metadata-page-next"),
        ("Random Pending", "metadata-page-random"),
    )
    yield Static("Source symbols: # filename  / path  ~ group  ^ UCS catalog/stem  * synonym", classes="note")
    yield from app._titled_table("Metadata Values - First 500 Prioritized Files", "metadata-rows-table")


def fill(app) -> None:
    from sfxworkbench.tui_app import _sort_text, _state_token
    from sfxworkbench.tui_data import metadata_findings, metadata_workbench_rows
    from sfxworkbench.tui_text import _tags_cell

    plan_path = app._report_dir / "metadata_tag_plan.json"
    app._fill_findings(
        "metadata-findings-table",
        metadata_findings(db_path=app.db_path, plan_path=plan_path),
    )
    table = app._reset_table(
        "metadata-rows-table",
        (
            ("State", "state", 12),
            ("Tags", "tags", 180),
            ("Filename", "filename", 56),
        ),
    )
    # ``Random Pending`` results can't use the adapter cache (random order
    # varies), so the warm thread hands them back under the current warm key.
    warm_key = None
    if hasattr(app, "_metadata_warm_key"):
        warm_key = app._metadata_warm_key(
            plan_path,
            random_pending=getattr(app, "_metadata_random_pending", False),
        )
    prewarmed_by_key = getattr(app, "_metadata_prewarmed_rows_by_key", {})
    prewarmed = prewarmed_by_key.pop(warm_key, None) if warm_key is not None else None
    legacy_prewarmed = getattr(app, "_metadata_prewarmed_rows", None)
    if prewarmed is not None or legacy_prewarmed is not None:
        rows = prewarmed if prewarmed is not None else legacy_prewarmed
        app._metadata_prewarmed_rows = None
    else:
        rows = metadata_workbench_rows(
            db_path=app.db_path,
            plan_path=plan_path,
            query=getattr(app, "_metadata_query", ""),
            limit=getattr(app, "_metadata_page_size", 500),
            offset=getattr(app, "_metadata_offset", 0),
            random_pending=getattr(app, "_metadata_random_pending", False),
            pending_only=True,
        )
    rows = app._sort_for_table(
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

    def tags_cell(row):
        cell = getattr(row, "prerendered_tags_cell", None)
        return cell.copy() if cell is not None else _tags_cell(row)

    # Batch insert: one ``add_rows`` call beats 500 reactive ``add_row`` calls
    # by ~10× on a real-library Metadata refresh.
    table.add_rows((_state_token(row.status), tags_cell(row), row.filename) for row in rows)
