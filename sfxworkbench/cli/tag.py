"""`sfx tag` subapp commands.

Extracted from the monolithic ``cli.py`` in the PR #6 follow-up using the
per-subapp pattern established by ``cli/metadata.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sfxworkbench.cli._shared import resolve_db_path, resolve_library_root, resolve_ucs_catalog_path
from sfxworkbench.db import DEFAULT_DB_PATH
from sfxworkbench.utils import atomic_write_json, json_dumps

console = Console()

tag_app = typer.Typer(
    name="tag",
    help="Propose and review metadata tags from corroborated evidence.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@tag_app.command("suggest")
def cmd_tag_suggest(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Root path of the indexed library to inspect. Optional when "
                "``library_root`` is set in your sfxworkbench config."
            ),
        ),
    ] = None,
    db: Annotated[
        Path | None,
        typer.Option("--db", help="Path to the SQLite index. Falls back to Config.db_path."),
    ] = None,
    ucs_catalog: Annotated[
        Path | None,
        typer.Option(
            "--ucs-catalog",
            help="Use this UCS catalog JSON for catalog-backed suggestions. Falls back to Config.ucs_catalog_path.",
        ),
    ] = None,
    use_ucs_catalog: Annotated[
        bool,
        typer.Option("--use-ucs-catalog", help="Use the UCS catalog discovery chain for catalog-backed suggestions."),
    ] = False,
    include_synonyms: Annotated[
        bool,
        typer.Option(
            "--include-synonyms",
            help="Suggest reviewed keyword synonyms for metadata enrichment.",
        ),
    ] = False,
    synonym_limit: Annotated[
        int,
        typer.Option(
            "--synonym-limit",
            help="Maximum synonym keyword suggestions per file when --include-synonyms is enabled; 0 means no cap.",
        ),
    ] = 0,
    synonym_depth: Annotated[
        int,
        typer.Option(
            "--synonym-depth",
            help="Maximum number of ordered synonyms to consider from each matched synonym list; 0 means all.",
        ),
    ] = 0,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write tag suggestion report JSON to this path.")
    ] = None,
    min_confidence: Annotated[
        float, typer.Option("--min-confidence", help="Drop suggestions below this confidence (0.0–1.0).")
    ] = 0.0,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Only include suggestions from this source. Repeat or comma-separate values."),
    ] = None,
    field: Annotated[
        list[str] | None,
        typer.Option(
            "--field", help="Only include suggestions for this metadata field. Repeat or comma-separate values."
        ),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum file entries to include; 0 writes all entries.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Suggest metadata tags from filename, path, and group evidence. No writes.

    All three optional resolvable inputs — ``path``, ``--db``, ``--ucs-catalog``
    — fall through to the active :class:`sfxworkbench.config.Config` when not
    given on the command line. This is the canonical example for the wider
    ``ctx.obj``-via-Config opt-in: every command resolves via the helpers in
    ``cli/_shared.py`` and the precedence is the same everywhere
    (CLI > Config > package default).
    """
    from sfxworkbench.config import Config
    from sfxworkbench.tag_suggest import (
        build_tag_suggestion_report,
        show_tag_suggestion_report,
        write_tag_suggestion_report,
    )

    path = resolve_library_root(ctx, path)
    if path is None:
        console.print(
            "[red]Error: no path argument and no library_root set in config. "
            'Either pass PATH or add `library_root = "..."` to your config file.[/red]'
        )
        raise typer.Exit(1)
    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    effective_db = resolve_db_path(ctx, db)
    effective_catalog = resolve_ucs_catalog_path(ctx, ucs_catalog)
    # Plumb Config.confidence so user-set TOML overrides actually affect output.
    active_config = ctx.obj if isinstance(ctx.obj, Config) else None
    profile = active_config.confidence if active_config is not None else None

    try:
        report = build_tag_suggestion_report(
            path,
            db_path=effective_db,
            min_confidence=min_confidence,
            limit=limit,
            ucs_catalog_path=effective_catalog,
            use_ucs_catalog=use_ucs_catalog,
            include_synonyms=include_synonyms,
            synonym_limit=synonym_limit,
            synonym_depth=synonym_depth,
            sources=source,
            fields=field,
            confidence_profile=profile,
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        write_tag_suggestion_report(report, output, quiet=json_output)
    elif not json_output:
        show_tag_suggestion_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "tag_suggest",
                    "root": path,
                    "db_path": effective_db,
                    "ucs_catalog_path": report.ucs_catalog_path,
                    "report_path": output,
                    "report": report,
                }
            )
        )


@tag_app.command("propose")
def cmd_tag_propose(
    path: Annotated[Path, typer.Argument(help="Root path of the indexed library to inspect.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    catalog: Annotated[Path | None, typer.Option("--catalog", help="Override the UCS catalog discovery chain.")] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write evidence-fusion tag proposal report JSON.")
    ] = None,
    min_confidence: Annotated[
        float, typer.Option("--min-confidence", help="Drop proposals below this confidence (0.0-1.0).")
    ] = 0.0,
    limit: Annotated[int, typer.Option("--limit", help="Maximum file entries to include; 0 writes all entries.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Propose UCS tags from combined evidence. No writes."""
    from sfxworkbench.tag_propose import build_tag_proposal_report, show_tag_proposal_report

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    try:
        report = build_tag_proposal_report(
            path,
            db_path=db,
            catalog_path=catalog,
            min_confidence=min_confidence,
            limit=limit,
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        atomic_write_json(output, report)
        if not json_output:
            console.print(f"Tag proposal report written to [cyan]{output}[/cyan]")
    elif not json_output:
        show_tag_proposal_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "tag_propose",
                    "root": path,
                    "db_path": db,
                    "catalog_path": report.catalog_path,
                    "report_path": output,
                    "report": report,
                }
            )
        )


@tag_app.command("plan")
def cmd_tag_plan(
    path: Annotated[Path, typer.Argument(help="Root path of the indexed library to inspect.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    output: Annotated[Path | None, typer.Option("--output", help="Write reviewed tag plan JSON to this path.")] = None,
    source_report: Annotated[
        Path | None, typer.Option("--from-suggestions", help="Build a plan from an existing tag suggestion report.")
    ] = None,
    csv_path: Annotated[
        Path | None,
        typer.Option(
            "--from-csv",
            help="Build a reviewed tag plan from CSV rows with file_id/path/filename, field, and value columns.",
        ),
    ] = None,
    ucs_catalog: Annotated[
        Path | None,
        typer.Option("--ucs-catalog", help="Use this UCS catalog JSON for catalog-backed suggestions."),
    ] = None,
    use_ucs_catalog: Annotated[
        bool,
        typer.Option("--use-ucs-catalog", help="Use the UCS catalog discovery chain for catalog-backed suggestions."),
    ] = False,
    include_synonyms: Annotated[
        bool,
        typer.Option(
            "--include-synonyms",
            help="Suggest reviewed keyword synonyms when building a new tag plan.",
        ),
    ] = False,
    synonym_limit: Annotated[
        int,
        typer.Option(
            "--synonym-limit",
            help="Maximum synonym keyword suggestions per file when --include-synonyms is enabled; 0 means no cap.",
        ),
    ] = 0,
    synonym_depth: Annotated[
        int,
        typer.Option(
            "--synonym-depth",
            help="Maximum number of ordered synonyms to consider from each matched synonym list; 0 means all.",
        ),
    ] = 0,
    min_confidence: Annotated[
        float, typer.Option("--min-confidence", help="Drop suggestions below this confidence (0.0-1.0).")
    ] = 0.0,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Only include suggestions from this source. Repeat or comma-separate values."),
    ] = None,
    field: Annotated[
        list[str] | None,
        typer.Option(
            "--field", help="Only include suggestions for this metadata field. Repeat or comma-separate values."
        ),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum file entries to inspect; 0 writes all entries.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Build a reviewed DB-only metadata tag plan. No writes."""
    from sfxworkbench.tag_plan import build_tag_plan, show_tag_plan, write_tag_plan

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    if source_report is not None and not source_report.exists():
        console.print(f"[red]Error: suggestion report not found: {source_report}[/red]")
        raise typer.Exit(1)
    if csv_path is not None and not csv_path.exists():
        console.print(f"[red]Error: CSV file not found: {csv_path}[/red]")
        raise typer.Exit(1)
    try:
        plan = build_tag_plan(
            path,
            db_path=db,
            min_confidence=min_confidence,
            limit=limit,
            ucs_catalog_path=ucs_catalog,
            use_ucs_catalog=use_ucs_catalog,
            include_synonyms=include_synonyms,
            synonym_limit=synonym_limit,
            synonym_depth=synonym_depth,
            source_report=source_report,
            csv_path=csv_path,
            sources=source,
            fields=field,
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    plan_path = write_tag_plan(plan, output, quiet=json_output) if output is not None else None
    if output is None and not json_output:
        show_tag_plan(plan)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "tag_plan",
                    "root": path,
                    "db_path": db,
                    "plan_path": plan_path,
                    "plan": plan,
                }
            )
        )


@tag_app.command("summarize")
def cmd_tag_summarize(
    plan: Annotated[Path, typer.Argument(help="Tag plan JSON to summarize.")],
    field: Annotated[
        list[str] | None,
        typer.Option("--field", help="Only summarize entries for this field. Repeat or comma-separate values."),
    ] = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Only summarize entries from this source. Repeat or comma-separate values."),
    ] = None,
    value: Annotated[
        list[str] | None,
        typer.Option(
            "--value", help="Only summarize entries with this proposed value. Repeat or comma-separate values."
        ),
    ] = None,
    status: Annotated[
        list[str] | None,
        typer.Option("--status", help="Only summarize entries with this review status."),
    ] = None,
    sample_limit: Annotated[int, typer.Option("--sample-limit", help="Sample filenames per value row.")] = 5,
    value_limit: Annotated[int, typer.Option("--value-limit", help="Maximum value rows to show; 0 shows all.")] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Summarize a tag plan for batch review."""
    from sfxworkbench.tag_plan import show_tag_plan_summary, summarize_tag_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)
    try:
        report = summarize_tag_plan(
            plan,
            fields=field,
            sources=source,
            values=value,
            statuses=status,
            sample_limit=sample_limit,
            value_limit=value_limit,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if not json_output:
        show_tag_plan_summary(report)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "tag_summarize", "plan_path": plan, "report": report}))


@tag_app.command("review")
def cmd_tag_review(
    plan: Annotated[Path, typer.Argument(help="Tag plan JSON to review.")],
    output: Annotated[Path | None, typer.Option("--output", help="Write reviewed plan to this path.")] = None,
    approve_all: Annotated[bool, typer.Option("--approve-all", help="Approve every tag plan entry.")] = False,
    entry: Annotated[list[int] | None, typer.Option("--entry", help="Approve a 1-based entry id.")] = None,
    reject_entry: Annotated[list[int] | None, typer.Option("--reject-entry", help="Reject a 1-based entry id.")] = None,
    approve_field: Annotated[
        list[str] | None,
        typer.Option("--approve-field", help="Approve entries for this field. Repeat or comma-separate values."),
    ] = None,
    reject_field: Annotated[
        list[str] | None,
        typer.Option("--reject-field", help="Reject entries for this field. Repeat or comma-separate values."),
    ] = None,
    approve_source: Annotated[
        list[str] | None,
        typer.Option("--approve-source", help="Approve entries from this source. Repeat or comma-separate values."),
    ] = None,
    reject_source: Annotated[
        list[str] | None,
        typer.Option("--reject-source", help="Reject entries from this source. Repeat or comma-separate values."),
    ] = None,
    approve_value: Annotated[
        list[str] | None,
        typer.Option(
            "--approve-value", help="Approve entries with this proposed value. Repeat or comma-separate values."
        ),
    ] = None,
    reject_value: Annotated[
        list[str] | None,
        typer.Option(
            "--reject-value", help="Reject entries with this proposed value. Repeat or comma-separate values."
        ),
    ] = None,
    only_status: Annotated[
        list[str] | None,
        typer.Option("--only-status", help="Only selector-review entries currently in this review status."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Mark tag plan entries as approved or rejected."""
    from sfxworkbench.tag_plan import review_tag_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)
    has_selector = any([approve_field, reject_field, approve_source, reject_source, approve_value, reject_value])
    if not approve_all and not entry and not reject_entry and not has_selector:
        console.print("[red]Error: pass --approve-all, --entry, --reject-entry, or a selector review option.[/red]")
        raise typer.Exit(1)
    try:
        result = review_tag_plan(
            plan,
            output_path=output,
            approve_all=approve_all,
            entries=entry,
            reject_entries=reject_entry,
            approve_fields=approve_field,
            reject_fields=reject_field,
            approve_sources=approve_source,
            reject_sources=reject_source,
            approve_values=approve_value,
            reject_values=reject_value,
            only_status=only_status,
            quiet=json_output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if result.invalid_entries:
        raise typer.Exit(1)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "tag_review",
                    "plan_path": plan,
                    "output_path": output or plan,
                    "result": result,
                }
            )
        )


@tag_app.command("apply")
def cmd_tag_apply(
    plan: Annotated[Path, typer.Argument(help="Reviewed tag plan JSON to apply.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index. Defaults to plan db_path.")] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Write approved tags to the DB-only accepted tag table.")
    ] = False,
    require_reviewed: Annotated[
        bool, typer.Option("--require-reviewed", help="Refuse to apply unless entries have been approved.")
    ] = False,
    log: Annotated[Path | None, typer.Option("--log", help="Write tag apply log JSON to this path.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Apply a reviewed tag plan into SQLite accepted_tags. No audio mutation."""
    from sfxworkbench.tag_plan import apply_tag_plan

    if not plan.exists():
        console.print(f"[red]Error: plan file not found: {plan}[/red]")
        raise typer.Exit(1)
    result = apply_tag_plan(
        plan,
        db_path=db,
        dry_run=not apply,
        require_reviewed=require_reviewed,
        log_path=log,
        quiet=json_output,
    )
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "tag_apply",
                    "plan_path": plan,
                    "db_path": db,
                    "result": result,
                }
            )
        )


@tag_app.command("sidecar-export")
def cmd_tag_sidecar_export(
    output: Annotated[Path, typer.Argument(help="Output JSON sidecar path.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    path: Annotated[Path | None, typer.Option("--path", help="Optional indexed library root to export.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum tagged files to include; 0 writes all.")] = 0,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Export DB-only accepted tags as a portable JSON sidecar."""
    from sfxworkbench.tag_sidecar import build_tag_sidecar_report, show_tag_sidecar_report, write_tag_sidecar_report

    try:
        report = build_tag_sidecar_report(db_path=db, root=path, limit=limit)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    write_tag_sidecar_report(report, output, quiet=json_output)
    if not json_output:
        show_tag_sidecar_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "tag_sidecar_export",
                    "db_path": db,
                    "root": path,
                    "sidecar_path": output,
                    "report": report,
                }
            )
        )


@tag_app.command("sidecar-import")
def cmd_tag_sidecar_import(
    sidecar: Annotated[Path, typer.Argument(help="JSON sidecar path to import.")],
    db: Annotated[Path, typer.Option("--db", help="Path to the SQLite index.")] = DEFAULT_DB_PATH,
    apply: Annotated[bool, typer.Option("--apply", help="Import sidecar tags into SQLite accepted_tags.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Import a portable JSON sidecar into DB-only accepted tags."""
    from sfxworkbench.tag_sidecar import import_tag_sidecar

    if not sidecar.exists():
        console.print(f"[red]Error: sidecar file not found: {sidecar}[/red]")
        raise typer.Exit(1)
    try:
        result = import_tag_sidecar(sidecar, db_path=db, dry_run=not apply, quiet=json_output)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "tag_sidecar_import",
                    "db_path": db,
                    "sidecar_path": sidecar,
                    "result": result,
                }
            )
        )
