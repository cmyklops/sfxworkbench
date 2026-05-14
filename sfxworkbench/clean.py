"""sfx clean command — find and remove junk files from sound libraries."""

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from sfxworkbench import junk
from sfxworkbench.db import get_connection, path_scope_filter, path_scope_params
from sfxworkbench.models import CleanResult
from sfxworkbench.utils import fmt_bytes

console = Console()
ProgressCallback = Callable[[str, int, int | None, str], None]


def find_junk(
    root: Path,
    quiet: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
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
    if progress_callback is not None:
        progress_callback("walking", 0, None, f"Walking {root}")

    if quiet:
        for item in root.rglob("*"):
            visited += 1
            if progress_callback is not None and visited % 500 == 0:
                progress_callback(
                    "walking",
                    visited,
                    None,
                    f"Walked {visited:,} item(s), found {len(junk_files) + len(junk_dirs):,} junk item(s)",
                )
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
        if progress_callback is not None:
            progress_callback(
                "walking",
                visited,
                visited,
                f"Found {len(junk_files) + len(junk_dirs):,} junk item(s)",
            )
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
                if progress_callback is not None:
                    progress_callback(
                        "walking",
                        visited,
                        None,
                        f"Walked {visited:,} item(s), found {len(junk_files) + len(junk_dirs):,} junk item(s)",
                    )
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

    if progress_callback is not None:
        progress_callback(
            "walking",
            visited,
            visited,
            f"Found {len(junk_files) + len(junk_dirs):,} junk item(s)",
        )
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


def _drop_indexed_rows_under(db_path: Path, deleted_paths: list[Path]) -> int:
    """Remove rows from ``files`` matching any path in *deleted_paths* or below.

    Junk cleanup unlinks files on disk. Most junk (``.DS_Store``, ``__MACOSX``)
    isn't indexed, but if anything tracked by the index gets removed the row
    must go too — otherwise the status strip keeps counting its bytes.
    """
    if not deleted_paths:
        return 0
    conn = get_connection(db_path)
    try:
        removed = 0
        for path in deleted_paths:
            cursor = conn.execute(
                f"DELETE FROM files WHERE {path_scope_filter()}",
                path_scope_params(path),
            )
            removed += cursor.rowcount or 0
        conn.commit()
    finally:
        conn.close()
    return removed


def clean_library(
    root: Path,
    dry_run: bool = True,
    log_path: Path | None = None,
    quiet: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    db_path: Path | None = None,
) -> CleanResult:
    """Find and optionally delete junk. Always dry_run unless dry_run=False.
    Writes JSON log of everything removed to log_path if provided.

    ``cancel_requested`` polled every 50 entries during the delete loop.
    Already-removed files stay removed — there is no rollback. The log
    still reflects whatever was completed before cancellation fired.
    """
    root = root.resolve()
    junk_files, junk_dirs = find_junk(root, quiet=quiet, progress_callback=progress_callback)

    planned_bytes = sum(sz for _, sz in junk_files) + sum(sz for _, sz in junk_dirs)
    removed_files = [str(f) for f, _ in junk_files] if dry_run else []
    removed_dirs = [str(d) for d, _ in junk_dirs] if dry_run else []
    bytes_freed = planned_bytes if dry_run else 0

    result = CleanResult(
        removed_files=removed_files,
        removed_dirs=removed_dirs,
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
            f"{action} [yellow]{fmt_bytes(planned_bytes)}[/yellow]"
        )

    cancelled = False
    if not dry_run:
        from sfxworkbench.utils import progress_interval

        total = len(junk_files) + len(junk_dirs)
        report_every = progress_interval(total)
        completed = 0
        for f, size in junk_files:
            try:
                f.unlink()
                result.removed_files.append(str(f))
                result.bytes_freed += size
            except OSError as e:
                if not quiet:
                    console.print(f"[red]Error removing {f}: {e}[/red]")
            completed += 1
            if progress_callback is not None and (completed % report_every == 0 or completed == total):
                progress_callback("cleaning", completed, total, f"Removed {f.name}")
            # Cancellation poll: every 50 file deletes (cheap individually)
            # so a tens-of-thousands-of-DS_Store-siblings cleanup is responsive.
            if completed % 50 == 0 and cancel_requested is not None and cancel_requested():
                cancelled = True
                break
        if not cancelled:
            for d, size in junk_dirs:
                try:
                    shutil.rmtree(d)
                    result.removed_dirs.append(str(d))
                    result.bytes_freed += size
                except OSError as e:
                    if not quiet:
                        console.print(f"[red]Error removing {d}: {e}[/red]")
                completed += 1
                if progress_callback is not None and (completed % report_every == 0 or completed == total):
                    progress_callback("cleaning", completed, total, f"Removed {d.name}")
                if completed % 50 == 0 and cancel_requested is not None and cancel_requested():
                    cancelled = True
                    break
        if db_path is not None and (result.removed_files or result.removed_dirs):
            _drop_indexed_rows_under(
                db_path,
                [Path(p) for p in result.removed_files] + [Path(p) for p in result.removed_dirs],
            )
    elif progress_callback is not None:
        total = len(junk_files) + len(junk_dirs)
        progress_callback("preview", total, total, f"Previewed {total:,} junk item(s)")
        if not quiet:
            console.print("[green]Done.[/green]")
    result.cancelled = cancelled

    if log_path is not None:
        log_data = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "root": str(root),
            "dry_run": dry_run,
            "removed_files": result.removed_files,
            "removed_dirs": result.removed_dirs,
            "bytes_freed": result.bytes_freed,
            "cancelled": result.cancelled,
        }
        log_path.write_text(json.dumps(log_data, indent=2))
        if not quiet:
            console.print(f"Log written to [cyan]{log_path}[/cyan]")

    return result
