"""sfx dedupe command — find and quarantine duplicate files."""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import get_connection
from wavwarden.models import DedupeApplyResult, DedupeGroup
from wavwarden.utils import fmt_bytes

console = Console()

PLAN_SCHEMA_VERSION = 1


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _md5(path: Path, block: int = 65536) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def _default_quarantine_dir(plan_path: Path) -> Path:
    return plan_path.parent / f"wavwarden_quarantine_{_now_stamp()}"


def _quarantine_target(path: Path, quarantine_dir: Path) -> Path:
    """Map an absolute source path into a quarantine tree without overwriting."""
    parts = [part for part in path.parts if part not in (path.anchor, "/")]
    target = quarantine_dir.joinpath(*parts)
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    i = 1
    while True:
        candidate = parent / f"{stem}__{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def find_duplicates(db_path: Path) -> list[DedupeGroup]:
    """Query the index for files grouped by MD5 where count > 1.

    Uses `json_group_array` so paths are returned as a proper JSON array — no
    fragile ad-hoc separator. Sorted within each group by path for
    deterministic ordering, so the same plan is generated on every run.
    """
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
    return groups


def write_dedupe_plan(
    groups: list[DedupeGroup],
    plan_path: Path,
    db_path: Path | None = None,
    quiet: bool = False,
) -> None:
    """Write JSON plan: for each group, mark all but the first as 'remove'."""
    root = None
    if db_path is not None:
        conn = get_connection(db_path)
        row = conn.execute("SELECT value FROM scan_meta WHERE key = ?", ("last_scan_root",)).fetchone()
        conn.close()
        root = row["value"] if row else None

    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "wavwarden",
        "tool_version": __version__,
        "db_path": str(db_path) if db_path is not None else None,
        "root": root,
        "groups": [],
    }
    for group in groups:
        entries = []
        for i, f in enumerate(group.files):
            entries.append(
                {
                    "path": f,
                    "action": "keep" if i == 0 else "remove",
                    "hash": group.hash,
                    "size_bytes": group.size_bytes,
                }
            )
        plan["groups"].append(entries)

    plan_path.write_text(json.dumps(plan, indent=2))
    if not quiet:
        console.print(f"Dedupe plan written to [cyan]{plan_path}[/cyan]")
        console.print("[yellow]Review the plan, then run with --apply to execute.[/yellow]")


def apply_dedupe_plan(
    plan_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quarantine_dir: Path | None = None,
    permanent_delete: bool = False,
    quiet: bool = False,
) -> DedupeApplyResult:
    """Execute a reviewed dedupe plan.

    On apply (`dry_run=False`), files are moved into quarantine by default and
    removed from the SQLite index. Use permanent_delete=True only for an
    explicitly reviewed purge.
    """
    plan = json.loads(plan_path.read_text())
    result = DedupeApplyResult(dry_run=dry_run)
    affected_paths: list[str] = []
    if quarantine_dir is None and not dry_run and not permanent_delete:
        quarantine_dir = _default_quarantine_dir(plan_path)
    if quarantine_dir is not None:
        result.quarantine_dir = str(quarantine_dir)

    for group in plan["groups"]:
        for entry in group:
            if entry["action"] != "remove":
                continue
            p = Path(entry["path"])
            sz = entry.get("size_bytes", 0)
            expected_hash = entry.get("hash")
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
                    target = _quarantine_target(p.resolve(), quarantine_dir)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(p), str(target))
                    affected_paths.append(entry["path"])
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
        conn = get_connection(db_path)
        conn.executemany(
            "DELETE FROM files WHERE path = ?",
            [(path,) for path in affected_paths],
        )
        conn.commit()
        conn.close()
        if not quiet:
            console.print(f"Removed [cyan]{len(affected_paths):,}[/cyan] row(s) from index.")

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
            return f"size changed: expected {expected_size}, got {actual_size}"
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

    total_extra = sum(len(g.files) - 1 for g in groups)
    total_wasted = sum(g.size_bytes * (len(g.files) - 1) for g in groups)

    console.print(
        f"\nFound [yellow]{len(groups)}[/yellow] duplicate group(s), "
        f"[yellow]{total_extra:,}[/yellow] extra copies, "
        f"[yellow]{fmt_bytes(total_wasted)}[/yellow] wasted.\n"
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
