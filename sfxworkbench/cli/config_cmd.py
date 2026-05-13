"""`sfx config` subapp — show + validate the loaded :class:`sfxworkbench.config.Config`.

This is the first subcommand that actively reads from ``typer.Context.obj``
(populated by the top-level ``_main`` callback). It demonstrates the pattern
that other commands can adopt incrementally: pull defaults from the resolved
config when CLI flags aren't passed.

Named ``config_cmd.py`` rather than ``config.py`` to avoid shadowing the
``sfxworkbench.config`` module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from sfxworkbench.config import Config, ConfigError, load_config
from sfxworkbench.utils import json_dumps

console = Console()

config_app = typer.Typer(
    name="config",
    help="Inspect and validate the active sfxworkbench configuration.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _resolved_config(ctx: typer.Context) -> Config:
    """Return the Config attached to *ctx*, falling back to defaults if absent.

    The top-level ``_main`` callback sets ``ctx.obj`` to the loaded Config.
    Defensive callers (tests, direct ``runner.invoke`` without going through
    the main app) might bypass that — fall back to a fresh ``load_config()``.
    """
    obj = ctx.obj
    if isinstance(obj, Config):
        return obj
    return load_config()


@config_app.command("show")
def cmd_config_show(
    ctx: typer.Context,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Print the effective configuration as resolved from the precedence chain."""
    config = _resolved_config(ctx)
    if json_output:
        print(json_dumps(config))
        return

    table = Table(title="sfxworkbench config", show_lines=False)
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("library_root", str(config.library_root) if config.library_root else "(unset)")
    table.add_row("db_path", str(config.db_path) if config.db_path else "(default)")
    table.add_row("ucs_catalog_path", str(config.ucs_catalog_path) if config.ucs_catalog_path else "(default)")
    table.add_row("backup.enabled", str(config.backup.enabled))
    table.add_row("backup.retain_days", str(config.backup.retain_days))
    table.add_row("confidence.ucs_heuristic", f"{config.confidence.ucs_heuristic:.2f}")
    table.add_row("confidence.ucs_catalog", f"{config.confidence.ucs_catalog:.2f}")
    table.add_row("confidence.group", f"{config.confidence.group:.2f}")
    table.add_row("confidence.filename_abbreviation", f"{config.confidence.filename_abbreviation:.2f}")
    table.add_row("confidence.filename_take", f"{config.confidence.filename_take:.2f}")
    table.add_row("confidence.filename_description", f"{config.confidence.filename_description:.2f}")
    table.add_row("confidence.path", f"{config.confidence.path:.2f}")
    table.add_row("confidence.synonym", f"{config.confidence.synonym:.2f}")
    console.print(table)


@config_app.command("validate")
def cmd_config_validate(
    path: Annotated[
        Path | None,
        typer.Argument(help="Config file to validate. Defaults to whatever the precedence chain resolves."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """Validate a TOML config file against the :class:`Config` schema."""
    try:
        config = load_config(config_path=path)
    except ConfigError as exc:
        if json_output:
            print(json_dumps({"schema_version": 1, "command": "config_validate", "ok": False, "error": str(exc)}))
        else:
            console.print(f"[red]Invalid config: {exc}[/red]")
        raise typer.Exit(1) from exc

    if json_output:
        print(
            json_dumps(
                {
                    "schema_version": 1,
                    "command": "config_validate",
                    "ok": True,
                    "config_path": path,
                    "config": config,
                }
            )
        )
    else:
        target = path or "(default precedence chain)"
        console.print(f"[green]OK[/green] {target} — config is valid.")
