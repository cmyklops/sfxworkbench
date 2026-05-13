"""`sfx organize` subapp commands.

Extracted from the monolithic ``cli.py`` in the PR #6 follow-up using the
per-subapp pattern established by ``cli/metadata.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sfxworkbench.db import DEFAULT_DB_PATH
from sfxworkbench.utils import json_dumps

console = Console()

organize_app = typer.Typer(
    name="organize",
    help="Preview safe folder-structure organization.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@organize_app.command("audit")
def cmd_organize_audit(
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    pattern: Annotated[
        str,
        typer.Option(
            "--pattern",
            help=(
                "Organization pattern. Supported: 'strip-leading-numbers', "
                "'common-prefix-folders', 'numeric-series-folders', "
                "'vendor-product-folders', 'redundant-nesting'."
            ),
        ),
    ] = "strip-leading-numbers",
    depth: Annotated[int, typer.Option("--depth", help="Folder depth under PATH to inspect.")] = 1,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write organization preview JSON to this path.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Preview safe folder-structure organization without changing files."""
    from sfxworkbench.organize import audit_organization, show_organize_audit_report, write_organize_audit_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    if depth < 1:
        console.print("[red]Error: --depth must be at least 1.[/red]")
        raise typer.Exit(1)

    try:
        report = audit_organization(path, pattern=pattern, depth=depth, config_path=config)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        write_organize_audit_report(report, output, quiet=json_output)
    elif not json_output:
        show_organize_audit_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "organize_audit",
                    "root": path,
                    "report_path": output,
                    "report": report,
                }
            )
        )


@organize_app.command("review")
def cmd_organize_review(
    report: Annotated[Path, typer.Argument(help="Organization report JSON to review.")],
    output: Annotated[Path | None, typer.Option("--output", help="Write reviewed report to this path.")] = None,
    approve_all: Annotated[bool, typer.Option("--approve-all", help="Approve every organization entry.")] = False,
    entry: Annotated[list[int] | None, typer.Option("--entry", help="Approve a 1-based entry number.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Mark organization preview entries as reviewed/approved."""
    from sfxworkbench.organize import review_organize_report

    if not report.exists():
        console.print(f"[red]Error: report file not found: {report}[/red]")
        raise typer.Exit(1)
    if not approve_all and not entry:
        console.print("[red]Error: pass --approve-all or at least one --entry.[/red]")
        raise typer.Exit(1)

    result = review_organize_report(
        report, output_path=output, approve_all=approve_all, entries=entry, quiet=json_output
    )
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "organize_review", "result": result}))


@organize_app.command("nesting-plan")
def cmd_organize_nesting_plan(
    report: Annotated[Path, typer.Argument(help="Redundant nesting audit report JSON.")],
    output: Annotated[Path, typer.Option("--output", help="Write reviewed nesting plan JSON to this path.")],
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help=(
                "Candidate kind to plan. Supported: 'repeated_folder_name', 'single_child_chain', 'low_value_wrapper'."
            ),
        ),
    ] = "repeated_folder_name",
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Create a safe flatten plan from repeated-folder-name candidates."""
    from sfxworkbench.organize import build_nesting_plan_from_report, show_nesting_plan

    if not report.exists():
        console.print(f"[red]Error: report file not found: {report}[/red]")
        raise typer.Exit(1)

    plan = build_nesting_plan_from_report(report, kind=kind, output_path=output, quiet=json_output, config_path=config)
    if not json_output:
        show_nesting_plan(plan)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "organize_nesting_plan",
                    "report_path": report,
                    "plan_path": output,
                    "plan": plan,
                }
            )
        )


@organize_app.command("nesting-apply")
def cmd_organize_nesting_apply(
    plan: Annotated[Path, typer.Argument(help="Reviewed nesting flatten plan JSON.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    log: Annotated[Path | None, typer.Option("--log", help="Write nesting undo log to this path.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Actually flatten folders (default is dry-run).")] = False,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Apply only approved nesting plan entries.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply a reviewed repeated-folder flatten plan."""
    from sfxworkbench.organize import apply_nesting_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)

    result = apply_nesting_plan(
        plan,
        db_path=db,
        log_path=log,
        require_reviewed=require_reviewed,
        dry_run=not apply,
        quiet=json_output,
        config_path=config,
    )
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "organize_nesting_apply", "result": result}))


@organize_app.command("nesting-undo")
def cmd_organize_nesting_undo(
    log: Annotated[Path, typer.Argument(help="Nesting undo log to restore.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    apply: Annotated[bool, typer.Option("--apply", help="Actually undo nesting flatten operations.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Undo a previously applied nesting flatten log."""
    from sfxworkbench.organize import undo_nesting_log

    if not log.exists():
        console.print(f"[red]Error: log file not found: {log}[/red]")
        raise typer.Exit(1)

    result = undo_nesting_log(log, db_path=db, dry_run=not apply, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "organize_nesting_undo", "result": result}))


@organize_app.command("apply")
def cmd_organize_apply(
    report: Annotated[Path, typer.Argument(help="Reviewed organization report JSON to apply.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    log: Annotated[Path | None, typer.Option("--log", help="Write organization undo log to this path.")] = None,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Apply only approved organization entries.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply approved folder organization entries and write an undo log."""
    from sfxworkbench.organize import apply_organize_report

    if not report.exists():
        console.print(f"[red]Error: report file not found: {report}[/red]")
        raise typer.Exit(1)

    result = apply_organize_report(
        report, db_path=db, log_path=log, require_reviewed=require_reviewed, quiet=json_output, config_path=config
    )
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "organize_apply", "result": result}))


@organize_app.command("undo")
def cmd_organize_undo(
    log: Annotated[Path, typer.Argument(help="Organization undo log to restore.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    apply: Annotated[bool, typer.Option("--apply", help="Actually undo renames (default is dry-run).")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Undo a previously applied folder organization log."""
    from sfxworkbench.organize import undo_organize_log

    if not log.exists():
        console.print(f"[red]Error: log file not found: {log}[/red]")
        raise typer.Exit(1)

    result = undo_organize_log(log, db_path=db, dry_run=not apply, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "organize_undo", "result": result}))
