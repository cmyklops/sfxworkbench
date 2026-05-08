"""wavwarden CLI — sfx command entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH
from wavwarden.utils import json_dumps

app = typer.Typer(
    name="sfx",
    help="Sound library hygiene — audit, clean, deduplicate, scan, search.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
packs_app = typer.Typer(
    name="packs",
    help="Report duplicated or overlapping sound-library packs.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(packs_app, name="packs")
groups_app = typer.Typer(
    name="groups",
    help="Report related sound groups inferred from filenames.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(groups_app, name="groups")
format_app = typer.Typer(
    name="format",
    help="Report audio format consistency within related sound groups.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(format_app, name="format")
metadata_app = typer.Typer(
    name="metadata",
    help="Report metadata coverage and sample-rate hygiene.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(metadata_app, name="metadata")
organize_app = typer.Typer(
    name="organize",
    help="Preview safe folder-structure organization.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(organize_app, name="organize")

console = Console()

# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"wavwarden {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    """sfx — sound library hygiene toolkit."""


# ---------------------------------------------------------------------------
# sfx format
# ---------------------------------------------------------------------------


@format_app.command("audit")
def cmd_format_audit(
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write format consistency report JSON to this path.")
    ] = None,
    min_files: Annotated[int, typer.Option("--min-files", help="Minimum related files required to inspect.")] = 2,
    limit: Annotated[int, typer.Option("--limit", help="Maximum inconsistent groups to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report mixed sample rates, bit depths, or channel counts inside related groups."""
    from wavwarden.format_audit import build_format_audit_report, show_format_audit_report, write_format_audit_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    try:
        report = build_format_audit_report(path, db_path=db, min_files=min_files, limit=limit)
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
                    "db_path": db,
                    "report_path": output,
                    "report": report,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx groups
# ---------------------------------------------------------------------------


@groups_app.command("audit")
def cmd_groups_audit(
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write related groups report JSON to this path.")
    ] = None,
    min_files: Annotated[int, typer.Option("--min-files", help="Minimum files required to report a group.")] = 2,
    limit: Annotated[int, typer.Option("--limit", help="Maximum groups to include; 0 writes all groups.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report obvious related sounds such as numbered takes and channel sets."""
    from wavwarden.groups import audit_related_groups, show_related_groups_report, write_related_groups_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    try:
        report = audit_related_groups(path, db_path=db, min_files=min_files, limit=limit)
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
                    "db_path": db,
                    "report_path": output,
                    "report": report,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx metadata
# ---------------------------------------------------------------------------


@metadata_app.command("audit")
def cmd_metadata_audit(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write metadata audit report JSON to this path.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum rows per report section; 0 writes all rows.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report files missing BWF/iXML metadata and files with unusual sample rates."""
    from wavwarden.metadata_audit import (
        build_metadata_audit_report,
        show_metadata_audit_report,
        write_metadata_audit_report,
    )

    try:
        report = build_metadata_audit_report(db, limit=limit)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        write_metadata_audit_report(report, output, quiet=json_output)
    elif not json_output:
        show_metadata_audit_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "metadata_audit",
                    "db_path": db,
                    "report_path": output,
                    "report": report,
                }
            )
        )


# ---------------------------------------------------------------------------
# sfx organize
# ---------------------------------------------------------------------------


@organize_app.command("audit")
def cmd_organize_audit(
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    pattern: Annotated[
        str,
        typer.Option(
            "--pattern",
            help="Organization pattern. Supported: 'strip-leading-numbers', 'redundant-nesting'.",
        ),
    ] = "strip-leading-numbers",
    depth: Annotated[int, typer.Option("--depth", help="Folder depth under PATH to inspect.")] = 1,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write organization preview JSON to this path.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Preview safe folder-structure organization without changing files."""
    from wavwarden.organize import audit_organization, show_organize_audit_report, write_organize_audit_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    if depth < 1:
        console.print("[red]Error: --depth must be at least 1.[/red]")
        raise typer.Exit(1)

    try:
        report = audit_organization(path, pattern=pattern, depth=depth)
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
    from wavwarden.organize import review_organize_report

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
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Create a safe flatten plan from repeated-folder-name candidates."""
    from wavwarden.organize import build_nesting_plan_from_report, show_nesting_plan

    if not report.exists():
        console.print(f"[red]Error: report file not found: {report}[/red]")
        raise typer.Exit(1)

    plan = build_nesting_plan_from_report(report, kind=kind, output_path=output, quiet=json_output)
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
    log: Annotated[Path | None, typer.Option("--log", help="Write nesting undo log to this path.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Actually flatten folders (default is dry-run).")] = False,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Apply only approved nesting plan entries.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply a reviewed repeated-folder flatten plan."""
    from wavwarden.organize import apply_nesting_plan

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
    from wavwarden.organize import undo_nesting_log

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
    log: Annotated[Path | None, typer.Option("--log", help="Write organization undo log to this path.")] = None,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Apply only approved organization entries.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply approved folder organization entries and write an undo log."""
    from wavwarden.organize import apply_organize_report

    if not report.exists():
        console.print(f"[red]Error: report file not found: {report}[/red]")
        raise typer.Exit(1)

    result = apply_organize_report(
        report, db_path=db, log_path=log, require_reviewed=require_reviewed, quiet=json_output
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
    from wavwarden.organize import undo_organize_log

    if not log.exists():
        console.print(f"[red]Error: log file not found: {log}[/red]")
        raise typer.Exit(1)

    result = undo_organize_log(log, db_path=db, dry_run=not apply, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "organize_undo", "result": result}))


# ---------------------------------------------------------------------------
# sfx packs
# ---------------------------------------------------------------------------


@packs_app.command("audit")
def cmd_packs_audit(
    path: Annotated[Path, typer.Argument(help="Root path of the library to analyze.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
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
    from wavwarden.packs import audit_packs, show_pack_audit_report, write_pack_audit_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    if min_files < 1:
        console.print("[red]Error: --min-files must be at least 1.[/red]")
        raise typer.Exit(1)
    if not 0 < overlap_threshold <= 1:
        console.print("[red]Error: --overlap-threshold must be > 0 and <= 1.[/red]")
        raise typer.Exit(1)

    report = audit_packs(
        path,
        db_path=db,
        min_files=min_files,
        overlap_threshold=overlap_threshold,
        max_overlap_candidates=max_overlap_candidates,
    )
    if output is not None:
        write_pack_audit_report(report, output, quiet=json_output)
    elif not json_output:
        show_pack_audit_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "packs_audit",
                    "db_path": db,
                    "root": path,
                    "report_path": output,
                    "report": report,
                }
            )
        )


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
    from wavwarden.clean import clean_library

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
    path: Annotated[Path, typer.Argument(help="Root path of the library to scan.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    no_hash: Annotated[bool, typer.Option("--no-hash", help="Skip MD5 hashing (faster).")] = False,
    force: Annotated[bool, typer.Option("--force", help="Re-scan all files even if unchanged.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Crawl a path and index all audio files into SQLite."""
    from wavwarden.scan import scan_library

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    result = scan_library(path, db_path=db, skip_hash=no_hash, force_rescan=force, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "scan", "db_path": db, "root": path, "result": result}))


# ---------------------------------------------------------------------------
# sfx dedupe
# ---------------------------------------------------------------------------


@app.command("dedupe")
def cmd_dedupe(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
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
    permanent_delete: Annotated[
        bool, typer.Option("--delete", help="Permanently delete instead of quarantining. Advanced/destructive.")
    ] = False,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Apply only plans with approved dedupe groups.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Find duplicate files or execute a dedupe plan."""
    from wavwarden.dedupe import (
        apply_dedupe_plan,
        find_duplicates,
        review_dedupe_plan,
        show_duplicates,
        summarize_duplicates,
        write_dedupe_plan,
    )

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
            db_path=db,
            dry_run=False,
            quarantine_dir=quarantine_dir,
            permanent_delete=permanent_delete,
            require_reviewed=require_reviewed,
            quiet=json_output,
        )
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "dedupe_apply", "result": result}))
        return

    groups = find_duplicates(db)
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
        write_dedupe_plan(groups, plan_path, db_path=db, quiet=json_output)
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
                    "db_path": db,
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
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Query the index for problems: missing metadata, scan errors, unusual sample rates."""
    from wavwarden.audit_cmd import run_audit

    result = run_audit(db, quiet=json_output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "audit", "db_path": db, "result": result}))


# ---------------------------------------------------------------------------
# sfx scan-errors
# ---------------------------------------------------------------------------


@app.command("scan-errors")
def cmd_scan_errors(
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    output: Annotated[Path | None, typer.Option("--output", help="Write scan-error plan to this path.")] = None,
    apply: Annotated[Path | None, typer.Option("--apply", help="Apply a reviewed scan-error plan JSON file.")] = None,
    quarantine_dir: Annotated[
        Path | None, typer.Option("--quarantine-dir", help="Directory for quarantined scan-error files.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Review unreadable indexed files and quarantine obvious artifacts."""
    from wavwarden.scan_errors import (
        apply_scan_error_plan,
        build_scan_error_plan,
        show_scan_error_plan,
        write_scan_error_plan,
    )

    if apply is not None:
        if not apply.exists():
            console.print(f"[red]Error: plan file not found: {apply}[/red]")
            raise typer.Exit(1)
        result = apply_scan_error_plan(
            apply, db_path=db, quarantine_dir=quarantine_dir, dry_run=False, quiet=json_output
        )
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "scan_errors_apply", "result": result}))
        return

    plan = build_scan_error_plan(db)
    plan_path = output
    if plan_path is not None:
        write_scan_error_plan(plan, plan_path, quiet=json_output)
    elif not json_output:
        show_scan_error_plan(plan)
    if json_output:
        print(
            json_dumps(
                {"schema_version": 1, "command": "scan_errors", "db_path": db, "plan_path": plan_path, "plan": plan}
            )
        )


# ---------------------------------------------------------------------------
# sfx search
# ---------------------------------------------------------------------------


@app.command("search")
def cmd_search(
    query: Annotated[str, typer.Argument(help="Full-text search query.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    limit: Annotated[int, typer.Option("--limit", help="Maximum results to return.")] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Full-text search over filenames and stems."""
    from rich.table import Table

    from wavwarden.search import search

    results = search(db, query, limit=limit)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "search", "db_path": db, "query": query, "results": results}))
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
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    output: Annotated[Path, typer.Option("--output", help="Output CSV file path.")] = Path("library.csv"),
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Export the files index to CSV."""
    from wavwarden.export import export_csv

    count = export_csv(db, output)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "export", "db_path": db, "output": output, "count": count}))
    else:
        console.print(f"Exported [yellow]{count:,}[/yellow] rows to [cyan]{output}[/cyan]")


# ---------------------------------------------------------------------------
# sfx rename
# ---------------------------------------------------------------------------


@app.command("rename")
def cmd_rename(
    path: Annotated[Path | None, typer.Argument(help="Root path of the library to rename.")] = None,
    pattern: Annotated[
        str, typer.Option("--pattern", help="Rename pattern. Supported: 'ucs', 'safe', 'portable'.")
    ] = "ucs",
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    apply: Annotated[bool, typer.Option("--apply", help="Actually rename files (default is dry-run).")] = False,
    allow_partial: Annotated[
        bool,
        typer.Option("--allow-partial", help="Apply valid entries even when the plan has unresolved errors."),
    ] = False,
    log: Annotated[Path | None, typer.Option("--log", help="Write/read rename log path.")] = None,
    undo: Annotated[Path | None, typer.Option("--undo", help="Undo a previous rename log.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Bulk UCS rename with preview, apply, collision detection, and undo."""
    from wavwarden.rename import apply_rename_plan, build_rename_plan, show_rename_plan, undo_rename_log

    if undo is not None:
        result = undo_rename_log(undo, db_path=db, dry_run=not apply, quiet=json_output)
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "rename_undo", "result": result}))
        return

    if path is None:
        console.print("[red]Error: PATH is required unless --undo is provided.[/red]")
        raise typer.Exit(1)
    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    plan = build_rename_plan(path, pattern=pattern)
    if not apply:
        if not json_output:
            console.print("[yellow]Dry run — pass --apply to actually rename files.[/yellow]\n")
            show_rename_plan(plan)
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "rename", "plan": plan}))
        return

    result = apply_rename_plan(
        plan,
        db_path=db,
        log_path=log,
        dry_run=False,
        quiet=json_output,
        allow_partial=allow_partial,
    )
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "rename_apply", "result": result, "plan": plan}))


if __name__ == "__main__":
    app()
