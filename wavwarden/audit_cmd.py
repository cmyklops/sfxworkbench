"""sfx audit command — query the index for problems."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden.db import get_connection

console = Console()

_STANDARD_SAMPLE_RATES = {44100, 48000, 88200, 96000, 176400, 192000}


def run_audit(db_path: Path) -> dict:
    """Return counts of: missing metadata, scan errors, unusual sample rates, etc."""
    conn = get_connection(db_path)

    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    scan_errors = conn.execute(
        "SELECT COUNT(*) FROM files WHERE scan_error IS NOT NULL"
    ).fetchone()[0]
    missing_metadata = conn.execute(
        "SELECT COUNT(*) FROM files WHERE has_bext = 0 AND has_ixml = 0"
    ).fetchone()[0]
    has_bext = conn.execute("SELECT COUNT(*) FROM files WHERE has_bext = 1").fetchone()[0]
    has_ixml = conn.execute("SELECT COUNT(*) FROM files WHERE has_ixml = 1").fetchone()[0]
    ucs_named = conn.execute("SELECT COUNT(*) FROM files WHERE is_ucs = 1").fetchone()[0]

    # Unusual sample rates
    sample_rate_rows = conn.execute(
        "SELECT sample_rate, COUNT(*) as cnt FROM files WHERE sample_rate IS NOT NULL GROUP BY sample_rate ORDER BY cnt DESC"
    ).fetchall()

    unusual_sample_rates = []
    for row in sample_rate_rows:
        if row["sample_rate"] not in _STANDARD_SAMPLE_RATES:
            unusual_sample_rates.append({"sample_rate": row["sample_rate"], "count": row["cnt"]})

    # Filename issues summary
    fn_issue_rows = conn.execute(
        "SELECT issue, COUNT(*) as cnt FROM fn_issues GROUP BY issue ORDER BY cnt DESC"
    ).fetchall()
    fn_issues_by_type = {row["issue"]: row["cnt"] for row in fn_issue_rows}
    fn_issues_total = sum(fn_issues_by_type.values())

    # Scan errors detail
    error_rows = conn.execute(
        "SELECT path, scan_error FROM files WHERE scan_error IS NOT NULL LIMIT 50"
    ).fetchall()
    errors = [{"path": row["path"], "error": row["scan_error"]} for row in error_rows]

    # Bit depth distribution
    bit_depth_rows = conn.execute(
        "SELECT bit_depth, COUNT(*) as cnt FROM files WHERE bit_depth IS NOT NULL GROUP BY bit_depth ORDER BY cnt DESC"
    ).fetchall()
    bit_depths = {str(row["bit_depth"]): row["cnt"] for row in bit_depth_rows}

    # Sample rate distribution
    sample_rates = {str(row["sample_rate"]): row["cnt"] for row in sample_rate_rows}

    conn.close()

    result = {
        "total_files": total,
        "scan_errors": scan_errors,
        "missing_metadata": missing_metadata,
        "has_bext": has_bext,
        "has_ixml": has_ixml,
        "ucs_named": ucs_named,
        "unusual_sample_rates": unusual_sample_rates,
        "fn_issues_total": fn_issues_total,
        "fn_issues_by_type": fn_issues_by_type,
        "errors": errors,
        "bit_depths": bit_depths,
        "sample_rates": sample_rates,
    }

    _print_audit(result)
    return result


def _print_audit(r: dict) -> None:
    """Print audit results as Rich tables."""
    total = r["total_files"]

    table = Table(title="Library Audit Summary", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")

    table.add_row("Total indexed files", f"{total:,}")
    table.add_row("Scan errors", f"[red]{r['scan_errors']:,}[/red]" if r["scan_errors"] else "0")

    meta_pct = 100 * (total - r["missing_metadata"]) / total if total else 0
    table.add_row("Missing metadata (bext+iXML)", f"{r['missing_metadata']:,} ({100 - meta_pct:.1f}%)")
    table.add_row("Has bext", str(r["has_bext"]))
    table.add_row("Has iXML", str(r["has_ixml"]))

    ucs_pct = 100 * r["ucs_named"] / total if total else 0
    table.add_row("UCS-named", f"{r['ucs_named']:,} ({ucs_pct:.1f}%)")
    table.add_row("Filename issues", f"{r['fn_issues_total']:,}")

    console.print(table)

    if r["unusual_sample_rates"]:
        console.print("\n[yellow]Unusual sample rates:[/yellow]")
        for entry in r["unusual_sample_rates"]:
            console.print(f"  {entry['sample_rate']:,} Hz — {entry['count']:,} files")

    if r["fn_issues_by_type"]:
        issue_table = Table(title="Filename Issues by Type", show_lines=False)
        issue_table.add_column("Issue", style="yellow")
        issue_table.add_column("Count", justify="right")
        for issue, count in sorted(r["fn_issues_by_type"].items(), key=lambda x: -x[1]):
            issue_table.add_row(issue, str(count))
        console.print(issue_table)

    if r["errors"]:
        console.print(f"\n[red]Scan errors (first {len(r['errors'])}):[/red]")
        for err in r["errors"]:
            console.print(f"  [dim]{err['path']}[/dim] — {err['error']}")
