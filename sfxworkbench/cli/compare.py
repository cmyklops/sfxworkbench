"""`sfx compare` subapp commands.

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

compare_app = typer.Typer(
    name="compare",
    help="Compare candidate imports against an existing index.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@compare_app.command("audit")
def cmd_compare_audit(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Candidate import folder to compare.")],
    against_db: Annotated[
        Path | None, typer.Option("--against-db", help="Existing master SQLite index to compare against.")
    ] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Write compare report JSON to this path.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum entries to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report exact-hash matches before importing a new folder."""
    from sfxworkbench.compare import build_compare_report, show_compare_report, write_compare_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    effective_db = resolve_db_path(ctx, against_db)
    try:
        report = build_compare_report(path, against_db=effective_db, limit=limit)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if output is not None:
        write_compare_report(report, output, quiet=json_output)
    elif not json_output:
        show_compare_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "compare_audit",
                    "root": path,
                    "against_db": effective_db,
                    "report_path": output,
                    "report": report,
                }
            )
        )


@compare_app.command("plan")
def cmd_compare_plan(
    report: Annotated[Path, typer.Argument(help="Compare report JSON to turn into an import-review plan.")],
    output: Annotated[Path, typer.Option("--output", help="Write compare plan JSON to this path.")],
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Build a review plan from a compare report. No files are changed."""
    from sfxworkbench.compare import build_compare_plan, show_compare_plan, write_compare_plan

    if not report.exists():
        console.print(f"[red]Error: report not found: {report}[/red]")
        raise typer.Exit(1)
    plan = build_compare_plan(report)
    write_compare_plan(plan, output, quiet=json_output)
    if not json_output:
        show_compare_plan(plan)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "compare_plan",
                    "report_path": report,
                    "plan_path": output,
                    "plan": plan,
                }
            )
        )
