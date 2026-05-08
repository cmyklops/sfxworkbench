"""sfx scan command — index a library path into SQLite."""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from wavwarden import audio as audio_mod
from wavwarden import health, junk
from wavwarden.db import get_connection
from wavwarden.models import ScanResult

console = Console()

_UCS_RE = re.compile(r"^[A-Z]{2,5}_[A-Z]{2,8}(_|$)")

# Commit every N files to balance throughput vs. crash-recovery granularity.
_COMMIT_BATCH = 500


def _looks_ucs(stem: str) -> bool:
    return bool(_UCS_RE.match(stem))


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
) -> ScanResult:
    """Crawl root, index all audio files into SQLite. Incremental by default
    (skips files where mtime + size match existing record)."""
    root = root.resolve()
    conn = get_connection(db_path)

    # Collect all audio files first (for an accurate progress bar)
    console.print(f"[cyan]Collecting files under {root}...[/cyan]")
    all_files: list[Path] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if junk.is_inside_junk_dir(f):
            continue
        if junk.is_junk_file(f):
            continue
        if f.suffix.lower() in junk.AUDIO_EXTENSIONS:
            all_files.append(f)

    total = len(all_files)
    console.print(f"Found [yellow]{total:,}[/yellow] audio files.")

    result = ScanResult(total=total)
    now_str = datetime.now(timezone.utc).isoformat()
    pending = 0  # uncommitted writes since last batch flush

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
                result.errors += 1
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
                    result.skipped += 1
                    continue

            audio_info = audio_mod.read_audio_info(f)
            fn_issues = health.check_path(f, root)
            md5 = _md5(f) if not skip_hash else None
            stem = f.stem
            is_ucs = _looks_ucs(stem)
            scan_error = audio_info.error if audio_info else None

            # Single upsert with RETURNING — avoids the second SELECT id query.
            row = conn.execute(
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
                RETURNING id
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
            ).fetchone()

            if row is not None:
                file_id = row["id"]
                conn.execute("DELETE FROM fn_issues WHERE file_id = ?", (file_id,))
                if fn_issues:
                    conn.executemany(
                        "INSERT INTO fn_issues (file_id, component, issue, detail) VALUES (?, ?, ?, ?)",
                        [(file_id, i.component, i.issue, i.detail) for i in fn_issues],
                    )

            result.scanned += 1
            pending += 1

            # Batched commit for performance
            if pending >= _COMMIT_BATCH:
                conn.commit()
                pending = 0

    # Final flush + scan_meta update
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
        f"Scanned: [yellow]{result.scanned:,}[/yellow], "
        f"Skipped (unchanged): [cyan]{result.skipped:,}[/cyan], "
        f"Errors: [red]{result.errors:,}[/red]"
    )

    return result
