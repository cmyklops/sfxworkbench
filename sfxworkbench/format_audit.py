"""Report-only audio format consistency audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.groups import audit_related_groups
from sfxworkbench.models import FormatAuditGroup, FormatAuditReport, FormatAuditSummary, FormatInconsistency

console = Console()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _inconsistency(field: str, values: list[int]) -> FormatInconsistency | None:
    if len(values) <= 1:
        return None
    return FormatInconsistency(field=field, values=values)


def build_format_audit_report(root: Path, db_path: Path, min_files: int = 2, limit: int = 200) -> FormatAuditReport:
    """Find related groups with mixed sample rate, bit depth, or channel counts.

    This is intentionally report-only. It preserves original audio format and
    produces evidence for review instead of recommending conversion.
    """
    if min_files < 2:
        raise ValueError("--min-files must be at least 2")
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")

    related = audit_related_groups(root, db_path=db_path, min_files=min_files, limit=0)
    inconsistent: list[FormatAuditGroup] = []
    sample_rate_groups = 0
    bit_depth_groups = 0
    channel_layout_groups = 0

    for source_group in related.groups:
        issues = [
            issue
            for issue in (
                _inconsistency("sample_rate", source_group.sample_rates),
                _inconsistency("bit_depth", source_group.bit_depths),
                _inconsistency("channels", source_group.channels),
            )
            if issue is not None
        ]
        if not issues:
            continue

        sample_rate_groups += any(issue.field == "sample_rate" for issue in issues)
        bit_depth_groups += any(issue.field == "bit_depth" for issue in issues)
        channel_layout_groups += any(issue.field == "channels" for issue in issues)
        inconsistent.append(
            FormatAuditGroup(
                group_id=0,
                source_group_id=source_group.group_id,
                parent_path=source_group.parent_path,
                inferred_stem=source_group.inferred_stem,
                related_group_reason=source_group.reason,
                file_count=source_group.file_count,
                inconsistencies=issues,
                files=source_group.files,
            )
        )

    inconsistent.sort(
        key=lambda group: (
            -len(group.inconsistencies),
            -group.file_count,
            group.parent_path,
            group.inferred_stem.casefold(),
        )
    )
    selected = inconsistent if limit == 0 else inconsistent[:limit]
    for group_id, group in enumerate(selected, start=1):
        group.group_id = group_id

    summary = FormatAuditSummary(
        related_groups_considered=related.summary.candidate_groups,
        inconsistent_groups=len(inconsistent),
        reported_groups=len(selected),
        affected_files=sum(group.file_count for group in inconsistent),
        sample_rate_groups=sample_rate_groups,
        bit_depth_groups=bit_depth_groups,
        channel_layout_groups=channel_layout_groups,
    )

    return FormatAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root.resolve()),
        db_path=str(db_path),
        min_files=min_files,
        limit=limit,
        summary=summary,
        groups=selected,
    )


def write_format_audit_report(report: FormatAuditReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    if not quiet:
        console.print(f"Format audit report written to [cyan]{output_path}[/cyan]")


def show_format_audit_report(report: FormatAuditReport) -> None:
    summary = report.summary
    console.print(
        f"Found [yellow]{summary.inconsistent_groups:,}[/yellow] format-inconsistent related group(s) "
        f"covering [yellow]{summary.affected_files:,}[/yellow] file(s)."
    )
    if not report.groups:
        return

    table = Table(title="Format consistency review", show_lines=False)
    table.add_column("Group", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Fields")
    table.add_column("Stem")
    table.add_column("Folder")
    for group in report.groups[:20]:
        fields = ", ".join(issue.field for issue in group.inconsistencies)
        table.add_row(str(group.group_id), str(group.file_count), fields, group.inferred_stem, group.parent_path)
    console.print(table)
