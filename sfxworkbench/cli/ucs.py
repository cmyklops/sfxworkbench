"""`sfx ucs` subapp commands.

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

ucs_app = typer.Typer(
    name="ucs",
    help="Import and inspect the Universal Category System (UCS) catalog.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@ucs_app.command("import")
def cmd_ucs_import(
    source: Annotated[Path, typer.Argument(help="UCS source file (Soundminer/_categorylist.csv).")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help="Write normalized catalog JSON to this path. Default: ~/.sfxworkbench/ucs_catalog.json.",
        ),
    ] = None,
    release_version: Annotated[
        str | None,
        typer.Option("--release-version", help="UCS release version recorded in provenance (e.g. 'v8.2.1')."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Import the official UCS catalog and write a normalized JSON cache."""
    from sfxworkbench.ucs_catalog import default_cache_path, import_catalog, show_import_result

    if not source.exists():
        console.print(f"[red]Error: UCS source file not found: {source}[/red]")
        raise typer.Exit(1)

    target = output or default_cache_path()
    try:
        result, catalog = import_catalog(source, output_path=target, release_version=release_version)
    except (FileNotFoundError, NotImplementedError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    if not json_output:
        show_import_result(result, catalog)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "ucs_import",
                    "source": source,
                    "catalog_path": target,
                    "result": result,
                }
            )
        )


@ucs_app.command("info")
def cmd_ucs_info(
    catalog: Annotated[
        Path | None, typer.Option("--catalog", help="Override the discovery chain with an explicit catalog path.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Show provenance and entry count of the loaded UCS catalog."""
    from sfxworkbench.ucs_catalog import default_cache_path, load_catalog

    try:
        loaded = load_catalog(catalog)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    if loaded is None:
        msg = "No UCS catalog loaded. Run `sfx ucs import SOURCE` first or set SFXWORKBENCH_UCS_DATA / pass --catalog."
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "ucs_info", "loaded": False, "message": msg}))
        else:
            console.print(f"[yellow]{msg}[/yellow]")
        raise typer.Exit(1)

    source_path = catalog or default_cache_path()
    if not json_output:
        from sfxworkbench.ucs_catalog import show_catalog_info

        show_catalog_info(loaded, source_path)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "ucs_info",
                    "loaded": True,
                    "catalog_path": source_path,
                    "provenance": loaded.provenance,
                    "entry_count": loaded.provenance.entry_count,
                }
            )
        )


@ucs_app.command("categories")
def cmd_ucs_categories(
    catalog: Annotated[
        Path | None, typer.Option("--catalog", help="Override the discovery chain with an explicit catalog path.")
    ] = None,
    category: Annotated[
        str | None, typer.Option("--category", help="Filter to entries whose long-form category matches.")
    ] = None,
    cat_short: Annotated[
        str | None, typer.Option("--cat-short", help="Filter to entries with this 3–5 char filename prefix.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List UCS entries from the loaded catalog, optionally filtered."""
    from sfxworkbench.ucs_catalog import load_catalog, query_categories, show_categories_query

    try:
        loaded = load_catalog(catalog)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    if loaded is None:
        console.print("[red]Error: no UCS catalog loaded. Run `sfx ucs import SOURCE` first.[/red]")
        raise typer.Exit(1)

    query = query_categories(loaded, category=category, cat_short=cat_short)
    if not json_output:
        show_categories_query(query)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "ucs_categories", "result": query}))


@ucs_app.command("validate")
def cmd_ucs_validate(
    ctx: typer.Context,
    path: Annotated[
        Path | None,
        typer.Argument(help="Optional indexed library root to validate. Omits unrelated rows when provided."),
    ] = None,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    catalog: Annotated[
        Path | None, typer.Option("--catalog", help="Override the discovery chain with an explicit catalog path.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write UCS validation report JSON to this path.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum miss entries to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Validate UCS-looking indexed filenames against the loaded UCS catalog."""
    from sfxworkbench.ucs_validate import (
        build_ucs_validation_report,
        show_ucs_validation_report,
        write_ucs_validation_report,
    )

    if path is not None and not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)

    effective_db = resolve_db_path(ctx, db)
    try:
        report = build_ucs_validation_report(effective_db, root=path, catalog_path=catalog, limit=limit)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if output is not None:
        write_ucs_validation_report(report, output, quiet=json_output)
    elif not json_output:
        show_ucs_validation_report(report)
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "ucs_validate",
                    "root": path,
                    "db_path": effective_db,
                    "catalog_path": report.catalog_path,
                    "report_path": output,
                    "report": report,
                }
            )
        )
