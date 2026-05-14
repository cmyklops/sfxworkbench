"""`sfx format` subapp commands.

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

format_app = typer.Typer(
    name="format",
    help="Report audio format consistency within related sound groups.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@format_app.command("audit")
def cmd_format_audit(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write format consistency report JSON to this path.")
    ] = None,
    min_files: Annotated[int, typer.Option("--min-files", help="Minimum related files required to inspect.")] = 2,
    limit: Annotated[int, typer.Option("--limit", help="Maximum inconsistent groups to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report mixed sample rates, bit depths, or channel counts inside related groups."""
    from sfxworkbench.format_audit import build_format_audit_report, show_format_audit_report, write_format_audit_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    effective_db = resolve_db_path(ctx, db)
    try:
        report = build_format_audit_report(path, db_path=effective_db, min_files=min_files, limit=limit)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        write_format_audit_report(report, output, quiet=json_output)
    elif not json_output:
        show_format_audit_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "format_audit",
                    "root": path,
                    "db_path": effective_db,
                    "report_path": output,
                    "report": report,
                }
            )
        )
