"""wavwarden CLI — sfx command entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH

app = typer.Typer(
    name="sfx",
    help="Sound library hygiene — audit, clean, deduplicate, scan, search.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()

# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------

def _version_callback(value: bool) -> None:
    if value:
        console.print(f"wavwarden {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    """sfx — sound library hygiene toolkit."""


# ---------------------------------------------------------------------------
# sfx clean
# ---------------------------------------------------------------------------

@app.command("clean")
def cmd_clean(
    path: Annotated[Path, typer.Argument(help="Root path of the library to clean.")],
    apply: Annotated[bool, typer.Option("--apply", help="Actually remove files (default is dry-run).")] = False,
    log: Annotated[Optional[Path], typer.Option("--log", help="Write JSON removal log to this file.")] = None,
) -> None:
    """Find and remove junk files (._*, .DS_Store, _wfCache/, *.reapeaks, etc.)."""
    from wavwarden.clean import clean_library

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    dry_run = not apply
    if dry_run:
        console.print("[yellow]Dry run — pass --apply to actually remove files.[/yellow]\n")

    clean_library(path, dry_run=dry_run, log_path=log)


# ---------------------------------------------------------------------------
# sfx scan
# ---------------------------------------------------------------------------

@app.command("scan")
def cmd_scan(
    path: Annotated[Path, typer.Argument(help="Root path of the library to scan.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    no_hash: Annotated[bool, typer.Option("--no-hash", help="Skip MD5 hashing (faster).")] = False,
    force: Annotated[bool, typer.Option("--force", help="Re-scan all files even if unchanged.")] = False,
) -> None:
    """Crawl a path and index all audio files into SQLite."""
    from wavwarden.scan import scan_library

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    scan_library(path, db_path=db, skip_hash=no_hash, force_rescan=force)


# ---------------------------------------------------------------------------
# sfx dedupe
# ---------------------------------------------------------------------------

@app.command("dedupe")
def cmd_dedupe(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    apply: Annotated[Optional[Path], typer.Option("--apply", help="Execute a reviewed dedupe plan JSON file.")] = None,
) -> None:
    """Find duplicate files or execute a dedupe plan."""
    from wavwarden.dedupe import find_duplicates, show_duplicates, write_dedupe_plan, apply_dedupe_plan

    if apply is not None:
        if not apply.exists():
            console.print(f"[red]Error: plan file not found: {apply}[/red]")
            raise typer.Exit(1)
        apply_dedupe_plan(apply, dry_run=False)
        return

    groups = find_duplicates(db)
    show_duplicates(groups)

    if groups:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_path = Path(f"dedupe_plan_{ts}.json")
        write_dedupe_plan(groups, plan_path)


# ---------------------------------------------------------------------------
# sfx audit
# ---------------------------------------------------------------------------

@app.command("audit")
def cmd_audit(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
) -> None:
    """Query the index for problems: missing metadata, scan errors, unusual sample rates."""
    from wavwarden.audit_cmd import run_audit
    run_audit(db)


# ---------------------------------------------------------------------------
# sfx search
# ---------------------------------------------------------------------------

@app.command("search")
def cmd_search(
    query: Annotated[str, typer.Argument(help="Full-text search query.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    limit: Annotated[int, typer.Option("--limit", help="Maximum results to return.")] = 50,
) -> None:
    """Full-text search over filenames and stems."""
    from rich.table import Table
    from wavwarden.search import search

    results = search(db, query, limit=limit)
    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search: {query!r} ({len(results)} results)", show_lines=False)
    table.add_column("Filename", style="white")
    table.add_column("Ext", style="cyan", no_wrap=True)
    table.add_column("SR", justify="right")
    table.add_column("Bit", justify="right")
    table.add_column("Ch", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("UCS", justify="center")

    for row in results:
        table.add_row(
            row["filename"],
            row["extension"] or "",
            str(row["sample_rate"]) if row["sample_rate"] else "",
            str(row["bit_depth"]) if row["bit_depth"] else "",
            str(row["channels"]) if row["channels"] else "",
            f"{row['duration_s']:.1f}s" if row["duration_s"] else "",
            "✓" if row["is_ucs"] else "",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# sfx export
# ---------------------------------------------------------------------------

@app.command("export")
def cmd_export(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    output: Annotated[Path, typer.Option("--output", help="Output CSV file path.")] = Path("library.csv"),
) -> None:
    """Export the files index to CSV."""
    from wavwarden.export import export_csv

    count = export_csv(db, output)
    console.print(f"Exported [yellow]{count:,}[/yellow] rows to [cyan]{output}[/cyan]")


if __name__ == "__main__":
    app()
