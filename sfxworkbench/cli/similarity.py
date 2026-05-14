"""`sfx similarity` subapp commands.

Extracted from the monolithic ``cli.py`` in the PR #6 follow-up using the
per-subapp pattern established by ``cli/metadata.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from sfxworkbench.cli._shared import resolve_db_path
from sfxworkbench.utils import json_dumps

console = Console()

similarity_app = typer.Typer(
    name="similarity",
    help="Analyze audio content descriptors for future similarity workflows.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

similarity_feedback_app = typer.Typer(
    name="feedback",
    help="Review DB-only similarity relationships without changing audio files.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
similarity_app.add_typer(similarity_feedback_app, name="feedback")


@similarity_app.command("crawl")
def cmd_similarity_crawl(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the indexed library to analyze.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    cache: Annotated[
        Path | None,
        typer.Option("--cache", help="Directory for similarity crawl run reports."),
    ] = None,
    max_duration: Annotated[
        float | None,
        typer.Option("--max-duration", help="Maximum seconds to analyze per file; 0 reads each full file."),
    ] = 30.0,
    force: Annotated[bool, typer.Option("--force", help="Rebuild descriptors even when file anchors match.")] = False,
    max_files: Annotated[
        int | None,
        typer.Option(
            "--max-files", help="Analyze at most this many stale files in this run; remaining files stay pending."
        ),
    ] = None,
    throttle_ms: Annotated[
        int,
        typer.Option(
            "--throttle-ms", help="Sleep this many milliseconds after each analyzed file to reduce CPU pressure."
        ),
    ] = 0,
    limit: Annotated[
        int, typer.Option("--limit", help="Maximum descriptor rows to include in JSON output; 0 includes all.")
    ] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Build deterministic audio descriptors for indexed files."""
    from sfxworkbench.similarity import DEFAULT_SIMILARITY_CACHE, crawl_similarity_descriptors

    if not path.exists():
        console.print(f"[red]Error: path not found: {path}[/red]")
        raise typer.Exit(1)
    effective_cache = cache if cache is not None else DEFAULT_SIMILARITY_CACHE
    effective_max_duration = None if max_duration == 0 else max_duration
    effective_db = resolve_db_path(ctx, db)
    try:
        report = crawl_similarity_descriptors(
            path,
            db_path=effective_db,
            cache_path=effective_cache,
            max_duration_s=effective_max_duration,
            force=force,
            max_files=max_files,
            throttle_ms=throttle_ms,
            limit=limit,
            quiet=json_output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "similarity_crawl",
                    "root": path,
                    "db_path": effective_db,
                    "cache_path": effective_cache,
                    "report": report,
                }
            )
        )


@similarity_app.command("backends")
def cmd_similarity_backends(
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report available and deferred similarity analysis backends."""
    from sfxworkbench.similarity import similarity_backends_report

    report = similarity_backends_report()
    if not json_output:
        table = Table(title="Similarity backends", show_lines=False)
        table.add_column("Backend")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("Scope")
        for item in report.capabilities:
            table.add_row(item.backend, item.backend_version, item.status, ", ".join(item.scope))
        console.print(table)
    if json_output:
        print(json_dumps({"schema_version": 1, "command": "similarity_backends", "report": report}))


@similarity_app.command("search")
def cmd_similarity_search(
    ctx: typer.Context,
    query_file: Annotated[Path, typer.Option("--file", help="Audio file to use as the similarity query.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    max_duration: Annotated[
        float | None,
        typer.Option("--max-duration", help="Maximum seconds to analyze from the query; 0 reads the full file."),
    ] = 30.0,
    limit: Annotated[int, typer.Option("--limit", help="Maximum matches to return.")] = 20,
    scope: Annotated[
        str,
        typer.Option("--scope", help="Search scope: 'file' for whole-file descriptors or 'segment' for event windows."),
    ] = "file",
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Search cached deterministic descriptors with a query audio file."""
    from sfxworkbench.similarity import search_similarity_descriptors

    effective_max_duration = None if max_duration == 0 else max_duration
    effective_db = resolve_db_path(ctx, db)
    try:
        report = search_similarity_descriptors(
            query_file,
            db_path=effective_db,
            max_duration_s=effective_max_duration,
            limit=limit,
            scope=scope,
            quiet=json_output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "similarity_search",
                    "query_path": query_file,
                    "db_path": effective_db,
                    "report": report,
                }
            )
        )


@similarity_app.command("segments")
def cmd_similarity_segments(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the indexed library to inspect.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    max_duration: Annotated[
        float | None,
        typer.Option("--max-duration", help="Descriptor analysis window to inspect; 0 uses full-file segments."),
    ] = 30.0,
    limit: Annotated[int, typer.Option("--limit", help="Maximum segments to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List cached event-like segments from the similarity crawler."""
    from sfxworkbench.similarity import list_similarity_segments

    effective_max_duration = None if max_duration == 0 else max_duration
    effective_db = resolve_db_path(ctx, db)
    try:
        report = list_similarity_segments(
            path,
            db_path=effective_db,
            max_duration_s=effective_max_duration,
            limit=limit,
            quiet=json_output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "similarity_segments",
                    "root": path,
                    "db_path": effective_db,
                    "report": report,
                }
            )
        )


@similarity_app.command("audit")
def cmd_similarity_audit(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Root path of the indexed library to audit.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    threshold: Annotated[
        float, typer.Option("--threshold", help="Minimum similarity score for near-duplicate candidate pairs.")
    ] = 0.92,
    max_duration: Annotated[
        float | None,
        typer.Option("--max-duration", help="Descriptor analysis window to audit; 0 uses full-file descriptors."),
    ] = 30.0,
    include_exact_md5: Annotated[
        bool,
        typer.Option("--include-exact-md5", help="Include exact MD5 duplicate pairs in the similarity report."),
    ] = False,
    scope: Annotated[
        str,
        typer.Option("--scope", help="Audit scope: 'file' for whole-file descriptors or 'segment' for event windows."),
    ] = "file",
    output: Annotated[
        Path | None, typer.Option("--output", help="Write near-duplicate similarity report JSON to this path.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum groups to include; 0 writes all groups.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Report near-duplicate groups from cached deterministic descriptors."""
    from sfxworkbench.similarity import audit_similarity_descriptors

    effective_max_duration = None if max_duration == 0 else max_duration
    effective_db = resolve_db_path(ctx, db)
    try:
        report = audit_similarity_descriptors(
            path,
            db_path=effective_db,
            threshold=threshold,
            max_duration_s=effective_max_duration,
            exclude_exact_md5=not include_exact_md5,
            scope=scope,
            limit=limit,
            output_path=output,
            quiet=json_output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "similarity_audit",
                    "root": path,
                    "db_path": effective_db,
                    "report_path": output,
                    "report": report,
                }
            )
        )


@similarity_feedback_app.command("set")
def cmd_similarity_feedback_set(
    ctx: typer.Context,
    left: Annotated[Path, typer.Option("--left", help="Indexed left-side file path.")],
    right: Annotated[Path, typer.Option("--right", help="Indexed right-side file path.")],
    state: Annotated[
        str,
        typer.Option("--state", help="Review state: favorite, hidden, ignored, accepted, or rejected."),
    ],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    scope: Annotated[str, typer.Option("--scope", help="Feedback scope: 'file' or 'segment'.")] = "file",
    left_segment: Annotated[
        int | None, typer.Option("--left-segment", help="Left segment index for segment feedback.")
    ] = None,
    right_segment: Annotated[
        int | None, typer.Option("--right-segment", help="Right segment index for segment feedback.")
    ] = None,
    max_duration: Annotated[
        float | None,
        typer.Option(
            "--max-duration", help="Descriptor analysis window for segment lookup; 0 uses full-file segments."
        ),
    ] = 30.0,
    note: Annotated[str | None, typer.Option("--note", help="Optional reviewer note.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Set a DB-only review state for a similarity relationship."""
    from sfxworkbench.similarity import set_similarity_feedback

    effective_max_duration = None if max_duration == 0 else max_duration
    effective_db = resolve_db_path(ctx, db)
    try:
        result = set_similarity_feedback(
            left_path=left,
            right_path=right,
            state=state,
            db_path=effective_db,
            scope=scope,
            left_segment_index=left_segment,
            right_segment_index=right_segment,
            max_duration_s=effective_max_duration,
            note=note,
            quiet=json_output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "similarity_feedback_set",
                    "db_path": effective_db,
                    "result": result,
                }
            )
        )


@similarity_feedback_app.command("list")
def cmd_similarity_feedback_list(
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    scope: Annotated[str | None, typer.Option("--scope", help="Filter to 'file' or 'segment'.")] = None,
    state: Annotated[
        str | None,
        typer.Option("--state", help="Filter to favorite, hidden, ignored, accepted, or rejected."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum entries to include; 0 writes all.")] = 200,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List DB-only similarity review states."""
    from sfxworkbench.similarity import list_similarity_feedback

    effective_db = resolve_db_path(ctx, db)
    try:
        report = list_similarity_feedback(
            db_path=effective_db, scope=scope, state=state, limit=limit, quiet=json_output
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "similarity_feedback_list",
                    "db_path": effective_db,
                    "report": report,
                }
            )
        )


@similarity_feedback_app.command("clear")
def cmd_similarity_feedback_clear(
    ctx: typer.Context,
    left: Annotated[Path, typer.Option("--left", help="Indexed left-side file path.")],
    right: Annotated[Path, typer.Option("--right", help="Indexed right-side file path.")],
    db: Annotated[Path | None, typer.Option("--db", help="Path to the SQLite index.")] = None,
    scope: Annotated[str, typer.Option("--scope", help="Feedback scope: 'file' or 'segment'.")] = "file",
    left_segment: Annotated[
        int | None, typer.Option("--left-segment", help="Left segment index for segment feedback.")
    ] = None,
    right_segment: Annotated[
        int | None, typer.Option("--right-segment", help="Right segment index for segment feedback.")
    ] = None,
    max_duration: Annotated[
        float | None,
        typer.Option(
            "--max-duration", help="Descriptor analysis window for segment lookup; 0 uses full-file segments."
        ),
    ] = 30.0,
    state: Annotated[
        str | None,
        typer.Option("--state", help="Only clear this state if the relationship currently has it."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Clear a DB-only review state for a similarity relationship."""
    from sfxworkbench.similarity import clear_similarity_feedback

    effective_max_duration = None if max_duration == 0 else max_duration
    effective_db = resolve_db_path(ctx, db)
    try:
        result = clear_similarity_feedback(
            left_path=left,
            right_path=right,
            db_path=effective_db,
            scope=scope,
            left_segment_index=left_segment,
            right_segment_index=right_segment,
            max_duration_s=effective_max_duration,
            state=state,
            quiet=json_output,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e
    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "similarity_feedback_clear",
                    "db_path": effective_db,
                    "result": result,
                }
            )
        )
