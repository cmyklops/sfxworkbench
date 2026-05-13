"""`sfx delete` subapp commands.

Extracted from the monolithic ``cli.py`` in the PR #6 follow-up using the
per-subapp pattern established by ``cli/metadata.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sfxworkbench.utils import json_dumps

console = Console()

delete_app = typer.Typer(
    name="delete",
    help="Reviewed permanent deletion from quarantine logs.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@delete_app.command("plan")
def cmd_delete_plan(
    quarantine_log: Annotated[
        Path, typer.Argument(help="sfxworkbench quarantine log JSON to plan permanent deletion from.")
    ],
    output: Annotated[Path, typer.Option("--output", help="Write delete plan JSON to this path.")],
    config: Annotated[
        Path | None, typer.Option("--config", help="Optional sfxworkbench JSON config with safe folders.")
    ] = None,
    safe_folder: Annotated[
        list[Path] | None, typer.Option("--safe-folder", help="Folder that must not be deleted.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Build a reviewed permanent-delete plan from quarantine logs only."""
    from sfxworkbench.delete import build_delete_plan, show_delete_plan, write_delete_plan

    if not quarantine_log.exists():
        console.print(f"[red]Error: quarantine log not found: {quarantine_log}[/red]")
        raise typer.Exit(1)
    plan = build_delete_plan(quarantine_log, config_path=config, safe_folders=safe_folder)
    write_delete_plan(plan, output, quiet=json_output)
    if not json_output:
        show_delete_plan(plan)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "delete_plan",
                    "source_log": quarantine_log,
                    "plan_path": output,
                    "plan": plan,
                }
            )
        )


@delete_app.command("review")
def cmd_delete_review(
    plan: Annotated[Path, typer.Argument(help="Delete plan JSON to review.")],
    output: Annotated[Path | None, typer.Option("--output", help="Write reviewed delete plan to this path.")] = None,
    approve_all: Annotated[bool, typer.Option("--approve-all", help="Approve every delete plan entry.")] = False,
    entry: Annotated[list[int] | None, typer.Option("--entry", help="Approve one entry id.")] = None,
    reject_entry: Annotated[list[int] | None, typer.Option("--reject-entry", help="Reject one entry id.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Mark permanent-delete entries as approved or rejected."""
    from sfxworkbench.delete import review_delete_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)
    if not approve_all and not entry and not reject_entry:
        console.print("[red]Error: pass --approve-all, --entry, or --reject-entry.[/red]")
        raise typer.Exit(1)
    result = review_delete_plan(
        plan, output_path=output, approve_all=approve_all, entries=entry, reject_entries=reject_entry, quiet=json_output
    )
    if result.invalid_entries:
        raise typer.Exit(1)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "delete_review", "plan_path": plan, "result": result}))


@delete_app.command("apply")
def cmd_delete_apply(
    plan: Annotated[Path, typer.Argument(help="Reviewed delete plan JSON to apply.")],
    apply: Annotated[bool, typer.Option("--apply", help="Actually delete approved quarantine paths.")] = False,
    require_reviewed: Annotated[bool, typer.Option("--require-reviewed", help="Only delete approved entries.")] = False,
    understand: Annotated[
        bool,
        typer.Option("--i-understand-permanent-delete", help="Required confirmation for irreversible deletion."),
    ] = False,
    log: Annotated[Path | None, typer.Option("--log", help="Write immutable delete log JSON to this path.")] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="Optional sfxworkbench JSON config with safe folders.")
    ] = None,
    safe_folder: Annotated[
        list[Path] | None, typer.Option("--safe-folder", help="Folder that must not be deleted.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply a reviewed permanent-delete plan. Defaults to dry-run."""
    from sfxworkbench.delete import apply_delete_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)
    result = apply_delete_plan(
        plan,
        dry_run=not apply,
        require_reviewed=require_reviewed,
        understand_permanent_delete=understand,
        log_path=log,
        config_path=config,
        safe_folders=safe_folder,
        quiet=json_output,
    )
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "delete_apply", "plan_path": plan, "result": result}))
