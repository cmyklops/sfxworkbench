"""`sfx maintenance` subapp commands.

Currently exposes the ``clean-backups`` sweep that removes sibling
``.original-<stamp>Z`` files produced by ``sfxworkbench.backups``. As more
maintenance chores (orphan removal, stale plan cleanup, etc.) accumulate
they'll join this subapp.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from sfxworkbench.artifacts import default_artifact_search_paths, sync_artifacts_from_paths
from sfxworkbench.backups import clean_backups
from sfxworkbench.cli._shared import resolve_db_path
from sfxworkbench.utils import fmt_bytes, json_dumps

console = Console()

maintenance_app = typer.Typer(
    name="maintenance",
    help="Periodic housekeeping for sfxworkbench-produced artifacts.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

artifacts_app = typer.Typer(
    name="artifacts",
    help="Maintain the SQLite registry of generated JSON artifacts.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
maintenance_app.add_typer(artifacts_app, name="artifacts")


@maintenance_app.command("clean-backups")
def cmd_maintenance_clean_backups(
    root: Annotated[Path, typer.Argument(help="Library root to sweep for sibling .original-* backups.")],
    older_than_days: Annotated[
        int,
        typer.Option(
            "--older-than-days",
            help="Backup files older than this many days are eligible for deletion. 0 removes every backup.",
        ),
    ] = 30,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Actually delete eligible backups. Default is dry-run."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Remove ``.original-<stamp>Z`` sibling backups older than the cutoff. Defaults to dry-run."""
    if not root.exists():
        console.print(f"[red]Error: path not found: {root}[/red]")
        raise typer.Exit(1)
    if older_than_days < 0:
        console.print("[red]Error: --older-than-days must be 0 or greater.[/red]")
        raise typer.Exit(1)

    result = clean_backups(root, older_than_days=older_than_days, dry_run=not apply)

    if not json_output:
        table = Table(title="Clean backups", show_lines=False)
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        verb = "Would remove" if result.dry_run else "Removed"
        table.add_row("Scanned", f"{result.scanned:,}")
        table.add_row(verb, f"{result.removed:,}")
        table.add_row("Kept (newer than cutoff)", f"{result.kept:,}")
        table.add_row("Freed", fmt_bytes(result.bytes_freed))
        console.print(table)
        if result.dry_run and result.removed:
            console.print("[dim]Pass [bold]--apply[/bold] to actually delete the eligible backups.[/dim]")

    if json_output:
        assert result.removed_paths is not None
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "maintenance_clean_backups",
                    "root": str(root),
                    "older_than_days": older_than_days,
                    "dry_run": result.dry_run,
                    "scanned": result.scanned,
                    "removed": result.removed,
                    "kept": result.kept,
                    "bytes_freed": result.bytes_freed,
                    "removed_paths": [str(p) for p in result.removed_paths],
                }
            )
        )


@artifacts_app.command("sync")
def cmd_maintenance_artifacts_sync(
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    report: Annotated[
        list[Path] | None,
        typer.Option("--report", help="Report directory or JSON file to index. May be passed more than once."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Rebuild/update the SQLite artifact registry from generated JSON files."""
    effective_db = resolve_db_path(ctx, db)
    paths = list(report or default_artifact_search_paths(effective_db))
    result = sync_artifacts_from_paths(effective_db, paths, materialize=True)

    if not json_output:
        table = Table(title="Artifact registry sync", show_lines=False)
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Scanned", f"{result.scanned:,}")
        table.add_row("Registered", f"{result.registered:,}")
        table.add_row("Updated", f"{result.updated:,}")
        table.add_row("Unchanged", f"{result.unchanged:,}")
        table.add_row("Missing", f"{result.missing:,}")
        table.add_row("Errors", f"{result.errors:,}")
        console.print(table)

    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "maintenance_artifacts_sync",
                    "db_path": effective_db,
                    "report_paths": paths,
                    "result": result.__dict__,
                }
            )
        )
