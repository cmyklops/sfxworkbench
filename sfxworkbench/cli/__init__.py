"""sfxworkbench CLI — sfx command entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.cli._shared import resolve_db_path
from sfxworkbench.cli.audio import audio_app
from sfxworkbench.cli.compare import compare_app
from sfxworkbench.cli.config_cmd import config_app
from sfxworkbench.cli.delete import delete_app
from sfxworkbench.cli.format import format_app
from sfxworkbench.cli.groups import groups_app
from sfxworkbench.cli.ls import ls as cmd_ls
from sfxworkbench.cli.maintenance import maintenance_app
from sfxworkbench.cli.metadata import metadata_app
from sfxworkbench.cli.organize import organize_app
from sfxworkbench.cli.packs import packs_app
from sfxworkbench.cli.similarity import similarity_app
from sfxworkbench.cli.tag import tag_app
from sfxworkbench.cli.ucs import ucs_app
from sfxworkbench.config import ConfigError, load_config
from sfxworkbench.utils import json_dumps

app = typer.Typer(
    name="sfx",
    help="Sound library hygiene — audit, clean, deduplicate, scan, search.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
# `metadata_app` lives in its own module — see sfxworkbench/cli/metadata.py.
# The pattern: each subapp module owns its Typer instance plus command
# decorations; this file imports the assembled instance and wires it in.
app.add_typer(metadata_app, name="metadata")
app.add_typer(maintenance_app, name="maintenance")
app.add_typer(packs_app, name="packs")
app.add_typer(groups_app, name="groups")
app.add_typer(format_app, name="format")
app.add_typer(compare_app, name="compare")
app.add_typer(delete_app, name="delete")
app.add_typer(audio_app, name="audio")
app.add_typer(organize_app, name="organize")
app.add_typer(tag_app, name="tag")
app.add_typer(ucs_app, name="ucs")
app.add_typer(similarity_app, name="similarity")
app.add_typer(config_app, name="config")
# Top-level `sfx ls QUERY` — the beets-style query DSL from PR #10.
app.command("ls")(cmd_ls)

console = Console()

# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"sfxworkbench {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="TOML config file to load. Defaults: $SFX_CONFIG, then ~/.config/sfxworkbench/config.toml.",
        ),
    ] = None,
) -> None:
    """sfx — sound library hygiene toolkit."""
    try:
        ctx.obj = load_config(config_path=config)
    except ConfigError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# sfx compare / processed / delete / audio dual-mono
# ---------------------------------------------------------------------------


@app.command("processed")
def cmd_processed(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the indexed library to inspect.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write processed-file report JSON to this path.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum entries to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report likely processed/rendered variants. No files are changed."""
    from sfxworkbench.processed import (
        build_processed_file_report,
        show_processed_file_report,
        write_processed_file_report,
    )

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    try:
        effective_db = resolve_db_path(ctx, db)
        report = build_processed_file_report(path, db_path=effective_db, limit=limit)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if output is not None:
        write_processed_file_report(report, output, quiet=json_output)
    elif not json_output:
        show_processed_file_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "processed",
                    "root": path,
                    "db_path": effective_db,
                    "report_path": output,
                    "report": report,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx similarity
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sfx format
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sfx groups
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sfx ucs
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sfx tag
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sfx organize
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sfx packs
# ---------------------------------------------------------------------------


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
    from sfxworkbench.clean import clean_library

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
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the library to scan.")],
    db: Annotated[
        Path | None,
        typer.Option(
            "--db", help="Path to the SQLite index. Falls back to Config.db_path, then ~/.sfxworkbench/index.db."
        ),
    ] = None,
    no_hash: Annotated[bool, typer.Option("--no-hash", help="Skip MD5 hashing (faster).")] = False,
    force: Annotated[bool, typer.Option("--force", help="Re-scan all files even if unchanged.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Crawl a path and index all audio files into SQLite."""
    from sfxworkbench.scan import scan_library

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    effective_db = resolve_db_path(ctx, db)
    result = scan_library(path, db_path=effective_db, skip_hash=no_hash, force_rescan=force, quiet=json_output)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "scan",
                    "db_path": effective_db,
                    "root": path,
                    "result": result,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx dedupe
# ---------------------------------------------------------------------------


@app.command("dedupe")
def cmd_dedupe(
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
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
    log: Annotated[Path | None, typer.Option("--log", help="Write dedupe quarantine log JSON to this path.")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    safe_folder: Annotated[
        list[Path] | None,
        typer.Option("--safe-folder", help="Folder that dedupe must not remove. May be passed multiple times."),
    ] = None,
    prefer_folder: Annotated[
        list[Path] | None,
        typer.Option(
            "--prefer-folder",
            help="Prefer this folder when choosing duplicate keep files. May be passed multiple times.",
        ),
    ] = None,
    prefer_extension: Annotated[
        list[str] | None,
        typer.Option(
            "--prefer-extension",
            help="Prefer this extension when choosing duplicate keep files, e.g. wav. May be passed multiple times.",
        ),
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
    from sfxworkbench.dedupe import (
        apply_dedupe_plan,
        find_duplicates,
        review_dedupe_plan,
        show_duplicates,
        summarize_duplicates,
        write_dedupe_plan,
    )

    effective_db = resolve_db_path(ctx, db)
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
            db_path=effective_db,
            dry_run=False,
            quarantine_dir=quarantine_dir,
            permanent_delete=permanent_delete,
            require_reviewed=require_reviewed,
            quiet=json_output,
            config_path=config,
            safe_folders=safe_folder,
            log_path=log,
        )
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "dedupe_apply", "result": result}))
        return

    groups = find_duplicates(effective_db)
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
        write_dedupe_plan(
            groups,
            plan_path,
            db_path=effective_db,
            quiet=json_output,
            config_path=config,
            safe_folders=safe_folder,
            prefer_folders=prefer_folder,
            prefer_extensions=prefer_extension,
        )
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
                    "db_path": effective_db,
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
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Query the index for problems: missing metadata, scan errors, unusual sample rates."""
    from sfxworkbench.audit_cmd import run_audit

    effective_db = resolve_db_path(ctx, db)
    result = run_audit(effective_db, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "audit", "db_path": effective_db, "result": result}))


@app.command("audit-bundle")
def cmd_audit_bundle(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the library to scan and audit.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for generated audit bundle JSON reports."),
    ] = None,
    skip_hash: Annotated[bool, typer.Option("--skip-hash", help="Skip MD5 hashing during the scan refresh.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Force rescan even if indexed anchors look current.")] = False,
    include_similarity: Annotated[
        bool,
        typer.Option(
            "--include-similarity",
            help="Record that similarity should be considered separately; similarity is not run by default.",
        ),
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", help="Maximum rows per generated sample report; 0 writes all.")
    ] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Refresh the index and generate a core read-only audit bundle."""
    from sfxworkbench.audit_bundle import build_audit_bundle

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    effective_db = resolve_db_path(ctx, db)
    try:
        bundle = build_audit_bundle(
            path,
            db_path=effective_db,
            output_dir=output_dir,
            skip_hash=skip_hash,
            force_rescan=force,
            include_similarity=include_similarity,
            quiet=json_output,
            limit=limit,
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if not json_output:
        table = Table(title="Audit Bundle", show_lines=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        summary = bundle.summary
        table.add_row("Indexed files", f"{summary.total_files:,}")
        table.add_row("Scan errors", f"{summary.scan_errors:,}")
        table.add_row("Filename issues", f"{summary.filename_issues:,}")
        table.add_row("Duplicate groups", f"{summary.duplicate_groups:,}")
        table.add_row("Missing metadata", f"{summary.missing_metadata:,}")
        table.add_row("Reports written", f"{summary.reports_written:,}")
        table.add_row("Errors", f"{summary.errors:,}")
        console.print(table)
        console.print(f"Audit bundle written to [cyan]{bundle.output_dir}[/cyan]")
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "audit_bundle",
                    "root": path,
                    "db_path": effective_db,
                    "output_dir": bundle.output_dir,
                    "bundle": bundle,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx scan-errors
# ---------------------------------------------------------------------------


@app.command("scan-errors")
def cmd_scan_errors(
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Write scan-error plan to this path.")] = None,
    apply: Annotated[Path | None, typer.Option("--apply", help="Apply a reviewed scan-error plan JSON file.")] = None,
    quarantine_dir: Annotated[
        Path | None, typer.Option("--quarantine-dir", help="Directory for quarantined scan-error files.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Review unreadable indexed files and quarantine obvious artifacts."""
    from sfxworkbench.scan_errors import (
        apply_scan_error_plan,
        build_scan_error_plan,
        show_scan_error_plan,
        write_scan_error_plan,
    )

    effective_db = resolve_db_path(ctx, db)
    if apply is not None:
        if not apply.exists():
            console.print(f"[red]Error: plan file not found: {apply}[/red]")
            raise typer.Exit(1)
        result = apply_scan_error_plan(
            apply, db_path=effective_db, quarantine_dir=quarantine_dir, dry_run=False, quiet=json_output
        )
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "scan_errors_apply", "result": result}))
        return

    plan = build_scan_error_plan(effective_db)
    plan_path = output
    if plan_path is not None:
        write_scan_error_plan(plan, plan_path, quiet=json_output)
    elif not json_output:
        show_scan_error_plan(plan)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "scan_errors",
                    "db_path": effective_db,
                    "plan_path": plan_path,
                    "plan": plan,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx search
# ---------------------------------------------------------------------------


@app.command("search")
def cmd_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Full-text search query.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum results to return.")] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Full-text search over filenames and stems."""
    from rich.table import Table

    from sfxworkbench.search import search

    effective_db = resolve_db_path(ctx, db)
    results = search(effective_db, query, limit=limit)
    if json_output:
        print(
            json_dumps(
                {"schema_version": 1, "command": "search", "db_path": effective_db, "query": query, "results": results}
            )
        )
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
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    output: Annotated[Path, typer.Option("--output", help="Output CSV file path.")] = Path("library.csv"),
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Export the files index to CSV."""
    from sfxworkbench.export import export_csv

    effective_db = resolve_db_path(ctx, db)
    count = export_csv(effective_db, output)
    if json_output:
        print(
            json_dumps(
                {"schema_version": 1, "command": "export", "db_path": effective_db, "output": output, "count": count}
            )
        )
    else:
        console.print(f"Exported [yellow]{count:,}[/yellow] rows to [cyan]{output}[/cyan]")


# ---------------------------------------------------------------------------
# sfx tui
# ---------------------------------------------------------------------------


@app.command("tui")
def cmd_tui(
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    report: Annotated[
        list[Path] | None,
        typer.Option("--report", help="JSON report/plan/log file or directory to include in the workbench."),
    ] = None,
) -> None:
    """Open the Textual alpha review workbench."""
    console.print("[dim]Starting SFX Workbench... opening the index.[/dim]")
    from sfxworkbench.tui_app import run_tui

    effective_db = resolve_db_path(ctx, db)
    try:
        run_tui(db_path=effective_db, config_path=config, report_paths=report or [])
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e


# ---------------------------------------------------------------------------
# sfx rename
# ---------------------------------------------------------------------------


@app.command("rename")
def cmd_rename(
    ctx: typer.Context,
    path: Annotated[Path | None, typer.Argument(help="Root path of the library to rename.")] = None,
    pattern: Annotated[
        str, typer.Option("--pattern", help="Rename pattern. Supported: 'ucs', 'safe', 'portable'.")
    ] = "ucs",
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Actually rename files (default is dry-run).")] = False,
    allow_partial: Annotated[
        bool,
        typer.Option("--allow-partial", help="Apply valid entries even when the plan has unresolved errors."),
    ] = False,
    log: Annotated[Path | None, typer.Option("--log", help="Write/read rename log path.")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="sfxworkbench config JSON with shared preservation rules."),
    ] = None,
    undo: Annotated[Path | None, typer.Option("--undo", help="Undo a previous rename log.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Bulk UCS rename with preview, apply, collision detection, and undo."""
    from sfxworkbench.rename import apply_rename_plan, build_rename_plan, show_rename_plan, undo_rename_log

    effective_db = resolve_db_path(ctx, db)
    if undo is not None:
        result = undo_rename_log(undo, db_path=effective_db, dry_run=not apply, quiet=json_output)
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "rename_undo", "result": result}))
        return

    if path is None:
        console.print("[red]Error: PATH is required unless --undo is provided.[/red]")
        raise typer.Exit(1)
    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    plan = build_rename_plan(path, pattern=pattern, config_path=config)
    if not apply:
        if not json_output:
            console.print("[yellow]Dry run — pass --apply to actually rename files.[/yellow]\n")
            show_rename_plan(plan)
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "rename", "plan": plan}))
        return

    result = apply_rename_plan(
        plan,
        db_path=effective_db,
        log_path=log,
        dry_run=False,
        quiet=json_output,
        allow_partial=allow_partial,
        config_path=config,
    )
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "rename_apply", "result": result, "plan": plan}))


if __name__ == "__main__":
    app()
