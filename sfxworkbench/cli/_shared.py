"""Shared helpers for the CLI package.

The active :class:`sfxworkbench.config.Config` is stashed on
``typer.Context.obj`` by the top-level ``_main`` callback. Subcommands that
want to honor user-set defaults call the resolvers in this module rather than
poking at ``ctx.obj`` directly — keeps the precedence logic in one place and
makes the "CLI flag wins, then config, then bake-in default" contract obvious
at the call site.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sfxworkbench.db import DEFAULT_DB_PATH

if TYPE_CHECKING:
    import typer

    from sfxworkbench.config import Config


def _active_config(ctx: typer.Context) -> Config | None:
    """Return the Config attached to *ctx*, or ``None`` when callers bypass _main."""
    from sfxworkbench.config import Config  # local import to avoid the typer dep at module load

    return ctx.obj if isinstance(ctx.obj, Config) else None


def resolve_db_path(ctx: typer.Context, cli_value: Path | None) -> Path:
    """Resolve the effective SQLite index path.

    Precedence: explicit CLI flag → ``Config.db_path`` → package default
    (``~/.sfxworkbench/index.db``). Commands that want to honor user config
    should declare ``db: Path | None = None`` and call this helper.
    """
    if cli_value is not None:
        return cli_value
    config = _active_config(ctx)
    if config is not None and config.db_path is not None:
        return config.db_path
    return DEFAULT_DB_PATH


def resolve_ucs_catalog_path(ctx: typer.Context, cli_value: Path | None) -> Path | None:
    """Resolve the UCS catalog path with CLI > Config precedence.

    Returns ``None`` when nothing is set; the loader functions handle that case
    by walking their own discovery chain (env var, default cache file).
    """
    if cli_value is not None:
        return cli_value
    config = _active_config(ctx)
    if config is not None:
        return config.ucs_catalog_path
    return None


def resolve_library_root(ctx: typer.Context, cli_value: Path | None) -> Path | None:
    """Resolve the library root with CLI > Config precedence (no default)."""
    if cli_value is not None:
        return cli_value
    config = _active_config(ctx)
    if config is not None:
        return config.library_root
    return None


def require_file(path: Path, *, kind: str = "file") -> None:
    """Print a red error and exit 1 when ``path`` does not exist.

    Used to collapse the ``if not X.exists(): console.print(red); raise Exit(1)``
    triplet that opens nearly every CLI subcommand.
    """
    import typer
    from rich.console import Console

    if not path.exists():
        Console().print(f"[red]Error: {kind} not found: {path}[/red]")
        raise typer.Exit(1)


def print_json_result(command: str, **payload) -> None:
    """Emit a stable ``{schema_version, command, ...}`` JSON envelope to stdout.

    All commands wrap their machine-readable output the same way; this helper
    keeps the schema version + envelope shape pinned in one place.
    """
    from sfxworkbench.utils import json_dumps

    print(json_dumps({"schema_version": 1, "command": command, **payload}))
