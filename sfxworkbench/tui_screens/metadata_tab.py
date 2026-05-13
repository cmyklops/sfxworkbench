"""Page module for the Metadata tab.

Metadata audit + tag suggestion + DB tag apply + sidecar export. The
metadata-rows-table shows the first 100 prioritized files with their pending
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
    "Audit metadata coverage, generate UCS/keyword suggestions, and apply DB-only "
    "tags. Press R (capital) for the dedicated two-pane review screen."
)


def compose(app) -> ComposeResult:
    from textual.widgets import DataTable

    yield from app._page_header(KEY)
    yield from app._button_row(
        ("Metadata Audit", "metadata-audit"),
        ("Generate Suggestions", "metadata-plan"),
        ("Generate Synonyms", "metadata-plan-synonyms"),
        ("Approve DB Tags", "metadata-approve"),
        ("Apply DB Tags", "metadata-apply", "warning"),
        ("Export Sidecar", "metadata-sidecar"),
    )
    yield DataTable(id="metadata-findings-table")
    yield from app._titled_table("Metadata Values - First 100 Prioritized Files", "metadata-rows-table")
    yield from app._titled_table("History", "metadata-reports-table")
    yield from app._titled_table("History Detail", "metadata-report-detail-table")


def fill(app) -> None:
    from sfxworkbench.tui_app import _sort_text, _state_token, _tags_cell
    from sfxworkbench.tui_data import metadata_findings, metadata_workbench_rows

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
    rows = metadata_workbench_rows(db_path=app.db_path, plan_path=plan_path, limit=100)
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
    for row in rows:
        table.add_row(
            _state_token(row.status),
            _tags_cell(row),
            row.filename,
        )
