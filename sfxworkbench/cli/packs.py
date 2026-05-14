"""`sfx packs` subapp commands.

Extracted from the monolithic ``cli.py`` in the PR #6 follow-up using the
per-subapp pattern established by ``cli/metadata.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sfxworkbench.cli._shared import print_json_result, require_file, resolve_db_path

console = Console()

packs_app = typer.Typer(
    name="packs",
    help="Report duplicated or overlapping sound-library packs.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@packs_app.command("audit")
def cmd_packs_audit(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Write pack audit report JSON to this path.")] = None,
    min_files: Annotated[int, typer.Option("--min-files", help="Minimum indexed files in a folder candidate.")] = 2,
    overlap_threshold: Annotated[
        float, typer.Option("--overlap-threshold", help="Minimum smaller-folder byte coverage for overlap candidates.")
    ] = 0.95,
    max_overlap_candidates: Annotated[
        int, typer.Option("--max-overlap-candidates", help="Maximum overlap candidates to include in the report.")
    ] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report exact duplicate folders and high-overlap pack candidates."""
    from sfxworkbench.packs import audit_packs, show_pack_audit_report, write_pack_audit_report

    require_file(path, kind="path")
    if min_files < 1:
        console.print("[red]Error: --min-files must be at least 1.[/red]")
        raise typer.Exit(1)
    if not 0 < overlap_threshold <= 1:
        console.print("[red]Error: --overlap-threshold must be > 0 and <= 1.[/red]")
        raise typer.Exit(1)

    effective_db = resolve_db_path(ctx, db)
    report = audit_packs(
        path,
        db_path=effective_db,
        min_files=min_files,
        overlap_threshold=overlap_threshold,
        max_overlap_candidates=max_overlap_candidates,
    )
    if output is not None:
        write_pack_audit_report(report, output, quiet=json_output)
    elif not json_output:
        show_pack_audit_report(report)
    if json_output:
        print_json_result("packs_audit", db_path=effective_db, root=path, report_path=output, report=report)


@packs_app.command("plan")
def cmd_packs_plan(
    report: Annotated[Path, typer.Option("--report", help="Pack audit report JSON to turn into a plan.")],
    output: Annotated[Path | None, typer.Option("--output", help="Write pack consolidation plan JSON here.")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    safe_folder: Annotated[
        list[Path] | None,
        typer.Option("--safe-folder", help="Folder that pack plans must not quarantine. May be passed multiple times."),
    ] = None,
    prefer_folder: Annotated[
        list[Path] | None,
        typer.Option(
            "--prefer-folder",
            help="Prefer this folder when choosing pack keep folders. May be passed multiple times.",
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Create a reviewed pack consolidation/quarantine plan from an audit report."""
    from sfxworkbench.packs import build_pack_plan, show_pack_plan

    require_file(report, kind="report file")

    plan = build_pack_plan(
        report,
        output_path=output,
        quiet=json_output,
        config_path=config,
        safe_folders=safe_folder,
        prefer_folders=prefer_folder,
    )
    if not json_output:
        show_pack_plan(plan)
    if json_output:
        print_json_result("packs_plan", report_path=report, plan_path=output, plan=plan)


@packs_app.command("review")
def cmd_packs_review(
    plan: Annotated[Path, typer.Argument(help="Pack consolidation plan JSON to review.")],
    output: Annotated[Path | None, typer.Option("--output", help="Write reviewed plan to this path.")] = None,
    approve_all: Annotated[bool, typer.Option("--approve-all", help="Approve every pack plan group.")] = False,
    group: Annotated[
        list[int] | None, typer.Option("--approve-group", help="Approve a 1-based pack plan group number.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Mark pack plan groups as reviewed/approved."""
    from sfxworkbench.packs import review_pack_plan

    require_file(plan, kind="plan file")
    if not approve_all and not group:
        console.print("[red]Error: pass --approve-all or at least one --approve-group.[/red]")
        raise typer.Exit(1)

    result = review_pack_plan(plan, output_path=output, approve_all=approve_all, groups=group, quiet=json_output)
    if json_output:
        print_json_result("packs_review", result=result)


@packs_app.command("apply")
def cmd_packs_apply(
    plan: Annotated[Path, typer.Argument(help="Reviewed pack consolidation plan JSON.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index. Defaults to plan db_path.")] = None,
    log: Annotated[Path | None, typer.Option("--log", help="Write pack undo log to this path.")] = None,
    quarantine_dir: Annotated[
        Path | None, typer.Option("--quarantine-dir", help="Directory for quarantined pack folders.")
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    safe_folder: Annotated[
        list[Path] | None,
        typer.Option("--safe-folder", help="Folder that pack apply must not quarantine. May be passed multiple times."),
    ] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Actually quarantine folders (default is dry-run).")] = False,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Apply only approved pack plan groups.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply a reviewed pack plan by quarantining redundant folders."""
    from sfxworkbench.packs import apply_pack_plan

    require_file(plan, kind="plan file")

    result = apply_pack_plan(
        plan,
        db_path=db,
        dry_run=not apply,
        quarantine_dir=quarantine_dir,
        log_path=log,
        require_reviewed=require_reviewed,
        quiet=json_output,
        config_path=config,
        safe_folders=safe_folder,
    )
    if json_output:
        print_json_result("packs_apply", result=result)


@packs_app.command("undo")
def cmd_packs_undo(
    log: Annotated[Path, typer.Argument(help="Pack undo log to restore.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index. Defaults to log db_path.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Actually restore quarantined folders.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Undo a previously applied pack quarantine log."""
    from sfxworkbench.packs import undo_pack_log

    require_file(log, kind="log file")

    result = undo_pack_log(log, db_path=db, dry_run=not apply, quiet=json_output)
    if json_output:
        print_json_result("packs_undo", result=result)
