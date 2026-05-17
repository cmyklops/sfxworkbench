"""Page module for the Dedupe tab (exact-duplicate detection + pack overlaps)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "dedupe"
TITLE = "Dedupe"
NOTE = (
    "Find exact MD5 duplicates and overlapping pack folders. Plans are reviewable; "
    "applies quarantine extra copies into ``apply_logs/`` for safe undo."
)


def compose(app) -> ComposeResult:
    from textual.widgets import DataTable, Input

    yield from app._page_header(KEY)
    yield DataTable(id="dedupe-findings-table")
    yield from app._button_row(
        ("Build Dedupe Plan", "dedupe-build"),
        ("Apply Quarantine", "dedupe-apply", "warning"),
        ("Pack Audit", "pack-audit"),
        ("Build Pack Plan", "pack-plan"),
        ("Apply Pack", "pack-apply", "warning"),
    )
    yield Input(placeholder="Filter duplicate groups (by hash or file path)", id="dedupe-search")
    yield from app._titled_table("Exact Duplicate Groups", "dedupe-groups-table")


def fill(app) -> None:
    """Populate the findings + grouped-duplicate table.

    The duplicate-groups table mirrors the SQL view in ``dedupe.py``: one row
    per (md5, size) cluster, with copies/extra/size/wasted and the keep-copy
    path. Delegates to the App for sort + render helpers.
    """
    from sfxworkbench.tui_app import _clip_middle, _fmt, _state_token
    from sfxworkbench.tui_data import dedupe_findings, dedupe_group_rows, workflow_history_finding
    from sfxworkbench.utils import fmt_bytes

    findings = [
        workflow_history_finding(
            "dedupe",
            "Latest dedupe action",
            app._history_report_paths(),
            actions=("dedupe_plan", "dedupe_apply", "pack_audit", "pack_plan", "pack_apply"),
            no_history_detail="No saved dedupe or pack action found for this report folder.",
            history_detail_suffix="Duplicate rows below are live index state.",
        ),
        *dedupe_findings(db_path=app.db_path),
    ]
    app._fill_findings("dedupe-findings-table", findings)
    table = app._reset_table(
        "dedupe-groups-table",
        ("Group", "Copies", "Extra", "Size", "Wasted", "State", "Keep Path"),
    )
    rows = dedupe_group_rows(
        db_path=app.db_path,
        query=getattr(app, "_dedupe_query", ""),
        limit=100,
    )
    if not rows:
        table.add_row("none", "0", "0", "0", "0", _state_token("clear"), "No exact duplicate groups indexed.")
        return
    for row in rows:
        table.add_row(
            str(row.group_id),
            _fmt(row.copies),
            _fmt(row.extra_copies),
            fmt_bytes(float(row.size_bytes or 0)),
            fmt_bytes(float(row.wasted_bytes or 0)),
            _state_token(row.status),
            _clip_middle(row.keep_path),
        )
