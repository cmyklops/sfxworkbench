"""sfx dedupe command — find and remove duplicate files."""

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden.db import get_connection
from wavwarden.models import DedupeGroup

console = Console()


def find_duplicates(db_path: Path) -> list[DedupeGroup]:
    """Query DB for files grouped by MD5 where count > 1."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT md5, size_bytes, GROUP_CONCAT(path, '|||') AS paths, COUNT(*) as cnt
        FROM files
        WHERE md5 IS NOT NULL
        GROUP BY md5
        HAVING cnt > 1
        ORDER BY size_bytes DESC
        """
    ).fetchall()
    conn.close()

    groups: list[DedupeGroup] = []
    for row in rows:
        files = row["paths"].split("|||")
        groups.append(DedupeGroup(
            hash=row["md5"],
            size_bytes=row["size_bytes"],
            files=files,
        ))
    return groups


def write_dedupe_plan(groups: list[DedupeGroup], plan_path: Path) -> None:
    """Write JSON plan: for each group, mark all but the first as 'remove'."""
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "groups": [],
    }
    for group in groups:
        entries = []
        for i, f in enumerate(group.files):
            entries.append({
                "path": f,
                "action": "keep" if i == 0 else "remove",
                "hash": group.hash,
                "size_bytes": group.size_bytes,
            })
        plan["groups"].append(entries)

    plan_path.write_text(json.dumps(plan, indent=2))
    console.print(f"Dedupe plan written to [cyan]{plan_path}[/cyan]")
    console.print("[yellow]Review the plan, then run with --apply to execute.[/yellow]")


def apply_dedupe_plan(plan_path: Path, dry_run: bool = True) -> dict:
    """Execute a reviewed dedupe plan. dry_run=True by default."""
    plan = json.loads(plan_path.read_text())
    result = {"removed": 0, "bytes_freed": 0, "errors": [], "dry_run": dry_run}

    for group in plan["groups"]:
        for entry in group:
            if entry["action"] != "remove":
                continue
            p = Path(entry["path"])
            sz = entry.get("size_bytes", 0)
            if dry_run:
                console.print(f"[dim]Would remove: {p}[/dim]")
                result["removed"] += 1
                result["bytes_freed"] += sz
            else:
                try:
                    p.unlink()
                    result["removed"] += 1
                    result["bytes_freed"] += sz
                    console.print(f"[green]Removed:[/green] {p}")
                except OSError as e:
                    result["errors"].append({"path": str(p), "error": str(e)})
                    console.print(f"[red]Error removing {p}: {e}[/red]")

    action = "Would remove" if dry_run else "Removed"
    console.print(
        f"\n{action} [yellow]{result['removed']:,}[/yellow] file(s), "
        f"freeing [yellow]{_fmt_bytes(result['bytes_freed'])}[/yellow]"
    )
    if result["errors"]:
        console.print(f"[red]{len(result['errors'])} error(s)[/red]")

    return result


def show_duplicates(groups: list[DedupeGroup]) -> None:
    """Display duplicate groups in a Rich table."""
    if not groups:
        console.print("[green]No duplicates found.[/green]")
        return

    total_extra = sum(len(g.files) - 1 for g in groups)
    total_wasted = sum(g.size_bytes * (len(g.files) - 1) for g in groups)

    console.print(
        f"\nFound [yellow]{len(groups)}[/yellow] duplicate group(s), "
        f"[yellow]{total_extra:,}[/yellow] extra copies, "
        f"[yellow]{_fmt_bytes(total_wasted)}[/yellow] wasted.\n"
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
            _fmt_bytes(group.size_bytes),
            str(len(group.files)),
            files_str,
        )

    console.print(table)
    if len(groups) > 25:
        console.print(f"[dim]...{len(groups) - 25} more groups in plan file.[/dim]")


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
