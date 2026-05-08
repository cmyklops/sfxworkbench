"""sfx scan command — index a library path into SQLite."""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from wavwarden import audio as audio_mod
from wavwarden import health
from wavwarden.db import get_connection
from wavwarden.models import FileRecord

console = Console()

AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".w64", ".rf64"}

# Same junk patterns as clean.py — skip these during scan
_JUNK_DIR_NAMES = {"_wfCache", "__MACOSX"}
_JUNK_FILENAMES = {".DS_Store", "desktop.ini", "Thumbs.db"}
_JUNK_SUFFIXES = {".reapeaks", ".sfk", ".pkf", ".wf"}

_UCS_RE = re.compile(r"^[A-Z]{2,5}_[A-Z]{2,8}(_|$)")


def _looks_ucs(stem: str) -> bool:
    return bool(_UCS_RE.match(stem))


def _is_junk(path: Path) -> bool:
    name = path.name
    if name.startswith("._"):
        return True
    if name in _JUNK_FILENAMES:
        return True
    if path.suffix.lower() in _JUNK_SUFFIXES:
        return True
    return False


def _is_inside_junk_dir(path: Path) -> bool:
    for part in path.parts:
        if part in _JUNK_DIR_NAMES:
            return True
    return False


def _md5(path: Path, block: int = 65536) -> str | None:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def scan_library(
    root: Path,
    db_path: Path,
    skip_hash: bool = False,
    force_rescan: bool = False,
) -> dict:
    """Crawl root, index all audio files into SQLite. Incremental by default
    (skips files where mtime and size match existing record)."""
    root = root.resolve()
    conn = get_connection(db_path)

    # Collect all audio files first (for progress bar)
    console.print(f"[cyan]Collecting files under {root}...[/cyan]")
    all_files: list[Path] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if _is_inside_junk_dir(f):
            continue
        if _is_junk(f):
            continue
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            all_files.append(f)

    total = len(all_files)
    console.print(f"Found [yellow]{total:,}[/yellow] audio files.")

    stats = {
        "total": total,
        "scanned": 0,
        "skipped": 0,
        "errors": 0,
    }

    now_str = datetime.now(timezone.utc).isoformat()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Scanning...", total=total)

        for f in all_files:
            progress.advance(task)

            try:
                stat = f.stat()
            except OSError:
                stats["errors"] += 1
                continue

            size = stat.st_size
            mtime = stat.st_mtime

            # Incremental: skip if mtime + size unchanged
            if not force_rescan:
                row = conn.execute(
                    "SELECT id FROM files WHERE path = ? AND mtime = ? AND size_bytes = ?",
                    (str(f), mtime, size),
                ).fetchone()
                if row:
                    stats["skipped"] += 1
                    continue

            # Read audio info
            audio_info = audio_mod.read_audio_info(f)

            # Filename health
            fn_issues = health.check_path(f, root)

            # MD5 hash
            md5 = _md5(f) if not skip_hash else None

            stem = f.stem
            is_ucs = _looks_ucs(stem)

            scan_error = audio_info.error if audio_info else None

            # Upsert into files table
            conn.execute(
                """
                INSERT INTO files (
                    path, filename, stem, extension, size_bytes, mtime, md5,
                    sample_rate, bit_depth, channels, duration_s, subtype,
                    has_bext, has_ixml, is_ucs, scan_error, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    filename=excluded.filename,
                    stem=excluded.stem,
                    extension=excluded.extension,
                    size_bytes=excluded.size_bytes,
                    mtime=excluded.mtime,
                    md5=excluded.md5,
                    sample_rate=excluded.sample_rate,
                    bit_depth=excluded.bit_depth,
                    channels=excluded.channels,
                    duration_s=excluded.duration_s,
                    subtype=excluded.subtype,
                    has_bext=excluded.has_bext,
                    has_ixml=excluded.has_ixml,
                    is_ucs=excluded.is_ucs,
                    scan_error=excluded.scan_error,
                    scanned_at=excluded.scanned_at
                """,
                (
                    str(f),
                    f.name,
                    stem,
                    f.suffix.lower(),
                    size,
                    mtime,
                    md5,
                    audio_info.sample_rate if audio_info else None,
                    audio_info.bit_depth if audio_info else None,
                    audio_info.channels if audio_info else None,
                    audio_info.duration_s if audio_info else None,
                    audio_info.subtype if audio_info else None,
                    int(audio_info.has_bext) if audio_info else 0,
                    int(audio_info.has_ixml) if audio_info else 0,
                    int(is_ucs),
                    scan_error,
                    now_str,
                ),
            )

            # Get the file id for fn_issues
            row = conn.execute("SELECT id FROM files WHERE path = ?", (str(f),)).fetchone()
            if row:
                file_id = row["id"]
                conn.execute("DELETE FROM fn_issues WHERE file_id = ?", (file_id,))
                for issue in fn_issues:
                    conn.execute(
                        "INSERT INTO fn_issues (file_id, component, issue, detail) VALUES (?, ?, ?, ?)",
                        (file_id, issue.component, issue.issue, issue.detail),
                    )

            conn.commit()
            stats["scanned"] += 1

    # Update scan_meta
    conn.execute(
        "INSERT OR REPLACE INTO scan_meta (key, value) VALUES (?, ?)",
        ("last_scan_root", str(root)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO scan_meta (key, value) VALUES (?, ?)",
        ("last_scan_at", now_str),
    )
    conn.commit()
    conn.close()

    console.print(
        f"\n[green]Scan complete.[/green] "
        f"Scanned: [yellow]{stats['scanned']:,}[/yellow], "
        f"Skipped (unchanged): [cyan]{stats['skipped']:,}[/cyan], "
        f"Errors: [red]{stats['errors']:,}[/red]"
    )

    return stats
