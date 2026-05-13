"""`sfx ls` — beets-style query against the SQLite index.

A read-only lookup. Compiles the query DSL in :mod:`sfxworkbench.query` to a
parameterized ``WHERE`` clause and prints a Rich table (or JSON, with
``--json``). The output is intentionally minimal: path, format, channels,
sample rate, size. Power users who need richer projection can fall back to
``sqlite3 sfxworkbench.db`` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from sfxworkbench.cli._shared import resolve_db_path
from sfxworkbench.db import connection
from sfxworkbench.query import FIELD_ALIASES, QueryError, compile_query, parse_query
from sfxworkbench.utils import fmt_bytes, json_dumps

console = Console()


# Columns selected for both the JSON output and the table. Keeping the set
# narrow makes the table render readably even on narrow terminals; the JSON
# output is more verbose and adds a ``has_*`` block.
_SELECT_COLUMNS = (
    "id",
    "path",
    "filename",
    "extension",
    "size_bytes",
    "sample_rate",
    "bit_depth",
    "channels",
    "duration_s",
    "md5",
    "has_bext",
    "has_ixml",
    "has_riff_info",
)


def _resolve_sort_column(raw: str) -> str | None:
    """Translate a user-typed sort key into the actual SQL column name.

    Honors the query DSL's :data:`FIELD_ALIASES` so ``--sort size`` /
    ``--sort rate`` / ``--sort duration`` all work the same way they do in a
    query body. Returns ``None`` if no mapping exists.
    """
    if raw in _SELECT_COLUMNS:
        return raw
    aliased = FIELD_ALIASES.get(raw.lower())
    if aliased in _SELECT_COLUMNS:
        return aliased
    return None


def ls(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Query string in the sfxworkbench DSL (e.g. 'ext:wav rate:>=48000').")],
    db: Annotated[
        Path | None,
        typer.Option("--db", help="Path to the SQLite index. Falls back to Config.db_path."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum rows to print. 0 prints all.")] = 100,
    sort: Annotated[
        str,
        typer.Option(
            "--sort",
            help="Column to sort by. Prefix with ``-`` for descending (e.g. ``-size``).",
        ),
    ] = "path",
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Query the SQLite index using the sfxworkbench DSL.

    Examples:

        sfx ls "ext:wav rate:>=48000 missing:bext"
        sfx ls "channels:1 duration:>30 -ext:mp3"
        sfx ls "rain"
    """
    try:
        terms = parse_query(query)
        where_body, params = compile_query(terms)
    except QueryError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    sort_desc = sort.startswith("-")
    sort_raw = sort[1:] if sort_desc else sort
    sort_column = _resolve_sort_column(sort_raw)
    if sort_column is None:
        allowed = sorted(set(_SELECT_COLUMNS) | set(FIELD_ALIASES))
        console.print(
            f"[red]Error: --sort key {sort_raw!r} doesn't resolve to a sortable column. Allowed: {allowed}[/red]"
        )
        raise typer.Exit(1)
    order_clause = f"{sort_column} {'DESC' if sort_desc else 'ASC'}"
    limit_clause = "" if limit == 0 else f" LIMIT {int(limit)}"

    effective_db = resolve_db_path(ctx, db)
    select_cols = ", ".join(_SELECT_COLUMNS)
    sql = (
        f"SELECT {select_cols} FROM files WHERE scan_error IS NULL AND ({where_body}) "
        f"ORDER BY {order_clause}{limit_clause}"
    )

    with connection(effective_db) as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "ls",
                    "db_path": effective_db,
                    "query": query,
                    "matched": len(rows),
                    "limit": limit,
                    "rows": rows,
                }
            )
        )
        return

    if not rows:
        console.print(f"No matches for [cyan]{query}[/cyan]")
        return

    table = Table(title=f"sfx ls — {query}", show_lines=False)
    table.add_column("Path", overflow="fold")
    table.add_column("Format", justify="right")
    table.add_column("Channels", justify="right")
    table.add_column("Rate", justify="right")
    table.add_column("Size", justify="right")
    for row in rows:
        sample_rate = row.get("sample_rate")
        rate_text = f"{sample_rate / 1000:.1f} kHz" if isinstance(sample_rate, (int, float)) and sample_rate else "?"
        size = row.get("size_bytes")
        size_text = fmt_bytes(float(size)) if isinstance(size, (int, float)) else "?"
        channels = row.get("channels")
        channels_text = str(channels) if channels else "?"
        ext = row.get("extension") or ""
        bit_depth = row.get("bit_depth")
        format_text = f"{ext.lstrip('.')}/{bit_depth}b" if ext and bit_depth else (ext.lstrip(".") or "?")
        table.add_row(str(row["path"]), format_text, channels_text, rate_text, size_text)
    console.print(table)
    console.print(f"[dim]{len(rows)} match(es)[/dim]")
