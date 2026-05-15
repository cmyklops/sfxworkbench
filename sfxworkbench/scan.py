"""sfx scan command — index a library path into SQLite."""

import hashlib
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from sfxworkbench import audio as audio_mod
from sfxworkbench import health, junk
from sfxworkbench.db import get_connection
from sfxworkbench.metadata_fields import replace_metadata_fields
from sfxworkbench.models import ScanResult
from sfxworkbench.ucs import looks_ucs
from sfxworkbench.utils import progress_interval

console = Console()

# Commit every N files to balance throughput vs. crash-recovery granularity.
_COMMIT_BATCH = 500
_COLLECT_REPORT_INTERVAL_S = 0.75
_COLLECT_REPORT_DIRS = 250
_COLLECT_REPORT_CANDIDATES = 2_000
_SCAN_REPORT_MAX_INTERVAL = 100

ProgressCallback = Callable[[str, int, int | None, str], None]
CancelCallback = Callable[[], bool]


class _ScanCancelled(Exception):
    """Internal signal used to stop a scan at a safe checkpoint."""


def _should_cancel(cancel_requested: CancelCallback | None) -> bool:
    if cancel_requested is None:
        return False
    try:
        return bool(cancel_requested())
    except Exception:
        return False


def _md5(path: Path, block: int = 65536, cancel_requested: CancelCallback | None = None) -> str | None:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block):
                if _should_cancel(cancel_requested):
                    raise _ScanCancelled
                h.update(chunk)
        return h.hexdigest()
    except _ScanCancelled:
        raise
    except Exception:
        return None


def _collection_message(*, dirs: int, files: int, candidates: int, current: Path | None = None) -> str:
    location = f"; now {current}" if current is not None else ""
    return (
        f"Walked {dirs:,} dir(s), inspected {files:,} file(s), "
        f"found {candidates:,} audio candidate(s){location}"
    )


def _scan_progress_message(
    *,
    processed: int,
    total: int,
    scanned: int,
    skipped: int,
    errors: int,
    current: Path | str | None = None,
) -> str:
    prefix = (
        f"Processed {processed:,}/{total:,}; indexed {scanned:,}, "
        f"skipped {skipped:,}, errors {errors:,}"
    )
    if current is None:
        return prefix
    name = current.name if isinstance(current, Path) else str(current)
    return f"{prefix}; current {name}"


def _collect_audio_files(
    root: Path,
    cancel_requested: CancelCallback | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[Path]:
    """Return indexable audio files while pruning known junk directory trees."""
    if junk.is_inside_junk_dir(root):
        return []

    all_files: list[Path] = []
    dirs_seen = 0
    files_seen = 0
    last_report_at = time.monotonic()
    last_report_dirs = 0
    last_report_candidates = 0

    def report(current: Path | None = None, *, force: bool = False) -> None:
        nonlocal last_report_at, last_report_dirs, last_report_candidates
        if progress_callback is None:
            return
        now = time.monotonic()
        enough_time = now - last_report_at >= _COLLECT_REPORT_INTERVAL_S
        enough_dirs = dirs_seen - last_report_dirs >= _COLLECT_REPORT_DIRS
        enough_candidates = len(all_files) - last_report_candidates >= _COLLECT_REPORT_CANDIDATES
        if not force and not (enough_time or enough_dirs or enough_candidates):
            return
        last_report_at = now
        last_report_dirs = dirs_seen
        last_report_candidates = len(all_files)
        progress_callback(
            "collecting",
            len(all_files),
            None,
            _collection_message(dirs=dirs_seen, files=files_seen, candidates=len(all_files), current=current),
        )

    for dirpath, dirnames, filenames in os.walk(root):
        if _should_cancel(cancel_requested):
            break
        dirs_seen += 1
        files_seen += len(filenames)
        dirnames[:] = [dirname for dirname in dirnames if dirname not in junk.JUNK_DIR_NAMES]
        parent = Path(dirpath)
        for filename in filenames:
            if _should_cancel(cancel_requested):
                break
            if filename.startswith(junk.APPLE_DOUBLE_PREFIX):
                continue
            suffix = os.path.splitext(filename)[1].lower()
            if suffix not in junk.AUDIO_EXTENSIONS:
                continue
            f = parent / filename
            if not f.is_file():
                continue
            all_files.append(f)
        report(parent)
    report(root, force=True)
    return all_files


def scan_library(
    root: Path,
    db_path: Path,
    skip_hash: bool = False,
    force_rescan: bool = False,
    quiet: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> ScanResult:
    """Crawl root, index all audio files into SQLite. Incremental by default
    (skips files where mtime + size match existing record)."""
    root = root.resolve()
    conn = get_connection(db_path)

    # Collect all audio files first (for an accurate progress bar)
    if not quiet:
        console.print(f"[cyan]Collecting files under {root}...[/cyan]")
    if progress_callback is not None:
        progress_callback("collecting", 0, None, f"Collecting files under {root}")
    all_files = _collect_audio_files(root, cancel_requested=cancel_requested, progress_callback=progress_callback)

    total = len(all_files)
    if not quiet:
        console.print(f"Found [yellow]{total:,}[/yellow] audio files.")
    if progress_callback is not None:
        progress_callback(
            "scanning",
            0,
            total,
            _scan_progress_message(processed=0, total=total, scanned=0, skipped=0, errors=0),
        )
    # A 500k-file library would otherwise update only every 5k files. Keep
    # large scans visibly alive while still bounding UI/job-progress churn.
    report_every = min(progress_interval(total), _SCAN_REPORT_MAX_INTERVAL)

    result = ScanResult(total=total)
    now_str = datetime.now(UTC).isoformat()
    pending = 0  # uncommitted writes since last batch flush
    processed = 0
    cancelled = _should_cancel(cancel_requested)

    progress = None
    if not quiet:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
            transient=False,
        )

    def scan_one(f: Path) -> None:
        nonlocal pending
        if _should_cancel(cancel_requested):
            raise _ScanCancelled
        try:
            stat = f.stat()
        except OSError:
            result.errors += 1
            return

        size = stat.st_size
        mtime = stat.st_mtime

        # Incremental: skip if mtime + size unchanged
        if not force_rescan:
            existing = conn.execute(
                "SELECT id FROM files WHERE path = ? AND mtime = ? AND size_bytes = ?",
                (str(f), mtime, size),
            ).fetchone()
            if existing:
                result.skipped += 1
                return

        audio_info = audio_mod.read_audio_info(f)
        fn_issues = health.check_path(f, root)
        md5 = _md5(f, cancel_requested=cancel_requested) if not skip_hash else None
        stem = f.stem
        is_ucs = looks_ucs(stem)
        scan_error = audio_info.error if audio_info else None
        metadata_sources = json.dumps(audio_info.metadata_sources if audio_info else [])

        # Single upsert with RETURNING — avoids the second SELECT id query.
        row = conn.execute(
            """
            INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, md5,
                sample_rate, bit_depth, channels, duration_s, subtype,
                has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
                has_sampler, metadata_sources, is_ucs, scan_error, scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                has_riff_info=excluded.has_riff_info,
                has_adm=excluded.has_adm,
                has_cue_markers=excluded.has_cue_markers,
                has_sampler=excluded.has_sampler,
                metadata_sources=excluded.metadata_sources,
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
                int(audio_info.has_riff_info) if audio_info else 0,
                int(audio_info.has_adm) if audio_info else 0,
                int(audio_info.has_cue_markers) if audio_info else 0,
                int(audio_info.has_sampler) if audio_info else 0,
                metadata_sources,
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
            replace_metadata_fields(conn, file_id=file_id, path=f, audio_info=audio_info, updated_at=now_str)

        result.scanned += 1
        pending += 1

        # Batched commit for performance
        if pending >= _COMMIT_BATCH:
            conn.commit()
            pending = 0

    if progress is None:
        for f in all_files:
            if _should_cancel(cancel_requested):
                cancelled = True
                break
            try:
                scan_one(f)
            except _ScanCancelled:
                cancelled = True
                break
            processed += 1
            if progress_callback is not None and (processed % report_every == 0 or processed == total):
                progress_callback(
                    "scanning",
                    processed,
                    total,
                    _scan_progress_message(
                        processed=processed,
                        total=total,
                        scanned=result.scanned,
                        skipped=result.skipped,
                        errors=result.errors,
                        current=f,
                    ),
                )
    else:
        with progress:
            task = progress.add_task(
                _scan_progress_message(processed=0, total=total, scanned=0, skipped=0, errors=0),
                total=total,
            )
            for f in all_files:
                if _should_cancel(cancel_requested):
                    cancelled = True
                    break
                try:
                    scan_one(f)
                except _ScanCancelled:
                    cancelled = True
                    break
                progress.advance(task)
                processed += 1
                description = _scan_progress_message(
                    processed=processed,
                    total=total,
                    scanned=result.scanned,
                    skipped=result.skipped,
                    errors=result.errors,
                    current=f,
                )
                if processed % report_every == 0 or processed == total:
                    progress.update(task, description=description)
                if progress_callback is not None and (processed % report_every == 0 or processed == total):
                    progress_callback("scanning", processed, total, description)

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

    if progress_callback is not None:
        phase = "cancelled" if cancelled else "complete"
        final_message = _scan_progress_message(
            processed=processed,
            total=total,
            scanned=result.scanned,
            skipped=result.skipped,
            errors=result.errors,
        )
        progress_callback(phase, processed, total, f"{'Scan cancelled' if cancelled else 'Scan complete'}: {final_message}")
    if not quiet:
        state = "[yellow]Scan cancelled.[/yellow]" if cancelled else "[green]Scan complete.[/green]"
        console.print(
            f"\n{state} "
            f"Scanned: [yellow]{result.scanned:,}[/yellow], "
            f"Skipped (unchanged): [cyan]{result.skipped:,}[/cyan], "
            f"Errors: [red]{result.errors:,}[/red]"
        )

    return result
