"""`sfx metadata` subapp commands.

Extracted from the monolithic ``cli.py`` in PR #6 as the first per-subapp
module. The pattern established here — a self-contained Typer instance plus
its command decorations, importable in isolation — is the template for
incrementally extracting the remaining 12 subapps in follow-up PRs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sfxworkbench.cli._shared import print_json_result, require_file, resolve_db_path

console = Console()

metadata_app = typer.Typer(
    name="metadata",
    help="Report metadata coverage and sample-rate hygiene.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@metadata_app.command("audit")
def cmd_metadata_audit(
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write metadata audit report JSON to this path.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum rows per report section; 0 writes all rows.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report files missing BWF/iXML metadata and files with unusual sample rates."""
    from sfxworkbench.metadata_audit import (
        build_metadata_audit_report,
        show_metadata_audit_report,
        write_metadata_audit_report,
    )

    try:
        effective_db = resolve_db_path(ctx, db)
        report = build_metadata_audit_report(effective_db, limit=limit)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        write_metadata_audit_report(report, output, quiet=json_output)
    elif not json_output:
        show_metadata_audit_report(report)
    if json_output:
        print_json_result("metadata_audit", db_path=effective_db, report_path=output, report=report)


@metadata_app.command("view")
def cmd_metadata_view(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Indexed path, filename, stem, or path fragment to inspect.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    catalog: Annotated[Path | None, typer.Option("--catalog", help="Override the UCS catalog discovery chain.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum matching files to show.")] = 5,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Show indexed metadata, UCS provenance, and DB-only tags for matching files."""
    from sfxworkbench.metadata_view import build_metadata_view_report, show_metadata_view_report

    try:
        effective_db = resolve_db_path(ctx, db)
        report = build_metadata_view_report(query, db_path=effective_db, catalog_path=catalog, limit=limit)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if not json_output:
        show_metadata_view_report(report)
    if json_output:
        print_json_result("metadata_view", db_path=effective_db, query=query, report=report)


@metadata_app.command("backends")
def cmd_metadata_backends(
    bwfmetaedit: Annotated[
        Path | None,
        typer.Option("--bwfmetaedit", help="Explicit path to the BWF MetaEdit CLI executable."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report installed metadata write backends. No audio files are modified."""
    from sfxworkbench.metadata_backends import build_metadata_backends_report, show_metadata_backends_report

    report = build_metadata_backends_report(bwfmetaedit=bwfmetaedit)
    if not json_output:
        show_metadata_backends_report(report)
    if json_output:
        print_json_result("metadata_backends", bwfmetaedit=bwfmetaedit, report=report)


@metadata_app.command("write-plan")
def cmd_metadata_write_plan(
    ctx: typer.Context,
    output: Annotated[Path, typer.Argument(help="Output embedded metadata write plan JSON path.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    path: Annotated[Path | None, typer.Option("--path", help="Optional indexed library root to include.")] = None,
    backend: Annotated[
        str, typer.Option("--backend", help="Metadata writer backend to plan for: auto, bwfmetaedit, or mutagen.")
    ] = "auto",
    bwfmetaedit: Annotated[
        Path | None,
        typer.Option("--bwfmetaedit", help="Explicit path to the BWF MetaEdit CLI executable."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum accepted tag entries to include; 0 writes all.")] = 0,
    replace_existing: Annotated[
        bool,
        typer.Option(
            "--replace-existing",
            help=(
                "Plan explicit reviewed replacements for non-empty existing BWF fields. "
                "Default preserves existing embedded metadata."
            ),
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Build a reviewed dry-run plan for future embedded metadata writes."""
    from sfxworkbench.metadata_write import (
        build_metadata_write_plan,
        show_metadata_write_plan,
        write_metadata_write_plan,
    )

    effective_db = resolve_db_path(ctx, db)
    try:
        plan = build_metadata_write_plan(
            db_path=effective_db,
            root=path,
            backend=backend,
            bwfmetaedit=bwfmetaedit,
            limit=limit,
            replace_existing=replace_existing,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    plan_path = write_metadata_write_plan(plan, output, quiet=json_output)
    if not json_output:
        show_metadata_write_plan(plan)
    if json_output:
        print_json_result("metadata_write_plan", db_path=effective_db, root=path, plan_path=plan_path, plan=plan)


@metadata_app.command("write-review")
def cmd_metadata_write_review(
    plan: Annotated[Path, typer.Argument(help="Embedded metadata write plan JSON to review.")],
    output: Annotated[Path | None, typer.Option("--output", help="Write reviewed plan to this path.")] = None,
    approve_all: Annotated[bool, typer.Option("--approve-all", help="Approve every write plan entry.")] = False,
    entry: Annotated[list[int] | None, typer.Option("--entry", help="Approve a 1-based entry id.")] = None,
    reject_entry: Annotated[list[int] | None, typer.Option("--reject-entry", help="Reject a 1-based entry id.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Mark embedded metadata write plan entries as approved or rejected."""
    from sfxworkbench.metadata_write import review_metadata_write_plan

    require_file(plan, kind="plan file")
    if not approve_all and not entry and not reject_entry:
        console.print("[red]Error: pass --approve-all, --entry, or --reject-entry.[/red]")
        raise typer.Exit(1)
    result = review_metadata_write_plan(
        plan,
        output_path=output,
        approve_all=approve_all,
        entries=entry,
        reject_entries=reject_entry,
        quiet=json_output,
    )
    if result.invalid_entries:
        raise typer.Exit(1)
    if json_output:
        print_json_result("metadata_write_review", plan_path=plan, output_path=output or plan, result=result)


@metadata_app.command("write-preview")
def cmd_metadata_write_preview(
    plan: Annotated[Path, typer.Argument(help="Reviewed embedded metadata write plan JSON to validate.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index. Defaults to plan db_path.")] = None,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Only count approved write plan entries.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Preview a reviewed embedded metadata write plan. No audio files are modified."""
    from sfxworkbench.metadata_write import preview_metadata_write_plan

    require_file(plan, kind="plan file")
    result = preview_metadata_write_plan(plan, db_path=db, require_reviewed=require_reviewed, quiet=json_output)
    if json_output:
        print_json_result("metadata_write_preview", plan_path=plan, db_path=db, result=result)


@metadata_app.command("write-fixtures")
def cmd_metadata_write_fixtures(
    plan: Annotated[Path, typer.Argument(help="Reviewed embedded metadata write plan JSON to fixture.")],
    output_dir: Annotated[Path, typer.Argument(help="Directory for copied audio fixtures and manifest.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index. Defaults to plan db_path.")] = None,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Only include approved write plan entries.")
    ] = True,
    write_fixture_metadata: Annotated[
        bool,
        typer.Option(
            "--write-fixture-metadata",
            help=(
                "Apply supported metadata writes to copied fixture files using Mutagen or BWF MetaEdit. "
                "Original audio files are not modified."
            ),
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Copy reviewed write targets to a fixture bundle. Original audio files are not modified."""
    from sfxworkbench.metadata_write import build_metadata_write_fixture_bundle

    require_file(plan, kind="plan file")
    bundle = build_metadata_write_fixture_bundle(
        plan,
        output_dir,
        db_path=db,
        require_reviewed=require_reviewed,
        write_fixture_metadata=write_fixture_metadata,
        quiet=json_output,
    )
    if json_output:
        print_json_result(
            "metadata_write_fixtures",
            plan_path=plan,
            output_dir=output_dir,
            write_fixture_metadata=write_fixture_metadata,
            bundle=bundle,
        )


@metadata_app.command("write-readback")
def cmd_metadata_write_readback(
    manifest: Annotated[
        Path,
        typer.Argument(help="Metadata write fixture manifest path, or a fixture bundle directory."),
    ],
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Compare copied fixture metadata against the fixture manifest. No files are modified."""
    from sfxworkbench.metadata_write import compare_metadata_write_fixture_readback

    require_file(manifest, kind="fixture manifest or directory")
    try:
        report = compare_metadata_write_fixture_readback(manifest, quiet=json_output)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print_json_result("metadata_write_readback", manifest_path=manifest, report=report)


@metadata_app.command("write-apply")
def cmd_metadata_write_apply(
    plan: Annotated[Path, typer.Argument(help="Reviewed embedded metadata write plan JSON to apply.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index. Defaults to plan db_path.")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Only apply approved write plan entries.")
    ] = True,
    backup_dir: Annotated[
        Path | None,
        typer.Option(
            "--backup-dir",
            help=(
                "Legacy: copy backups into this directory mirroring source paths. "
                "When omitted (the default), ExifTool-style sibling .original-<stamp>Z "
                "files are written next to each source instead."
            ),
        ),
    ] = None,
    no_backup: Annotated[
        bool,
        typer.Option(
            "--no-backup",
            help=(
                "Skip backups entirely. WARNING: readback-mismatch restore is "
                "unavailable in this mode. Requires --yes to confirm the safety bypass."
            ),
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Acknowledge the --no-backup safety bypass. Required when --apply --no-backup are combined.",
        ),
    ] = False,
    log: Annotated[Path | None, typer.Option("--log", help="Write an apply log JSON to this path.")] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Actually write metadata to original files. Default is dry-run.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply reviewed Mutagen tag writes and BWF MetaEdit BEXT writes."""
    from sfxworkbench.metadata_write import apply_metadata_write_plan

    require_file(plan, kind="plan file")
    # Safety gate: combining --apply with --no-backup removes the readback-mismatch
    # rollback path. Require explicit --yes so the bypass is intentional, never a typo.
    if apply and no_backup and not yes:
        console.print(
            "[red]Error: --apply --no-backup removes the readback rollback safety net. Add --yes to acknowledge.[/red]"
        )
        raise typer.Exit(1)
    result = apply_metadata_write_plan(
        plan,
        db_path=db,
        require_reviewed=require_reviewed,
        dry_run=not apply,
        backup_dir=backup_dir,
        backup=not no_backup,
        log_path=log,
        quiet=json_output,
        config_path=config,
    )
    if json_output:
        print_json_result("metadata_write_apply", plan_path=plan, db_path=db, result=result)


@metadata_app.command("write-undo")
def cmd_metadata_write_undo(
    log: Annotated[Path, typer.Argument(help="Metadata write apply log JSON to undo.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index. Defaults to log db_path.")] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Actually restore files from backups. Default is dry-run.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Restore files from a metadata write apply log."""
    from sfxworkbench.metadata_write import undo_metadata_write_apply_log

    require_file(log, kind="apply log")
    result = undo_metadata_write_apply_log(log, db_path=db, dry_run=not apply, quiet=json_output)
    if json_output:
        print_json_result("metadata_write_undo", log_path=log, db_path=db, result=result)
