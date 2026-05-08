"""Reviewed DB-only tag plans and apply workflow."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH, get_connection
from wavwarden.models import (
    TagApplyResult,
    TagPlan,
    TagPlanEntry,
    TagPlanSummary,
    TagReviewResult,
    TagSuggestionReport,
)
from wavwarden.tag_suggest import build_tag_suggestion_report
from wavwarden.utils import json_dumps

console = Console()

PLAN_SCHEMA_VERSION = 1
_VALID_REVIEW_STATES = {"approved", "rejected", "pending"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_plan_path() -> Path:
    return Path(f"tag_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


def _default_log_path() -> Path:
    return Path(f"tag_apply_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


def _existing_tag_values(conn, *, file_id: int, field: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT value
        FROM accepted_tags
        WHERE file_id = ? AND field = ?
        ORDER BY value
        """,
        (file_id, field),
    ).fetchall()
    return [row["value"] for row in rows]


def _summarize_plan(plan: TagPlan) -> TagPlanSummary:
    return TagPlanSummary(
        files_considered=plan.summary.files_considered,
        candidate_entries=len(plan.entries),
        add_entries=sum(1 for entry in plan.entries if entry.action == "add"),
        skip_existing_entries=sum(1 for entry in plan.entries if entry.action == "skip_existing"),
        approved_entries=sum(1 for entry in plan.entries if entry.review_status == "approved"),
        rejected_entries=sum(1 for entry in plan.entries if entry.review_status == "rejected"),
    )


def _plan_from_suggestion_report(
    report: TagSuggestionReport,
    *,
    db_path: Path,
    source_report: Path | None = None,
    target: str = "db",
) -> TagPlan:
    conn = get_connection(db_path)
    entries: list[TagPlanEntry] = []
    entry_id = 1
    for suggestion_entry in report.entries:
        for suggestion in suggestion_entry.suggestions:
            existing_values = _existing_tag_values(conn, file_id=suggestion_entry.file_id, field=suggestion.field)
            action = "skip_existing" if existing_values else "add"
            entries.append(
                TagPlanEntry(
                    entry_id=entry_id,
                    file_id=suggestion_entry.file_id,
                    path=suggestion_entry.path,
                    filename=suggestion_entry.filename,
                    size_bytes=suggestion_entry.size_bytes,
                    mtime=suggestion_entry.mtime,
                    md5=suggestion_entry.md5,
                    field=suggestion.field,
                    action=action,
                    existing_values=existing_values,
                    proposed_value=suggestion.value,
                    source=suggestion.source,
                    method=suggestion.method,
                    confidence=suggestion.confidence,
                    evidence=suggestion.evidence,
                )
            )
            entry_id += 1
    conn.close()
    plan = TagPlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=report.root,
        db_path=str(db_path),
        source_report=str(source_report) if source_report is not None else None,
        target=target,
        min_confidence=report.min_confidence,
        limit=report.limit,
        summary=TagPlanSummary(
            files_considered=report.summary.files_considered,
            candidate_entries=len(entries),
            add_entries=sum(1 for entry in entries if entry.action == "add"),
            skip_existing_entries=sum(1 for entry in entries if entry.action == "skip_existing"),
        ),
        entries=entries,
    )
    plan.summary = _summarize_plan(plan)
    return plan


def build_tag_plan(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    min_confidence: float = 0.0,
    limit: int = 200,
    ucs_catalog_path: Path | None = None,
    use_ucs_catalog: bool = False,
    source_report: Path | None = None,
    target: str = "db",
) -> TagPlan:
    """Build a reviewed DB-only tag plan from suggestions."""
    if target != "db":
        raise ValueError("Only target='db' is supported in this metadata-writing slice")
    if source_report is not None:
        report = TagSuggestionReport.model_validate(json.loads(source_report.read_text()))
    else:
        report = build_tag_suggestion_report(
            root,
            db_path=db_path,
            min_confidence=min_confidence,
            limit=limit,
            ucs_catalog_path=ucs_catalog_path,
            use_ucs_catalog=use_ucs_catalog,
        )
    return _plan_from_suggestion_report(report, db_path=db_path, source_report=source_report, target=target)


def write_tag_plan(plan: TagPlan, output_path: Path | None = None, quiet: bool = False) -> Path:
    output = output_path or _default_plan_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json_dumps(plan), encoding="utf-8")
    if not quiet:
        console.print(f"Tag plan written to [cyan]{output}[/cyan]")
    return output


def load_tag_plan(plan_path: Path) -> TagPlan:
    return TagPlan.model_validate(json.loads(plan_path.read_text()))


def review_tag_plan(
    plan_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    entries: list[int] | None = None,
    reject_entries: list[int] | None = None,
    quiet: bool = False,
) -> TagReviewResult:
    """Mark selected plan entries as approved or rejected."""
    plan = load_tag_plan(plan_path)
    by_id = {entry.entry_id: entry for entry in plan.entries}
    requested_approve = set(entries or [])
    requested_reject = set(reject_entries or [])
    invalid = sorted((requested_approve | requested_reject) - set(by_id))
    if approve_all:
        requested_approve.update(by_id)
    for entry_id in sorted(requested_approve - set(invalid)):
        by_id[entry_id].review_status = "approved"
    for entry_id in sorted(requested_reject - set(invalid)):
        by_id[entry_id].review_status = "rejected"
    plan.summary = _summarize_plan(plan)

    output = output_path or plan_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json_dumps(plan), encoding="utf-8")
    result = TagReviewResult(
        plan_path=str(plan_path),
        output_path=str(output),
        total_entries=len(plan.entries),
        approved_entries=plan.summary.approved_entries,
        rejected_entries=plan.summary.rejected_entries,
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_entries:,}[/yellow] and rejected "
            f"[yellow]{result.rejected_entries:,}[/yellow] of "
            f"[yellow]{result.total_entries:,}[/yellow] tag plan entrie(s)."
        )
        if invalid:
            console.print(f"[red]Ignored invalid entry number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def _validate_plan_entry(conn, entry: TagPlanEntry) -> str | None:
    row = conn.execute(
        "SELECT path, size_bytes, mtime, md5 FROM files WHERE id = ?",
        (entry.file_id,),
    ).fetchone()
    if row is None:
        return "indexed file row is missing"
    if row["path"] != entry.path:
        return f"path changed: expected {entry.path}, got {row['path']}"
    if entry.size_bytes is not None and row["size_bytes"] != entry.size_bytes:
        return f"size changed: expected {entry.size_bytes}, got {row['size_bytes']}"
    if entry.mtime is not None and row["mtime"] != entry.mtime:
        return "mtime changed"
    if entry.md5 is not None and row["md5"] != entry.md5:
        return "md5 changed"
    if not Path(entry.path).exists():
        return "file does not exist"
    return None


def apply_tag_plan(
    plan_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    require_reviewed: bool = False,
    log_path: Path | None = None,
    quiet: bool = False,
) -> TagApplyResult:
    """Apply approved tag plan entries into the DB-only accepted_tags table."""
    plan = load_tag_plan(plan_path)
    effective_db = db_path or Path(plan.db_path)
    result = TagApplyResult(planned=len(plan.entries), dry_run=dry_run, target=plan.target)
    if plan.target != "db":
        result.errors.append({"path": str(plan_path), "error": f"unsupported tag target: {plan.target}"})
        return result
    approved_entries = [entry for entry in plan.entries if entry.review_status == "approved"]
    if require_reviewed and not approved_entries:
        result.errors.append({"path": str(plan_path), "error": "plan has no approved entries"})
        return result
    conn = get_connection(effective_db)
    now = _now_iso()
    for entry in plan.entries:
        if require_reviewed and entry.review_status != "approved":
            result.skipped += 1
            continue
        if entry.review_status == "rejected":
            result.skipped += 1
            continue
        if entry.review_status not in _VALID_REVIEW_STATES:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": "invalid review status"})
            continue
        validation_error = _validate_plan_entry(conn, entry)
        if validation_error is not None:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": validation_error})
            continue
        existing_values = _existing_tag_values(conn, file_id=entry.file_id, field=entry.field)
        if entry.action == "skip_existing" or existing_values:
            result.skipped += 1
            continue
        if dry_run:
            result.applied += 1
            continue
        conn.execute(
            """
            INSERT INTO accepted_tags (
                file_id, field, value, source, method, confidence, evidence,
                plan_entry_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id, field, value) DO UPDATE SET
                source = excluded.source,
                method = excluded.method,
                confidence = excluded.confidence,
                evidence = excluded.evidence,
                plan_entry_id = excluded.plan_entry_id,
                updated_at = excluded.updated_at
            """,
            (
                entry.file_id,
                entry.field,
                entry.proposed_value,
                entry.source,
                entry.method,
                entry.confidence,
                json.dumps(entry.evidence),
                entry.entry_id,
                now,
                now,
            ),
        )
        result.applied += 1
    if log_path is None and not dry_run:
        log_path = _default_log_path()
    if log_path is not None:
        result.log_path = str(log_path)
    log_payload = None
    if log_path is not None:
        log_payload = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "tool": "wavwarden",
            "tool_version": __version__,
            "plan_path": str(plan_path),
            "db_path": str(effective_db),
            "result": result,
        }
    if not dry_run:
        conn.execute(
            """
            INSERT INTO tag_apply_log (plan_path, db_path, dry_run, generated_at, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(plan_path),
                str(effective_db),
                int(dry_run),
                log_payload["generated_at"] if log_payload is not None else _now_iso(),
                json_dumps(result),
            ),
        )
        conn.commit()
    conn.close()
    if log_path is not None and log_payload is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json_dumps(log_payload), encoding="utf-8")
    if not quiet:
        show_tag_apply_result(result)
    return result


def show_tag_plan(plan: TagPlan) -> None:
    table = Table(title="Tag plan", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Candidate entries", f"{plan.summary.candidate_entries:,}")
    table.add_row("Add entries", f"{plan.summary.add_entries:,}")
    table.add_row("Skip existing", f"{plan.summary.skip_existing_entries:,}")
    table.add_row("Approved", f"{plan.summary.approved_entries:,}")
    console.print(table)
    if not plan.entries:
        return
    sample = Table(title="Sample tag entries", show_lines=False)
    sample.add_column("#", justify="right")
    sample.add_column("File")
    sample.add_column("Field")
    sample.add_column("Value")
    sample.add_column("Action")
    sample.add_column("Review")
    for entry in plan.entries[:20]:
        sample.add_row(
            str(entry.entry_id),
            entry.filename,
            entry.field,
            entry.proposed_value,
            entry.action,
            entry.review_status,
        )
    console.print(sample)


def show_tag_apply_result(result: TagApplyResult) -> None:
    table = Table(title="Tag apply result", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Applied", f"{result.applied:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)
