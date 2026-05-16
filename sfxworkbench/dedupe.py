"""sfx dedupe command — find and quarantine duplicate files."""

import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.apply_logs import (
    default_apply_log_path_for_plan,
    mark_groups_approved,
    write_apply_log,
)
from sfxworkbench.db import get_connection
from sfxworkbench.models import DedupeApplyResult, DedupeGroup, DedupeReviewResult, DedupeSummary
from sfxworkbench.path_safety import path_exists_windows
from sfxworkbench.preservation import build_preservation_rules, evidence, priority_key, protected_by
from sfxworkbench.utils import fmt_bytes

console = Console()

PLAN_SCHEMA_VERSION = 1
_PROGRESS_MAX_INTERVAL = 100


def _dedupe_apply_progress_message(
    *,
    processed: int,
    total: int,
    removed: int,
    quarantined: int,
    skipped: int,
    errors: int,
    bytes_freed: int,
    current: str | None = None,
) -> str:
    message = (
        f"Processed {processed:,}/{total:,}; removed {removed:,}, "
        f"quarantined {quarantined:,}, skipped {skipped:,}, "
        f"errors {errors:,}, freed {fmt_bytes(bytes_freed)}"
    )
    if current:
        return f"{message}; current {Path(current).name}"
    return message


def _dedupe_finalizing_message(*, affected_paths: int, removed_rows: int | None = None) -> str:
    if removed_rows is None:
        return f"Updating index for {affected_paths:,} affected duplicate path(s)"
    return f"Updated index for {affected_paths:,} affected duplicate path(s); dropped {removed_rows:,} row(s)"


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _md5(path: Path, block: int = 65536) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def _default_quarantine_dir(plan_path: Path, root: str | Path | None = None) -> Path:
    base = Path(root).expanduser() if root else plan_path.parent
    return base / f"sfxworkbench_quarantine_{_now_stamp()}"


def _default_dedupe_log_path(plan_path: Path) -> Path:
    return default_apply_log_path_for_plan(plan_path, "dedupe_quarantine_log")


def _quarantine_target(path: Path, quarantine_dir: Path, root: str | Path | None = None) -> Path:
    """Map an absolute source path into a quarantine tree without overwriting."""
    if root:
        try:
            parts = path.resolve().relative_to(Path(root).expanduser().resolve()).parts
        except ValueError:
            drive = path.drive.rstrip(":") or "absolute"
            parts = ("_external", drive, *[part for part in path.parts if part not in (path.anchor, "/")])
    else:
        parts = [part for part in path.parts if part not in (path.anchor, "/")]
    target = quarantine_dir.joinpath(*parts)
    if not path_exists_windows(target):
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    i = 1
    while True:
        candidate = parent / f"{stem}__{i}{suffix}"
        if not path_exists_windows(candidate):
            return candidate
        i += 1


# Single-slot cache for ``find_duplicates`` keyed on a cheap DB-mutation
# signature: (main db mtime, WAL mtime, WAL size). On a 50k-file library the
# GROUP BY MD5 query is a few hundred ms — fine in isolation, but on the
# Dedupe tab it ran on every search-input keystroke debounce. Now it runs
# at most once per DB write, with subsequent reads short-circuiting the cache.
_FIND_DUPLICATES_CACHE: dict[tuple[str, float, float, int], list[DedupeGroup]] = {}


def _db_mutation_signature(db_path: Path) -> tuple[float, float, int]:
    """Return a cheap (stat-only) signal that changes after any DB write.

    SQLite in WAL mode writes commits to the ``-wal`` sidecar; the main DB
    file's mtime only updates during checkpoint. Checking both files'
    mtimes plus the WAL size catches every commit without opening a
    connection. Returns zeros if the DB doesn't exist yet.
    """
    try:
        main_stat = db_path.stat()
    except OSError:
        return (0.0, 0.0, 0)
    wal_path = db_path.with_name(db_path.name + "-wal")
    if wal_path.exists():
        wal_stat = wal_path.stat()
        return (main_stat.st_mtime, wal_stat.st_mtime, wal_stat.st_size)
    return (main_stat.st_mtime, 0.0, 0)


def find_duplicates(db_path: Path, *, ensure_hash: bool = False, root: Path | None = None) -> list[DedupeGroup]:
    """Query the index for files grouped by MD5 where count > 1.

    Uses `json_group_array` so paths are returned as a proper JSON array — no
    fragile ad-hoc separator. Sorted within each group by path for
    deterministic ordering, so the same plan is generated on every run.

    Results are cached per ``(db_path, mutation-signature)``. Any DB write
    invalidates by changing the WAL signature; the next call recomputes.
    """
    if ensure_hash:
        from sfxworkbench.scan import ensure_hashes

        ensure_hashes(db_path, root)
    signature = _db_mutation_signature(db_path)
    cache_key = (str(db_path), *signature)
    cached = _FIND_DUPLICATES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT
            md5,
            size_bytes,
            json_group_array(path) AS paths_json,
            COUNT(*) AS cnt
        FROM (
            SELECT md5, size_bytes, path
            FROM files
            WHERE md5 IS NOT NULL
            ORDER BY md5, path
        )
        GROUP BY md5
        HAVING cnt > 1
        ORDER BY size_bytes DESC
        """
    ).fetchall()
    conn.close()

    groups: list[DedupeGroup] = []
    for row in rows:
        files = json.loads(row["paths_json"])
        groups.append(
            DedupeGroup(
                hash=row["md5"],
                size_bytes=row["size_bytes"],
                files=files,
            )
        )
    # Single-slot cache: evict every other entry so memory doesn't grow
    # with the number of distinct DB paths a session sees.
    _FIND_DUPLICATES_CACHE.clear()
    _FIND_DUPLICATES_CACHE[cache_key] = groups
    return groups


def summarize_duplicates(groups: list[DedupeGroup]) -> DedupeSummary:
    """Return aggregate duplicate counts for review and JSON output."""
    if not groups:
        return DedupeSummary()
    extra_copies = sum(len(group.files) - 1 for group in groups)
    wasted_bytes = sum(group.size_bytes * (len(group.files) - 1) for group in groups)
    duplicate_files = sum(len(group.files) for group in groups)
    largest = max(groups, key=lambda group: group.size_bytes * (len(group.files) - 1))
    return DedupeSummary(
        duplicate_groups=len(groups),
        duplicate_files=duplicate_files,
        extra_copies=extra_copies,
        wasted_bytes=wasted_bytes,
        largest_group_bytes=largest.size_bytes * (len(largest.files) - 1),
        largest_group_copies=len(largest.files),
    )


def write_dedupe_plan(
    groups: list[DedupeGroup],
    plan_path: Path,
    db_path: Path | None = None,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    prefer_folders: list[Path] | None = None,
    prefer_extensions: list[str] | None = None,
) -> None:
    """Write JSON plan: for each group, mark all but the first as 'remove'."""
    rules = build_preservation_rules(
        config_path=config_path,
        safe_folders=safe_folders,
        prefer_folders=prefer_folders,
        prefer_extensions=prefer_extensions,
    )
    root = None
    if db_path is not None:
        conn = get_connection(db_path)
        row = conn.execute("SELECT value FROM scan_meta WHERE key = ?", ("last_scan_root",)).fetchone()
        conn.close()
        root = row["value"] if row else None

    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "tool": "sfxworkbench",
        "tool_version": __version__,
        "db_path": str(db_path) if db_path is not None else None,
        "root": root,
        "safe_folders": list(rules.safe_folders),
        "preservation_priority": rules.model(),
        "groups": [],
    }
    for group in groups:
        entries = []
        ordered_files = sorted(group.files, key=lambda file_path: priority_key(Path(file_path), rules))
        keep_path = ordered_files[0] if ordered_files else None
        keep_protected_by = protected_by(Path(keep_path), rules) if keep_path is not None else None
        keep_evidence = evidence(Path(keep_path), rules) if keep_path is not None else []
        for i, f in enumerate(ordered_files):
            file_path = Path(f)
            protected_match = protected_by(file_path, rules)
            action = "keep" if i == 0 else ("ignore" if protected_match is not None else "remove")
            reason = None
            if action == "ignore":
                reason = f"file is inside safe folder: {protected_match}"
            entries.append(
                {
                    "path": f,
                    "action": action,
                    "hash": group.hash,
                    "size_bytes": group.size_bytes,
                    **({"reason": reason} if reason is not None else {}),
                    **({"protected_by": protected_match} if protected_match is not None else {}),
                    **({"keep_protected_by": keep_protected_by} if keep_protected_by is not None else {}),
                    **({"preservation_evidence": evidence(file_path, rules)} if evidence(file_path, rules) else {}),
                    **({"keep_preservation_evidence": keep_evidence} if keep_evidence else {}),
                }
            )
        plan["groups"].append(entries)

    plan_path.write_text(json.dumps(plan, indent=2))
    if not quiet:
        console.print(f"Dedupe plan written to [cyan]{plan_path}[/cyan]")
        console.print("[yellow]Review the plan, then run with --apply to quarantine duplicate removals.[/yellow]")


def review_dedupe_plan(
    plan_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    groups: list[int] | None = None,
    quiet: bool = False,
) -> DedupeReviewResult:
    """Stamp a dedupe plan with approved group indexes.

    Group numbers are 1-based to match the preview table. The stored review
    metadata is 0-based so it remains stable for list indexing.
    """
    plan = json.loads(plan_path.read_text())
    approved_groups, invalid, total = mark_groups_approved(
        plan,
        requested_1based=groups,
        approve_all=approve_all,
        items_key="groups",
        approved_key="approved_groups",
    )

    output = output_path or plan_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2))
    result = DedupeReviewResult(
        plan_path=str(plan_path),
        output_path=str(output),
        total_groups=total,
        approved_groups=len(approved_groups),
        invalid_groups=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_groups:,}[/yellow] of "
            f"[yellow]{result.total_groups:,}[/yellow] group(s) in [cyan]{output}[/cyan]"
        )
        if invalid:
            console.print(f"[red]Ignored invalid group number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def apply_dedupe_plan(
    plan_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quarantine_dir: Path | None = None,
    permanent_delete: bool = False,
    require_reviewed: bool = False,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    log_path: Path | None = None,
    target_paths: tuple[str, ...] | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> DedupeApplyResult:
    """Execute a reviewed dedupe plan.

    On apply (`dry_run=False`), files are moved into quarantine by default and
    removed from the SQLite index. Use permanent_delete=True only for an
    explicitly reviewed purge.

    ``progress_callback`` fires every 50 remove-entries so the TUI status
    strip animates during a long quarantine. ``cancel_requested`` is polled
    every 50 entries — mid-stream cancellation preserves files already
    moved (filesystem move is itself atomic per file).
    """
    plan = json.loads(plan_path.read_text())
    result = DedupeApplyResult(dry_run=dry_run)
    affected_paths: list[str] = []
    log_entries: list[dict] = []
    # Tier 3.8: scope quarantine to selected files when the TUI passes them.
    # Only entries whose path is in the selection are touched.
    selection: frozenset[str] | None = frozenset(target_paths) if target_paths is not None else None
    from sfxworkbench.utils import progress_interval

    # Count up-front so progress reporting has a meaningful denominator.
    total_remove_entries = sum(
        1 for group in plan.get("groups", []) for entry in group if entry.get("action") == "remove"
    )
    processed_entries = 0
    report_every = min(progress_interval(total_remove_entries), _PROGRESS_MAX_INTERVAL)
    if progress_callback is not None:
        progress_callback(
            "applying",
            0,
            total_remove_entries,
            _dedupe_apply_progress_message(
                processed=0,
                total=total_remove_entries,
                removed=0,
                quarantined=0,
                skipped=0,
                errors=0,
                bytes_freed=0,
            ),
        )
    rules = build_preservation_rules(
        config_path=config_path,
        safe_folders=[Path(folder) for folder in plan.get("safe_folders", [])] + list(safe_folders or []),
    )
    plan_root = plan.get("root")
    quarantine_target_root = None
    if quarantine_dir is None and not dry_run and not permanent_delete:
        quarantine_dir = _default_quarantine_dir(plan_path, plan_root)
        quarantine_target_root = plan_root
    if quarantine_dir is not None:
        result.quarantine_dir = str(quarantine_dir)

    approved_groups = set(plan.get("review", {}).get("approved_groups", []))
    if require_reviewed and not approved_groups:
        result.errors.append({"path": str(plan_path), "error": "plan has no approved groups"})
        if not quiet:
            console.print("[red]Refusing to apply: plan has no approved groups.[/red]")
        return result

    cancelled = False
    for group_index, group in enumerate(plan["groups"]):
        if cancelled:
            break
        if require_reviewed and group_index not in approved_groups:
            result.errors.append({"path": str(plan_path), "error": f"group {group_index + 1} is not approved"})
            continue
        for entry in group:
            if entry["action"] != "remove":
                continue
            # Cancel polled every 50 entries (cheap, sub-second response).
            # Progress is emitted frequently; the TUI throttles redraws and
            # job-progress writes so six-figure plans stay responsive.
            if processed_entries > 0 and processed_entries % 50 == 0:
                if cancel_requested is not None and cancel_requested():
                    cancelled = True
                    break
            if progress_callback is not None and processed_entries > 0 and processed_entries % report_every == 0:
                progress_callback(
                    "applying",
                    processed_entries,
                    total_remove_entries,
                    _dedupe_apply_progress_message(
                        processed=processed_entries,
                        total=total_remove_entries,
                        removed=result.removed,
                        quarantined=result.quarantined,
                        skipped=result.skipped,
                        errors=len(result.errors),
                        bytes_freed=result.bytes_freed,
                        current=entry.get("path", ""),
                    ),
                )
            processed_entries += 1
            if selection is not None and entry["path"] not in selection:
                # Mirror the other Tier 3.8 executors: count selection-skipped
                # entries in ``result.skipped`` so the user can see how many
                # plan entries the scope filter dropped.
                result.skipped += 1
                continue
            p = Path(entry["path"])
            sz = entry.get("size_bytes", 0)
            expected_hash = entry.get("hash")
            protected_match = protected_by(p, rules)
            if protected_match is not None:
                result.errors.append(
                    {
                        "path": str(p),
                        "safe_folder": protected_match,
                        "error": "file is protected by safe folder",
                    }
                )
                if not quiet:
                    console.print(f"[red]Refusing protected file:[/red] {p}")
                continue
            validation_error = _validate_remove_candidate(p, sz, expected_hash)
            if validation_error is not None:
                result.errors.append({"path": str(p), "error": validation_error})
                if not quiet:
                    console.print(f"[red]Error validating {p}: {validation_error}[/red]")
                continue
            if dry_run:
                if not quiet:
                    console.print(f"[dim]Would quarantine: {p}[/dim]")
                result.removed += 1
                result.bytes_freed += sz
            elif permanent_delete:
                try:
                    p.unlink()
                    affected_paths.append(entry["path"])
                    result.removed += 1
                    result.bytes_freed += sz
                    if not quiet:
                        console.print(f"[green]Deleted:[/green] {p}")
                except OSError as e:
                    result.errors.append({"path": str(p), "error": str(e)})
                    if not quiet:
                        console.print(f"[red]Error deleting {p}: {e}[/red]")
            else:
                try:
                    assert quarantine_dir is not None
                    target = _quarantine_target(p.resolve(), quarantine_dir, quarantine_target_root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(p), str(target))
                    affected_paths.append(entry["path"])
                    log_entries.append(
                        {
                            "path": str(p),
                            "quarantine_path": str(target),
                            "size_bytes": sz,
                            "md5": expected_hash,
                            "source_plan": str(plan_path),
                            "group_index": group_index,
                        }
                    )
                    result.removed += 1
                    result.quarantined += 1
                    result.bytes_freed += sz
                    if not quiet:
                        console.print(f"[green]Quarantined:[/green] {p} -> {target}")
                except OSError as e:
                    result.errors.append({"path": str(p), "error": str(e)})
                    if not quiet:
                        console.print(f"[red]Error quarantining {p}: {e}[/red]")

    # Clean up the index after a real apply so it doesn't reference dead paths.
    if not dry_run and affected_paths and db_path is not None:
        if progress_callback is not None:
            progress_callback(
                "updating_index",
                0,
                None,
                _dedupe_finalizing_message(affected_paths=len(affected_paths)),
            )
        conn = get_connection(db_path)
        cursor = conn.executemany(
            "DELETE FROM files WHERE path = ?",
            [(path,) for path in affected_paths],
        )
        conn.commit()
        conn.close()
        removed_rows = cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else len(affected_paths)
        if progress_callback is not None:
            progress_callback(
                "updating_index",
                len(affected_paths),
                len(affected_paths),
                _dedupe_finalizing_message(affected_paths=len(affected_paths), removed_rows=removed_rows),
            )
        if not quiet:
            console.print(f"Removed [cyan]{len(affected_paths):,}[/cyan] row(s) from index.")

    result.cancelled = cancelled
    if not dry_run and log_entries:
        if log_path is None:
            log_path = _default_dedupe_log_path(plan_path)
        result.log_path = str(log_path)
        if progress_callback is not None:
            progress_callback("writing_log", 0, None, f"Writing dedupe quarantine log to {log_path.name}")
        write_apply_log(
            log_path,
            plan_path=plan_path,
            tool_version=__version__,
            result=result,
            extra={
                "quarantine_dir": str(quarantine_dir) if quarantine_dir is not None else None,
                "entries": log_entries,
            },
        )
        if not quiet:
            console.print(f"Dedupe quarantine log written to [cyan]{log_path}[/cyan]")

    if progress_callback is not None:
        progress_callback(
            "cancelled" if cancelled else "complete",
            processed_entries,
            total_remove_entries,
            _dedupe_apply_progress_message(
                processed=processed_entries,
                total=total_remove_entries,
                removed=result.removed,
                quarantined=result.quarantined,
                skipped=result.skipped,
                errors=len(result.errors),
                bytes_freed=result.bytes_freed,
            ),
        )

    if not quiet:
        action = "Would quarantine" if dry_run else ("Deleted" if permanent_delete else "Quarantined")
        console.print(
            f"\n{action} [yellow]{result.removed:,}[/yellow] file(s), "
            f"freeing [yellow]{fmt_bytes(result.bytes_freed)}[/yellow]"
        )
        if result.errors:
            console.print(f"[red]{len(result.errors)} error(s)[/red]")

    return result


def _validate_remove_candidate(path: Path, expected_size: int | None, expected_hash: str | None) -> str | None:
    if not path.exists():
        return "file does not exist"
    if not path.is_file():
        return "path is not a file"
    if expected_size is not None:
        try:
            actual_size = path.stat().st_size
        except OSError as e:
            return str(e)
        if actual_size != expected_size:
            return f"size changed: expected {fmt_bytes(expected_size)}, got {fmt_bytes(actual_size)}"
    if expected_hash and len(expected_hash) == 32:
        try:
            actual_hash = _md5(path)
        except OSError as e:
            return str(e)
        if actual_hash != expected_hash:
            return "md5 changed"
    return None


def show_duplicates(groups: list[DedupeGroup], quiet: bool = False) -> None:
    """Display duplicate groups in a Rich table."""
    if quiet:
        return
    if not groups:
        console.print("[green]No duplicates found.[/green]")
        return

    summary = summarize_duplicates(groups)

    console.print(
        f"\nFound [yellow]{summary.duplicate_groups}[/yellow] duplicate group(s), "
        f"[yellow]{summary.extra_copies:,}[/yellow] extra copies, "
        f"[yellow]{fmt_bytes(summary.wasted_bytes)}[/yellow] wasted.\n"
    )

    table = Table(title="Duplicate Groups (top 25)", show_lines=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Hash", style="cyan", no_wrap=True)
    table.add_column("Size", style="yellow", justify="right")
    table.add_column("Copies", justify="right")
    table.add_column("Files", style="white")

    for i, group in enumerate(groups[:25], 1):
        files_str = "\n".join(group.files)
        table.add_row(
            str(i),
            group.hash[:12] + "...",
            fmt_bytes(group.size_bytes),
            str(len(group.files)),
            files_str,
        )

    console.print(table)
    if len(groups) > 25:
        console.print(f"[dim]...{len(groups) - 25} more groups in plan file.[/dim]")
