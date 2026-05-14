"""`sfx groups` subapp commands.

Extracted from the monolithic ``cli.py`` in the PR #6 follow-up using the
per-subapp pattern established by ``cli/metadata.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sfxworkbench.cli._shared import resolve_db_path
from sfxworkbench.utils import json_dumps

console = Console()

groups_app = typer.Typer(
    name="groups",
    help="Report related sound groups inferred from filenames.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@groups_app.command("audit")
def cmd_groups_audit(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write related groups report JSON to this path.")
    ] = None,
    min_files: Annotated[int, typer.Option("--min-files", help="Minimum files required to report a group.")] = 2,
    limit: Annotated[int, typer.Option("--limit", help="Maximum groups to include; 0 writes all groups.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report obvious related sounds such as numbered takes and channel sets."""
    from sfxworkbench.groups import audit_related_groups, show_related_groups_report, write_related_groups_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    effective_db = resolve_db_path(ctx, db)
    try:
        report = audit_related_groups(path, db_path=effective_db, min_files=min_files, limit=limit)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        write_related_groups_report(report, output, quiet=json_output)
    elif not json_output:
        show_related_groups_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "groups_audit",
                    "root": path,
                    "db_path": effective_db,
                    "report_path": output,
                    "report": report,
                }
            )
        )
