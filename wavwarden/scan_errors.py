"""Review and quarantine scan-error files."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import get_connection
from wavwarden.models import ScanErrorApplyResult, ScanErrorEntry, ScanErrorPlan
from wavwarden.utils import fmt_bytes

console = Console()


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _md5(path: Path, block: int = 65536) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def _read_prefix(path: Path, size: int = 16) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(size)
    except OSError:
        return b""


def _is_all_zero(path: Path, block: int = 1024 * 1024) -> bool:
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block):
                if chunk.strip(b"\x00"):
                    return False
    except OSError:
        return False
    return True


def classify_scan_error(path: Path, scan_error: str) -> str:
    prefix = _read_prefix(path)
    if prefix.startswith(b"\x00\x05\x16\x07"):
        return "appledouble"
    if prefix and set(prefix) == {0} and _is_all_zero(path):
        return "all_zero"
    if "No 'data' chunk marker" in scan_error:
        return "riff_missing_data"
    if "Malformed 'fmt ' chunk" in scan_error:
        return "riff_malformed_fmt"
    if prefix.startswith(b"RIFF"):
        return "riff_unrecognized"
    if "Format not recognised" in scan_error:
        return "unknown_data"
    return "unknown"


def default_action_for_classification(classification: str) -> str:
    if classification in {"all_zero", "appledouble"}:
        return "quarantine"
    return "review"


def build_scan_error_plan(db_path: Path) -> ScanErrorPlan:
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT path, size_bytes, md5, scan_error
        FROM files
        WHERE scan_error IS NOT NULL
        ORDER BY path
        """
    ).fetchall()
    conn.close()

    entries: list[ScanErrorEntry] = []
    for row in rows:
        path = Path(row["path"])
        scan_error = row["scan_error"] or ""
        classification = classify_scan_error(path, scan_error)
        entries.append(
            ScanErrorEntry(
                path=str(path),
                action=default_action_for_classification(classification),
                classification=classification,
                scan_error=scan_error,
                size_bytes=row["size_bytes"],
                hash=row["md5"],
            )
        )
    return ScanErrorPlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        db_path=str(db_path),
        entries=entries,
    )


def write_scan_error_plan(plan: ScanErrorPlan, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan.model_dump(), indent=2))
    if not quiet:
        review_count = sum(1 for entry in plan.entries if entry.action == "review")
        quarantine_count = sum(1 for entry in plan.entries if entry.action == "quarantine")
        console.print(
            f"Scan-error plan written to [cyan]{output_path}[/cyan] "
            f"([yellow]{quarantine_count}[/yellow] quarantine, [yellow]{review_count}[/yellow] review)."
        )


def show_scan_error_plan(plan: ScanErrorPlan, quiet: bool = False) -> None:
    if quiet:
        return
    table = Table(title=f"Scan errors ({len(plan.entries)} files)", show_lines=False)
    table.add_column("Action", style="cyan")
    table.add_column("Class", style="yellow")
    table.add_column("Size", justify="right")
    table.add_column("Path", style="white")
    for entry in plan.entries[:50]:
        table.add_row(entry.action, entry.classification, fmt_bytes(entry.size_bytes or 0), entry.path)
    console.print(table)
    if len(plan.entries) > 50:
        console.print(f"[dim]...{len(plan.entries) - 50} more scan-error file(s).[/dim]")


def _default_quarantine_dir(plan_path: Path) -> Path:
    return plan_path.parent / f"wavwarden_scan_error_quarantine_{_now_stamp()}"


def _quarantine_target(path: Path, quarantine_dir: Path) -> Path:
    parts = [part for part in path.resolve().parts if part not in (path.anchor, "/")]
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


def _validate_candidate(path: Path, expected_size: int | None, expected_hash: str | None) -> str | None:
    if not path.exists():
        return "file does not exist"
    if not path.is_file():
        return "path is not a file"
    if expected_size is not None:
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            return f"size changed: expected {expected_size}, got {actual_size}"
    if expected_hash and len(expected_hash) == 32:
        if _md5(path) != expected_hash:
            return "md5 changed"
    return None


def apply_scan_error_plan(
    plan_path: Path,
    db_path: Path | None = None,
    quarantine_dir: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> ScanErrorApplyResult:
    plan = ScanErrorPlan.model_validate(json.loads(plan_path.read_text()))
    if db_path is None:
        db_path = Path(plan.db_path)
    if quarantine_dir is None and not dry_run:
        quarantine_dir = _default_quarantine_dir(plan_path)

    result = ScanErrorApplyResult(
        planned=sum(1 for entry in plan.entries if entry.action == "quarantine"),
        quarantine_dir=str(quarantine_dir) if quarantine_dir is not None else None,
        dry_run=dry_run,
    )
    affected_paths: list[str] = []

    for entry in plan.entries:
        if entry.action != "quarantine":
            continue
        path = Path(entry.path)
        validation_error = _validate_candidate(path, entry.size_bytes, entry.hash)
        if validation_error is not None:
            result.errors.append({"path": str(path), "error": validation_error})
            continue
        if dry_run:
            result.quarantined += 1
            result.bytes_quarantined += entry.size_bytes or 0
            if not quiet:
                console.print(f"[dim]Would quarantine: {path}[/dim]")
            continue
        assert quarantine_dir is not None
        target = _quarantine_target(path, quarantine_dir)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            affected_paths.append(str(path))
            result.quarantined += 1
            result.bytes_quarantined += entry.size_bytes or 0
            if not quiet:
                console.print(f"[green]Quarantined:[/green] {path} -> {target}")
        except OSError as e:
            result.errors.append({"path": str(path), "target": str(target), "error": str(e)})

    if not dry_run and affected_paths and db_path is not None:
        conn = get_connection(db_path)
        conn.executemany("DELETE FROM files WHERE path = ?", [(path,) for path in affected_paths])
        conn.commit()
        conn.close()

    if not quiet:
        action = "Would quarantine" if dry_run else "Quarantined"
        console.print(
            f"\n{action} [yellow]{result.quarantined:,}[/yellow] scan-error file(s), "
            f"[yellow]{fmt_bytes(result.bytes_quarantined)}[/yellow]"
        )
        if result.errors:
            console.print(f"[red]{len(result.errors)} error(s)[/red]")
    return result
