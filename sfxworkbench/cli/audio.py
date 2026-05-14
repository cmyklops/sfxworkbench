"""`sfx audio` subapp commands.

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

audio_app = typer.Typer(
    name="audio",
    help="Advanced audio maintenance workflows.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

dual_mono_app = typer.Typer(
    name="dual-mono",
    help="Detect and copy-convert dual-mono stereo files.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
audio_app.add_typer(dual_mono_app, name="dual-mono")


@dual_mono_app.command("audit")
def cmd_dual_mono_audit(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the indexed library to inspect.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Write dual-mono report JSON to this path.")] = None,
    threshold: Annotated[
        float, typer.Option("--threshold", help="Maximum channel difference for near-exact matches.")
    ] = 0.000001,
    limit: Annotated[int, typer.Option("--limit", help="Maximum entries to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report likely dual-mono stereo files. No files are changed."""
    from sfxworkbench.dual_mono import build_dual_mono_report, show_dual_mono_report, write_dual_mono_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    effective_db = resolve_db_path(ctx, db)
    try:
        report = build_dual_mono_report(path, db_path=effective_db, threshold=threshold, limit=limit)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if output is not None:
        write_dual_mono_report(report, output, quiet=json_output)
    elif not json_output:
        show_dual_mono_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "dual_mono_audit",
                    "root": path,
                    "db_path": effective_db,
                    "report_path": output,
                    "report": report,
                }
            )
        )


@dual_mono_app.command("plan")
def cmd_dual_mono_plan(
    report: Annotated[Path, typer.Argument(help="Dual-mono report JSON to plan from.")],
    output: Annotated[Path, typer.Option("--output", help="Write dual-mono conversion plan JSON to this path.")],
    config: Annotated[
        Path | None, typer.Option("--config", help="Optional sfxworkbench JSON config with safe folders.")
    ] = None,
    safe_folder: Annotated[
        list[Path] | None, typer.Option("--safe-folder", help="Protected folder to block conversion.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Build a reviewed copy-output dual-mono conversion plan."""
    from sfxworkbench.dual_mono import build_dual_mono_plan, show_dual_mono_plan, write_dual_mono_plan

    if not report.exists():
        console.print(f"[red]Error: report file not found: {report}[/red]")
        raise typer.Exit(1)
    plan = build_dual_mono_plan(report, config_path=config, safe_folders=safe_folder)
    write_dual_mono_plan(plan, output, quiet=json_output)
    if not json_output:
        show_dual_mono_plan(plan)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "dual_mono_plan",
                    "report_path": report,
                    "plan_path": output,
                    "plan": plan,
                }
            )
        )


@dual_mono_app.command("review")
def cmd_dual_mono_review(
    plan: Annotated[Path, typer.Argument(help="Dual-mono plan JSON to review.")],
    output: Annotated[Path | None, typer.Option("--output", help="Write reviewed plan to this path.")] = None,
    approve_all: Annotated[bool, typer.Option("--approve-all", help="Approve every dual-mono plan entry.")] = False,
    group: Annotated[list[int] | None, typer.Option("--approve-group", help="Approve one group id.")] = None,
    reject_group: Annotated[list[int] | None, typer.Option("--reject-group", help="Reject one group id.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Mark dual-mono conversion entries as approved or rejected."""
    from sfxworkbench.dual_mono import review_dual_mono_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)
    if not approve_all and not group and not reject_group:
        console.print("[red]Error: pass --approve-all, --approve-group, or --reject-group.[/red]")
        raise typer.Exit(1)
    result = review_dual_mono_plan(
        plan,
        output_path=output,
        approve_all=approve_all,
        groups=group,
        reject_groups=reject_group,
        quiet=json_output,
    )
    if result.invalid_entries:
        raise typer.Exit(1)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "dual_mono_review", "plan_path": plan, "result": result}))


@dual_mono_app.command("apply")
def cmd_dual_mono_apply(
    plan: Annotated[Path, typer.Argument(help="Reviewed dual-mono plan JSON to apply.")],
    output_root: Annotated[Path, typer.Option("--output-root", help="Root folder for copied mono output files.")],
    apply: Annotated[bool, typer.Option("--apply", help="Write copied mono files to --output-root.")] = False,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Only convert approved entries.")
    ] = False,
    log: Annotated[Path | None, typer.Option("--log", help="Write conversion log JSON to this path.")] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="Optional sfxworkbench JSON config with safe folders.")
    ] = None,
    safe_folder: Annotated[
        list[Path] | None, typer.Option("--safe-folder", help="Protected folder to block conversion.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Copy approved dual-mono stereo files as mono files. Originals are preserved."""
    from sfxworkbench.dual_mono import apply_dual_mono_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)
    result = apply_dual_mono_plan(
        plan,
        output_root=output_root,
        dry_run=not apply,
        require_reviewed=require_reviewed,
        log_path=log,
        config_path=config,
        safe_folders=safe_folder,
        quiet=json_output,
    )
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "dual_mono_apply", "plan_path": plan, "result": result}))
