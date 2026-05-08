"""sfx clean command — find and remove junk files from sound libraries."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from wavwarden import junk
from wavwarden.models import CleanResult
from wavwarden.utils import fmt_bytes

console = Console()


def find_junk(root: Path, quiet: bool = False) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
    """Walk `root` and return (junk_files, junk_dirs).

    Each entry is `(path, size_bytes)` — sizes are captured during the walk
    so we never need to stat() the same file twice. junk_dirs entries
    contain the total size of the directory subtree.

    Shows a transient spinner with a live counter while walking.
    """
    junk_files: list[tuple[Path, int]] = []
    junk_dirs: list[tuple[Path, int]] = []
    seen_dirs: set[Path] = set()
    visited = 0

    if quiet:
        for item in root.rglob("*"):
            if any(item.is_relative_to(jd) for jd in seen_dirs):
                continue
            if item.is_dir():
                if junk.is_junk_dir(item):
                    dir_size = _dir_size(item)
                    junk_dirs.append((item, dir_size))
                    seen_dirs.add(item)
            elif item.is_file() and junk.is_junk_file(item):
                try:
                    size = item.stat().st_size
                except OSError:
                    size = 0
                junk_files.append((item, size))
        return junk_files, junk_dirs

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Walking...", total=None)

        for item in root.rglob("*"):
            visited += 1
            if visited % 500 == 0:
                progress.update(
                    task,
                    description=(
                        f"Walking... [white]{visited:,}[/white] items, "
                        f"[yellow]{len(junk_files) + len(junk_dirs):,}[/yellow] junk found"
                    ),
                )

            # Skip items already inside a marked junk dir
            if any(item.is_relative_to(jd) for jd in seen_dirs):
                continue

            if item.is_dir():
                if junk.is_junk_dir(item):
                    dir_size = _dir_size(item)
                    junk_dirs.append((item, dir_size))
                    seen_dirs.add(item)
            elif item.is_file():
                if junk.is_junk_file(item):
                    try:
                        size = item.stat().st_size
                    except OSError:
                        size = 0
                    junk_files.append((item, size))

    return junk_files, junk_dirs


def _dir_size(path: Path) -> int:
    """Total size of all files under a directory."""
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def clean_library(
    root: Path,
    dry_run: bool = True,
    log_path: Path | None = None,
    quiet: bool = False,
) -> CleanResult:
    """Find and optionally delete junk. Always dry_run unless dry_run=False.
    Writes JSON log of everything removed to log_path if provided."""
    root = root.resolve()
    junk_files, junk_dirs = find_junk(root, quiet=quiet)

    bytes_freed = sum(sz for _, sz in junk_files) + sum(sz for _, sz in junk_dirs)

    result = CleanResult(
        removed_files=[str(f) for f, _ in junk_files],
        removed_dirs=[str(d) for d, _ in junk_dirs],
        bytes_freed=bytes_freed,
        dry_run=dry_run,
    )

    if not quiet:
        # Build display table using cached sizes
        table = Table(title=f"{'[DRY RUN] ' if dry_run else ''}Junk found in {root}", show_lines=False)
        table.add_column("Type", style="cyan", no_wrap=True)
        table.add_column("Path", style="white")
        table.add_column("Size", style="yellow", justify="right")

        for f, sz in junk_files:
            table.add_row("file", str(f.relative_to(root)), fmt_bytes(sz))
        for d, sz in junk_dirs:
            table.add_row("dir", str(d.relative_to(root)) + "/", fmt_bytes(sz))

        console.print(table)

        action = "Would free" if dry_run else "Freed"
        total = len(junk_files) + len(junk_dirs)
        console.print(
            f"\n{total} item(s) ({len(junk_files)} files, {len(junk_dirs)} dirs), "
            f"{action} [yellow]{fmt_bytes(bytes_freed)}[/yellow]"
        )

    if not dry_run:
        for f, _ in junk_files:
            try:
                f.unlink()
            except OSError as e:
                if not quiet:
                    console.print(f"[red]Error removing {f}: {e}[/red]")
        for d, _ in junk_dirs:
            try:
                shutil.rmtree(d)
            except OSError as e:
                if not quiet:
                    console.print(f"[red]Error removing {d}: {e}[/red]")
        if not quiet:
            console.print("[green]Done.[/green]")

    if log_path is not None:
        log_data = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "root": str(root),
            "dry_run": dry_run,
            "removed_files": result.removed_files,
            "removed_dirs": result.removed_dirs,
            "bytes_freed": bytes_freed,
        }
        log_path.write_text(json.dumps(log_data, indent=2))
        if not quiet:
            console.print(f"Log written to [cyan]{log_path}[/cyan]")

    return result
