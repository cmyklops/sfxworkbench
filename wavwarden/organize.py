"""Report-only folder organization previews."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.models import OrganizeAuditReport, OrganizeAuditSummary, OrganizeEntry

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
