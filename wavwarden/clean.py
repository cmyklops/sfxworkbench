"""sfx clean command — find and remove junk files from sound libraries."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden.models import CleanResult

# Audio extensions that must never be touched
AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".w64", ".rf64"}

# Entire directory trees to remove
_JUNK_DIR_NAMES = {"_wfCache", "__MACOSX"}

# Exact filename matches
_JUNK_FILENAMES = {".DS_Store", "desktop.ini", "Thumbs.db"}

# Glob-style suffix matches (lowercase)
_JUNK_SUFFIXES = {".reapeaks", ".sfk", ".pkf", ".wf"}

console = Console()


def _is_junk_file(path: Path) -> bool:
    """Return True if this file is junk (should be cleaned)."""
    name = path.name
    # AppleDouble files
    if name.startswith("._"):
        return True
    # Exact matches
    if name in _JUNK_FILENAMES:
        return True
    # Suffix matches
    if path.suffix.lower() in _JUNK_SUFFIXES:
        return True
    return False


def _is_junk_dir(path: Path) -> bool:
    """Return True if this entire directory should be removed."""
    return path.name in _JUNK_DIR_NAMES


def find_junk(root: Path) -> tuple[list[Path], list[Path]]:
    """Returns (junk_files, junk_dirs). junk_dirs are entire dirs to remove."""
    junk_files: list[Path] = []
    junk_dirs: list[Path] = []
    seen_dirs: set[Path] = set()

    for item in root.rglob("*"):
        # Skip items already inside a marked junk dir
        skip = False
        for jd in seen_dirs:
            try:
                item.relative_to(jd)
                skip = True
                break
            except ValueError:
                pass
        if skip:
            continue

        if item.is_dir():
            if _is_junk_dir(item):
                junk_dirs.append(item)
                seen_dirs.add(item)
        elif item.is_file():
            if _is_junk_file(item):
                # AppleDouble files (._*) are ALWAYS junk regardless of extension.
                # For other patterns, never touch audio extensions as a safety guard.
                if item.name.startswith("._") or item.suffix.lower() not in AUDIO_EXTENSIONS:
                    junk_files.append(item)

    return junk_files, junk_dirs


def clean_library(
    root: Path,
    dry_run: bool = True,
    log_path: Path | None = None,
) -> CleanResult:
    """Find and optionally delete junk. Always dry_run unless dry_run=False.
    Writes JSON log of everything removed to log_path if provided."""
    root = root.resolve()
    junk_files, junk_dirs = find_junk(root)

    result = CleanResult(dry_run=dry_run)

    # Calculate sizes
    bytes_freed = 0
    for f in junk_files:
        try:
            bytes_freed += f.stat().st_size
        except OSError:
            pass
    for d in junk_dirs:
        for item in d.rglob("*"):
            if item.is_file():
                try:
                    bytes_freed += item.stat().st_size
                except OSError:
                    pass

    result.removed_files = [str(f) for f in junk_files]
    result.removed_dirs = [str(d) for d in junk_dirs]
    result.bytes_freed = bytes_freed

    # Build display table
    table = Table(title=f"{'[DRY RUN] ' if dry_run else ''}Junk found in {root}", show_lines=False)
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("Path", style="white")
    table.add_column("Size", style="yellow", justify="right")

    for f in junk_files:
        try:
            sz = _fmt_bytes(f.stat().st_size)
        except OSError:
            sz = "?"
        table.add_row("file", str(f.relative_to(root)), sz)

    for d in junk_dirs:
        dir_size = sum(
            item.stat().st_size
            for item in d.rglob("*")
            if item.is_file()
        )
        table.add_row("dir", str(d.relative_to(root)) + "/", _fmt_bytes(dir_size))

    console.print(table)

    action = "Would free" if dry_run else "Freed"
    total = len(junk_files) + len(junk_dirs)
    console.print(
        f"\n{total} item(s) ({len(junk_files)} files, {len(junk_dirs)} dirs), "
        f"{action} [yellow]{_fmt_bytes(bytes_freed)}[/yellow]"
    )

    if not dry_run:
        for f in junk_files:
            try:
                f.unlink()
            except OSError as e:
                console.print(f"[red]Error removing {f}: {e}[/red]")
        for d in junk_dirs:
            try:
                shutil.rmtree(d)
            except OSError as e:
                console.print(f"[red]Error removing {d}: {e}[/red]")
        console.print("[green]Done.[/green]")

    if log_path is not None:
        log_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "root": str(root),
            "dry_run": dry_run,
            "removed_files": result.removed_files,
            "removed_dirs": result.removed_dirs,
            "bytes_freed": bytes_freed,
        }
        log_path.write_text(json.dumps(log_data, indent=2))
        console.print(f"Log written to [cyan]{log_path}[/cyan]")

    return result


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
