"""Report-only folder organization previews."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.models import (
    OrganizeAuditReport,
    OrganizeAuditSummary,
    OrganizeEntry,
    OrganizeReviewResult,
    RenameEntry,
    RenamePlan,
    RenameResult,
)
from wavwarden.rename import apply_rename_plan, undo_rename_log

console = Console()

_SUPPORTED_PATTERNS = {"strip-leading-numbers"}
_DOTTED_OR_DASHED_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-_.]\s*(.+?)\s*$")
_SORT_SPACE_PREFIX_RE = re.compile(r"^\s*(?:0\d+|\d)\s+(.+?)\s*$")
_DOUBLE_SPACE_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s{2,}(.+?)\s*$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_leading_number(name: str) -> str | None:
    """Return a folder name without an obvious manual sort prefix."""
    for pattern in (_DOTTED_OR_DASHED_PREFIX_RE, _DOUBLE_SPACE_PREFIX_RE, _SORT_SPACE_PREFIX_RE):
        match = pattern.match(name)
        if not match:
            continue
        candidate = match.group(1).strip(" -_.")
        if candidate and candidate != name and not candidate.isdigit():
            return candidate
    return None


def _iter_dirs_at_depth(root: Path, depth: int) -> list[Path]:
    if depth < 1:
        raise ValueError("depth must be at least 1")
    dirs: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if len(rel_parts) == depth:
            dirs.append(path)
    return sorted(dirs, key=lambda path: str(path).lower())


def audit_organization(root: Path, pattern: str = "strip-leading-numbers", depth: int = 1) -> OrganizeAuditReport:
    """Build a report-only folder organization preview."""
    if pattern not in _SUPPORTED_PATTERNS:
        raise ValueError("Only pattern='strip-leading-numbers' is currently supported")
    if depth < 1:
        raise ValueError("depth must be at least 1")

    root = root.resolve()
    dirs = _iter_dirs_at_depth(root, depth)
    entries: list[OrganizeEntry] = []
    errors: list[dict] = []
    planned_targets: set[Path] = set()

    for path in dirs:
        if pattern == "strip-leading-numbers":
            new_name = _strip_leading_number(path.name)
        else:
            new_name = None
        if not new_name:
            continue

        target = path.with_name(new_name)
        if target == path:
            continue
        if target.exists():
            errors.append({"path": str(path), "target": str(target), "error": "target exists"})
            continue
        if target in planned_targets:
            errors.append({"path": str(path), "target": str(target), "error": "target planned more than once"})
            continue
        planned_targets.add(target)
        entries.append(
            OrganizeEntry(
                old_path=str(path),
                new_path=str(target),
                old_name=path.name,
                new_name=new_name,
            )
        )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern=pattern,
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            planned=len(entries),
            errors=len(errors),
        ),
        entries=entries,
        errors=errors,
    )


def write_organize_audit_report(report: OrganizeAuditReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2))
    if not quiet:
        console.print(f"Organization preview written to [cyan]{output_path}[/cyan]")


def review_organize_report(
    report_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    entries: list[int] | None = None,
    quiet: bool = False,
) -> OrganizeReviewResult:
    """Stamp an organization report with approved entry indexes."""
    report = json.loads(report_path.read_text())
    total = len(report.get("entries", []))
    requested = set(entries or [])
    invalid = sorted(entry for entry in requested if entry < 1 or entry > total)
    if approve_all:
        approved = set(range(total))
    else:
        approved = {entry - 1 for entry in requested if 1 <= entry <= total}

    existing_review = report.get("review", {})
    approved.update(existing_review.get("approved_entries", []))
    approved_entries = sorted(approved)
    report["review"] = {
        "status": "approved" if len(approved_entries) == total and total else "partially_approved",
        "approved_at": _now_iso(),
        "approved_entries": approved_entries,
    }

    output = output_path or report_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    result = OrganizeReviewResult(
        report_path=str(report_path),
        output_path=str(output),
        total_entries=total,
        approved_entries=len(approved_entries),
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_entries:,}[/yellow] of "
            f"[yellow]{result.total_entries:,}[/yellow] organization entry/entries in [cyan]{output}[/cyan]"
        )
        if invalid:
            console.print(f"[red]Ignored invalid entry number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def _rename_plan_from_report(report: OrganizeAuditReport, raw_report: dict, require_reviewed: bool) -> RenamePlan:
    approved = set(raw_report.get("review", {}).get("approved_entries", []))
    entries: list[RenameEntry] = []
    errors = list(report.errors)
    if require_reviewed and not approved:
        errors.append({"path": raw_report.get("root"), "error": "report has no approved entries"})

    for index, entry in enumerate(report.entries):
        if require_reviewed and index not in approved:
            errors.append({"path": entry.old_path, "error": f"entry {index + 1} is not approved"})
            continue
        entries.append(
            RenameEntry(
                old_path=entry.old_path,
                new_path=entry.new_path,
                old_filename=entry.old_name,
                new_filename=entry.new_name,
                issue_fixes=[entry.reason],
            )
        )

    return RenamePlan(
        generated_at=_now_iso(),
        root=report.root,
        pattern=f"organize:{report.pattern}",
        entries=sorted(entries, key=lambda entry: (len(Path(entry.old_path).parts), entry.old_path), reverse=True),
        errors=errors,
    )


def apply_organize_report(
    report_path: Path,
    db_path: Path | None = None,
    log_path: Path | None = None,
    require_reviewed: bool = False,
    quiet: bool = False,
) -> RenameResult:
    """Apply a reviewed organization report using the rename engine."""
    raw_report = json.loads(report_path.read_text())
    report = OrganizeAuditReport.model_validate(raw_report)
    plan = _rename_plan_from_report(report, raw_report, require_reviewed=require_reviewed)
    return apply_rename_plan(plan, db_path=db_path, log_path=log_path, dry_run=False, quiet=quiet)


def undo_organize_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> RenameResult:
    """Undo a previously applied organization log."""
    return undo_rename_log(log_path, db_path=db_path, dry_run=dry_run, quiet=quiet)


def show_organize_audit_report(report: OrganizeAuditReport) -> None:
    console.print(
        f"Scanned [yellow]{report.summary.directories_scanned:,}[/yellow] folder(s), "
        f"planned [yellow]{report.summary.planned:,}[/yellow] rename(s), "
        f"found [yellow]{report.summary.errors:,}[/yellow] error(s)."
    )
    if report.entries:
        table = Table(title="Folder organization preview", show_lines=False)
        table.add_column("Old", style="white")
        table.add_column("New", style="cyan")
        for entry in report.entries[:50]:
            table.add_row(entry.old_name, entry.new_name)
        console.print(table)
        if len(report.entries) > 50:
            console.print(f"[dim]...{len(report.entries) - 50} more planned rename(s).[/dim]")
    if report.errors:
        console.print("[red]Preview has collision/error(s); apply would be refused until resolved.[/red]")
