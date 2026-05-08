"""wavwarden CLI — sfx command entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH
from wavwarden.utils import json_dumps

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
        bool | None,
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
    log: Annotated[Path | None, typer.Option("--log", help="Write JSON removal log to this file.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Find and remove junk files (._*, .DS_Store, _wfCache/, *.reapeaks, etc.)."""
    from wavwarden.clean import clean_library

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    dry_run = not apply
    if dry_run and not json_output:
        console.print("[yellow]Dry run — pass --apply to actually remove files.[/yellow]\n")

    result = clean_library(path, dry_run=dry_run, log_path=log, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "clean", "result": result}))


# ---------------------------------------------------------------------------
# sfx scan
# ---------------------------------------------------------------------------


@app.command("scan")
def cmd_scan(
    path: Annotated[Path, typer.Argument(help="Root path of the library to scan.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    no_hash: Annotated[bool, typer.Option("--no-hash", help="Skip MD5 hashing (faster).")] = False,
    force: Annotated[bool, typer.Option("--force", help="Re-scan all files even if unchanged.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Crawl a path and index all audio files into SQLite."""
    from wavwarden.scan import scan_library

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    result = scan_library(path, db_path=db, skip_hash=no_hash, force_rescan=force, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "scan", "db_path": db, "root": path, "result": result}))


# ---------------------------------------------------------------------------
# sfx dedupe
# ---------------------------------------------------------------------------


@app.command("dedupe")
def cmd_dedupe(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    apply: Annotated[Path | None, typer.Option("--apply", help="Execute a reviewed dedupe plan JSON file.")] = None,
    review: Annotated[Path | None, typer.Option("--review", help="Mark a dedupe plan as reviewed/approved.")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Write dedupe plan to this path.")] = None,
    summary_only: Annotated[
        bool, typer.Option("--summary-only", help="Show duplicate counts without writing a plan.")
    ] = False,
    approve_all: Annotated[
        bool, typer.Option("--approve-all", help="Approve every group when used with --review.")
    ] = False,
    group: Annotated[
        list[int] | None, typer.Option("--group", help="Approve a 1-based group number when used with --review.")
    ] = None,
    quarantine_dir: Annotated[
        Path | None, typer.Option("--quarantine-dir", help="Directory for quarantined duplicates.")
    ] = None,
    permanent_delete: Annotated[
        bool, typer.Option("--delete", help="Permanently delete instead of quarantining. Advanced/destructive.")
    ] = False,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Apply only plans with approved dedupe groups.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Find duplicate files or execute a dedupe plan."""
    from wavwarden.dedupe import (
        apply_dedupe_plan,
        find_duplicates,
        review_dedupe_plan,
        show_duplicates,
        summarize_duplicates,
        write_dedupe_plan,
    )

    if review is not None:
        if not review.exists():
            console.print(f"[red]Error: plan file not found: {review}[/red]")
            raise typer.Exit(1)
        if not approve_all and not group:
            console.print("[red]Error: pass --approve-all or at least one --group with --review.[/red]")
            raise typer.Exit(1)
        result = review_dedupe_plan(
            review, output_path=output, approve_all=approve_all, groups=group, quiet=json_output
        )
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "dedupe_review", "result": result}))
        return

    if apply is not None:
        if not apply.exists():
            console.print(f"[red]Error: plan file not found: {apply}[/red]")
            raise typer.Exit(1)
        result = apply_dedupe_plan(
            apply,
            db_path=db,
            dry_run=False,
            quarantine_dir=quarantine_dir,
            permanent_delete=permanent_delete,
            require_reviewed=require_reviewed,
            quiet=json_output,
        )
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "dedupe_apply", "result": result}))
        return

    groups = find_duplicates(db)
    summary = summarize_duplicates(groups)
    show_duplicates(groups, quiet=json_output or summary_only)

    plan_path = None
    if groups and not summary_only:
        if output is not None:
            plan_path = output
        else:
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            plan_path = Path(f"dedupe_plan_{ts}.json")
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        write_dedupe_plan(groups, plan_path, db_path=db, quiet=json_output)
    elif summary_only and not json_output:
        console.print(
            f"Duplicate groups: [yellow]{summary.duplicate_groups:,}[/yellow]\n"
            f"Duplicate files: [yellow]{summary.duplicate_files:,}[/yellow]\n"
            f"Extra copies: [yellow]{summary.extra_copies:,}[/yellow]\n"
            f"Wasted bytes: [yellow]{summary.wasted_bytes:,}[/yellow] "
            f"([yellow]{summary.wasted_bytes / (1024**3):.2f} GB[/yellow])"
        )
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "dedupe",
                    "db_path": db,
                    "plan_path": plan_path,
                    "summary": summary,
                    "groups": groups,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx audit
# ---------------------------------------------------------------------------


@app.command("audit")
def cmd_audit(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Query the index for problems: missing metadata, scan errors, unusual sample rates."""
    from wavwarden.audit_cmd import run_audit

    result = run_audit(db, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "audit", "db_path": db, "result": result}))


# ---------------------------------------------------------------------------
# sfx search
# ---------------------------------------------------------------------------


@app.command("search")
def cmd_search(
    query: Annotated[str, typer.Argument(help="Full-text search query.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    limit: Annotated[int, typer.Option("--limit", help="Maximum results to return.")] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Full-text search over filenames and stems."""
    from rich.table import Table

    from wavwarden.search import search

    results = search(db, query, limit=limit)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "search", "db_path": db, "query": query, "results": results}))
        return
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
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Export the files index to CSV."""
    from wavwarden.export import export_csv

    count = export_csv(db, output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "export", "db_path": db, "output": output, "count": count}))
    else:
        console.print(f"Exported [yellow]{count:,}[/yellow] rows to [cyan]{output}[/cyan]")


# ---------------------------------------------------------------------------
# sfx rename
# ---------------------------------------------------------------------------


@app.command("rename")
def cmd_rename(
    path: Annotated[Path | None, typer.Argument(help="Root path of the library to rename.")] = None,
    pattern: Annotated[str, typer.Option("--pattern", help="Rename pattern. Currently only 'ucs'.")] = "ucs",
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    apply: Annotated[bool, typer.Option("--apply", help="Actually rename files (default is dry-run).")] = False,
    log: Annotated[Path | None, typer.Option("--log", help="Write/read rename log path.")] = None,
    undo: Annotated[Path | None, typer.Option("--undo", help="Undo a previous rename log.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Bulk UCS rename with preview, apply, collision detection, and undo."""
    from wavwarden.rename import apply_rename_plan, build_rename_plan, show_rename_plan, undo_rename_log

    if undo is not None:
        result = undo_rename_log(undo, db_path=db, dry_run=not apply, quiet=json_output)
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "rename_undo", "result": result}))
        return

    if path is None:
        console.print("[red]Error: PATH is required unless --undo is provided.[/red]")
        raise typer.Exit(1)
    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    plan = build_rename_plan(path, pattern=pattern)
    if not apply:
        if not json_output:
            console.print("[yellow]Dry run — pass --apply to actually rename files.[/yellow]\n")
            show_rename_plan(plan)
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "rename", "plan": plan}))
        return

    result = apply_rename_plan(plan, db_path=db, log_path=log, dry_run=False, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "rename_apply", "result": result, "plan": plan}))


if __name__ == "__main__":
    app()
