"""Page module for the Dedupe tab (exact-duplicate detection + pack overlaps)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.app import ComposeResult

KEY = "dedupe"
TITLE = "Dedupe"
NOTE = (
    "Smart dedupe and pack actions reuse same-library plans only when root, DB, and scan age match. "
    "Palette overrides can reuse indexed hashes or rebuild reports and plans."
)


def pack_audit_feedback_row(result: Any) -> tuple[str, str, str, str, str, str, str] | None:
    """Return a one-row summary for a just-completed pack audit action."""
    if getattr(result, "action", "") != "pack_audit":
        return None
    details = getattr(result, "details", None)
    if not isinstance(details, dict):
        return None
    summary = details.get("summary")
    if not isinstance(summary, dict):
        return None
    exact_groups = int(summary.get("exact_duplicate_groups") or 0)
    overlaps = int(summary.get("overlap_candidates") or 0)
    folders = int(summary.get("folders_analyzed") or 0)
    files = int(summary.get("indexed_files_considered") or 0)
    total = exact_groups + overlaps
    state = "review" if total else "clear"
    message = (
        f"Pack audit found {exact_groups:,} exact folder group(s), "
        f"{overlaps:,} overlap candidate(s), {folders:,} folder(s), {files:,} indexed file(s)."
    )
    return ("pack audit", str(exact_groups), str(overlaps), "", "", state, message)


def compose(app) -> ComposeResult:
    from textual.widgets import DataTable, Input

    yield from app._page_header(KEY)
    yield DataTable(id="dedupe-findings-table")
    yield from app._button_row(
        ("Smart Dedupe Plan", "dedupe-build"),
        ("Apply Quarantine", "dedupe-apply", "warning"),
        ("Smart Pack Audit", "pack-audit"),
        ("Smart Pack Plan", "pack-plan"),
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
            history_detail_suffix="Duplicate rows below are live index state scoped to the active library.",
        ),
        *dedupe_findings(db_path=app.db_path, library_path=app._library_path),
    ]
    app._fill_findings("dedupe-findings-table", findings)
    table = app._reset_table(
        "dedupe-groups-table",
        ("Group", "Copies", "Extra", "Size", "Wasted", "State", "Keep Path"),
    )
    last_action = getattr(app, "_last_action", None)
    pack_feedback = pack_audit_feedback_row(last_action)
    if pack_feedback is not None:
        group, copies, extra, size, wasted, state, message = pack_feedback
        table.add_row(group, copies, extra, size, wasted, _state_token(state), message)
    if last_action is not None and last_action.action in {"dedupe_apply", "pack_apply"} and last_action.errors:
        table.add_row(
            "issues",
            "",
            _fmt(len(last_action.errors)),
            "",
            "",
            _state_token("warning"),
            "Review History for apply issues.",
        )
    rows = dedupe_group_rows(
        db_path=app.db_path,
        query=getattr(app, "_dedupe_query", ""),
        limit=100,
        library_path=app._library_path,
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
