"""sfx audit command — query the index for problems."""

from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench.db import get_connection, path_scope_filter, path_scope_params, resolve_scope_root
from sfxworkbench.models import AuditResult

console = Console()

_STANDARD_SAMPLE_RATES = {44100, 48000, 88200, 96000, 176400, 192000}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def run_audit(
    db_path: Path,
    quiet: bool = False,
    *,
    root: Path | None = None,
    action_mode: str = "audit",
) -> AuditResult:
    """Query the index for problems and print a Rich summary.

    Returns the structured result so callers (tests, future GUI) can use it
    without reparsing terminal output.
    """
    conn = get_connection(db_path)
    scope_root = resolve_scope_root(root) if root is not None else None
    scope_params = path_scope_params(scope_root) if scope_root is not None else ()

    def files_where(condition: str | None = None, *, column: str = "path") -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        params: list[object] = []
        if condition:
            clauses.append(condition)
        if scope_root is not None:
            clauses.append(path_scope_filter(column))
            params.extend(scope_params)
        return (" WHERE " + " AND ".join(clauses), tuple(params)) if clauses else ("", ())

    def count_files(condition: str | None = None) -> int:
        where_sql, params = files_where(condition)
        return int(conn.execute("SELECT COUNT(*) FROM files" + where_sql, params).fetchone()[0] or 0)

    total = count_files()
    scan_errors = count_files("scan_error IS NOT NULL")
    missing_metadata = count_files("has_bext = 0 AND has_ixml = 0")
    has_bext = count_files("has_bext = 1")
    has_ixml = count_files("has_ixml = 1")
    ucs_named = count_files("is_ucs = 1")

    sample_rate_where, sample_rate_params = files_where("sample_rate IS NOT NULL")
    sample_rate_rows = conn.execute(
        "SELECT sample_rate, COUNT(*) AS cnt FROM files "
        + sample_rate_where
        + " GROUP BY sample_rate ORDER BY cnt DESC",
        sample_rate_params,
    ).fetchall()
    sample_rates = {str(row["sample_rate"]): row["cnt"] for row in sample_rate_rows}
    unusual_sample_rates = [
        {"sample_rate": row["sample_rate"], "count": row["cnt"]}
        for row in sample_rate_rows
        if row["sample_rate"] not in _STANDARD_SAMPLE_RATES
    ]

    if scope_root is None:
        fn_issue_rows = conn.execute(
            "SELECT issue, COUNT(*) AS cnt FROM fn_issues GROUP BY issue ORDER BY cnt DESC"
        ).fetchall()
    else:
        fn_issue_rows = conn.execute(
            f"""
            SELECT fn_issues.issue, COUNT(*) AS cnt
            FROM fn_issues
            JOIN files ON files.id = fn_issues.file_id
            WHERE {path_scope_filter("files.path")}
            GROUP BY fn_issues.issue
            ORDER BY cnt DESC
            """,
            scope_params,
        ).fetchall()
    fn_issues_by_type = {row["issue"]: row["cnt"] for row in fn_issue_rows}

    error_where, error_params = files_where("scan_error IS NOT NULL")
    error_rows = conn.execute("SELECT path, scan_error FROM files" + error_where + " LIMIT 50", error_params).fetchall()
    errors = [{"path": row["path"], "error": row["scan_error"]} for row in error_rows]

    bit_depth_where, bit_depth_params = files_where("bit_depth IS NOT NULL")
    bit_depth_rows = conn.execute(
        "SELECT bit_depth, COUNT(*) AS cnt FROM files" + bit_depth_where + " GROUP BY bit_depth ORDER BY cnt DESC",
        bit_depth_params,
    ).fetchall()
    bit_depths = {str(row["bit_depth"]): row["cnt"] for row in bit_depth_rows}

    conn.close()

    result = AuditResult(
        generated_at=_now_iso(),
        root=str(scope_root) if scope_root is not None else None,
        db_path=str(db_path),
        action_mode=action_mode,
        total_files=total,
        scan_errors=scan_errors,
        missing_metadata=missing_metadata,
        has_bext=has_bext,
        has_ixml=has_ixml,
        ucs_named=ucs_named,
        unusual_sample_rates=unusual_sample_rates,
        fn_issues_total=sum(fn_issues_by_type.values()),
        fn_issues_by_type=fn_issues_by_type,
        errors=errors,
        bit_depths=bit_depths,
        sample_rates=sample_rates,
    )

    if not quiet:
        _print_audit(result)
    return result


def _print_audit(r: AuditResult) -> None:
    """Print audit results as Rich tables."""
    total = r.total_files

    table = Table(title="Library Audit Summary", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")

    table.add_row("Total indexed files", f"{total:,}")
    table.add_row("Scan errors", f"[red]{r.scan_errors:,}[/red]" if r.scan_errors else "0")

    meta_pct = 100 * (total - r.missing_metadata) / total if total else 0
    table.add_row("Missing metadata (bext+iXML)", f"{r.missing_metadata:,} ({100 - meta_pct:.1f}%)")
    table.add_row("Has bext", str(r.has_bext))
    table.add_row("Has iXML", str(r.has_ixml))

    ucs_pct = 100 * r.ucs_named / total if total else 0
    table.add_row("UCS-named", f"{r.ucs_named:,} ({ucs_pct:.1f}%)")
    table.add_row("Filename issues", f"{r.fn_issues_total:,}")

    console.print(table)

    if r.unusual_sample_rates:
        console.print("\n[yellow]Unusual sample rates:[/yellow]")
        for entry in r.unusual_sample_rates:
            console.print(f"  {entry['sample_rate']:,} Hz — {entry['count']:,} files")

    if r.fn_issues_by_type:
        issue_table = Table(title="Filename Issues by Type", show_lines=False)
        issue_table.add_column("Issue", style="yellow")
        issue_table.add_column("Count", justify="right")
        for issue, count in sorted(r.fn_issues_by_type.items(), key=lambda x: -x[1]):
            issue_table.add_row(issue, str(count))
        console.print(issue_table)

    if r.errors:
        console.print(f"\n[red]Scan errors (first {len(r.errors)}):[/red]")
        for err in r.errors:
            console.print(f"  [dim]{err['path']}[/dim] — {err['error']}")
