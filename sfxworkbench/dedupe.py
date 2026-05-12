"""sfx dedupe command — find and quarantine duplicate files."""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.apply_logs import default_apply_log_path_for_plan
from sfxworkbench.db import get_connection
from sfxworkbench.models import DedupeApplyResult, DedupeGroup, DedupeReviewResult, DedupeSummary
from sfxworkbench.preservation import build_preservation_rules, evidence, priority_key, protected_by
from sfxworkbench.utils import fmt_bytes

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
    return plan_path.parent / f"sfxworkbench_quarantine_{_now_stamp()}"


def _default_dedupe_log_path(plan_path: Path) -> Path:
    return default_apply_log_path_for_plan(plan_path, "dedupe_quarantine_log")


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
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
    total = len(plan.get("groups", []))
    requested = set(groups or [])
    invalid = sorted(group for group in requested if group < 1 or group > total)
    if approve_all:
        approved = set(range(total))
    else:
        approved = {group - 1 for group in requested if 1 <= group <= total}

    existing_review = plan.get("review", {})
    existing_approved = set(existing_review.get("approved_groups", []))
    approved.update(existing_approved)
    approved_groups = sorted(approved)

    plan["review"] = {
        "status": "approved" if len(approved_groups) == total and total else "partially_approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_groups": approved_groups,
    }

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
) -> DedupeApplyResult:
    """Execute a reviewed dedupe plan.

    On apply (`dry_run=False`), files are moved into quarantine by default and
    removed from the SQLite index. Use permanent_delete=True only for an
    explicitly reviewed purge.
    """
    plan = json.loads(plan_path.read_text())
    result = DedupeApplyResult(dry_run=dry_run)
    affected_paths: list[str] = []
    log_entries: list[dict] = []
    rules = build_preservation_rules(
        config_path=config_path,
        safe_folders=[Path(folder) for folder in plan.get("safe_folders", [])] + list(safe_folders or []),
    )
    if quarantine_dir is None and not dry_run and not permanent_delete:
        quarantine_dir = _default_quarantine_dir(plan_path)
    if quarantine_dir is not None:
        result.quarantine_dir = str(quarantine_dir)

    approved_groups = set(plan.get("review", {}).get("approved_groups", []))
    if require_reviewed and not approved_groups:
        result.errors.append({"path": str(plan_path), "error": "plan has no approved groups"})
        if not quiet:
            console.print("[red]Refusing to apply: plan has no approved groups.[/red]")
        return result

    for group_index, group in enumerate(plan["groups"]):
        if require_reviewed and group_index not in approved_groups:
            result.errors.append({"path": str(plan_path), "error": f"group {group_index + 1} is not approved"})
            continue
        for entry in group:
            if entry["action"] != "remove":
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
                    target = _quarantine_target(p.resolve(), quarantine_dir)
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
        conn = get_connection(db_path)
        conn.executemany(
            "DELETE FROM files WHERE path = ?",
            [(path,) for path in affected_paths],
        )
        conn.commit()
        conn.close()
        if not quiet:
            console.print(f"Removed [cyan]{len(affected_paths):,}[/cyan] row(s) from index.")

    if not dry_run and log_entries:
        if log_path is None:
            log_path = _default_dedupe_log_path(plan_path)
        result.log_path = str(log_path)
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tool": "sfxworkbench",
            "tool_version": __version__,
            "plan_path": str(plan_path),
            "quarantine_dir": str(quarantine_dir) if quarantine_dir is not None else None,
            "entries": log_entries,
            "result": result.model_dump(),
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(payload, indent=2))
        if not quiet:
            console.print(f"Dedupe quarantine log written to [cyan]{log_path}[/cyan]")

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
