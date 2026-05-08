"""sfx rename command — reversible UCS-oriented file renames."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import health, junk
from wavwarden.db import get_connection
from wavwarden.models import RenameEntry, RenamePlan, RenameResult

console = Console()

_UCS_RE = re.compile(r"^[A-Z]{2,5}_[A-Z]{2,8}(_|$)")
_BAD_CHARS_RE = re.compile(r"[:*?\"<>|#&;'\\!]+")
_SEPARATOR_RE = re.compile(r"[\s\-]+")
_UNDERSCORE_RE = re.compile(r"_+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_log_path() -> Path:
    return Path(f"rename_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


def _sanitize_stem(stem: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    normalized = unicodedata.normalize("NFC", stem)
    if normalized != stem:
        fixes.append("unicode_normalization")
    cleaned = _BAD_CHARS_RE.sub("_", normalized)
    if cleaned != normalized:
        fixes.append("illegal_or_risky_chars")
    cleaned = _SEPARATOR_RE.sub("_", cleaned)
    cleaned = _UNDERSCORE_RE.sub("_", cleaned).strip("._ ")
    cleaned = cleaned.upper()
    if not cleaned:
        cleaned = "UNTITLED"
        fixes.append("empty_name")
    return cleaned, fixes


def _ucs_filename(path: Path) -> tuple[str, list[str]]:
    already_ucs = bool(_UCS_RE.match(unicodedata.normalize("NFC", path.stem).upper()))
    stem, fixes = _sanitize_stem(path.stem)
    suffix = path.suffix.lower()
    if already_ucs:
        return f"{stem}{suffix}", fixes
    fixes.append("ucs_prefix")
    return f"SFX_MISC_{stem}{suffix}", fixes


def build_rename_plan(root: Path, pattern: str = "ucs") -> RenamePlan:
    """Build a dry-run rename plan for audio files under root."""
    if pattern != "ucs":
        raise ValueError("Only pattern='ucs' is currently supported")

    root = root.resolve()
    entries: list[RenameEntry] = []
    errors: list[dict] = []
    planned_targets: set[Path] = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if junk.is_inside_junk_dir(path) or junk.is_junk_file(path):
            continue
        if path.suffix.lower() not in junk.AUDIO_EXTENSIONS:
            continue

        new_filename, fixes = _ucs_filename(path)
        target = path.with_name(new_filename)
        if target == path:
            continue
        if target.exists():
            errors.append({"path": str(path), "target": str(target), "error": "target exists"})
            continue
        if target in planned_targets:
            errors.append({"path": str(path), "target": str(target), "error": "target planned more than once"})
            continue
        planned_targets.add(target)
        entries.append(
            RenameEntry(
                old_path=str(path),
                new_path=str(target),
                old_filename=path.name,
                new_filename=new_filename,
                issue_fixes=fixes,
            )
        )

    return RenamePlan(
        generated_at=_now_iso(),
        root=str(root),
        pattern=pattern,
        entries=entries,
        errors=errors,
    )


def show_rename_plan(plan: RenamePlan) -> None:
    table = Table(title=f"Rename preview ({len(plan.entries)} planned)", show_lines=False)
    table.add_column("Old", style="white")
    table.add_column("New", style="cyan")
    table.add_column("Fixes", style="yellow")
    for entry in plan.entries[:50]:
        table.add_row(entry.old_filename, entry.new_filename, ", ".join(entry.issue_fixes))
    console.print(table)
    if len(plan.entries) > 50:
        console.print(f"[dim]...{len(plan.entries) - 50} more rename(s).[/dim]")
    if plan.errors:
        console.print(f"[red]{len(plan.errors)} collision/error(s); apply will be refused until resolved.[/red]")


def write_rename_log(plan: RenamePlan, log_path: Path) -> None:
    log_path.write_text(json.dumps(plan.model_dump(), indent=2))


def apply_rename_plan(
    plan: RenamePlan,
    db_path: Path | None = None,
    log_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> RenameResult:
    """Apply a rename plan, refusing collisions and writing an undo log."""
    result = RenameResult(planned=len(plan.entries), dry_run=dry_run)
    if plan.errors:
        result.errors.extend(plan.errors)
        if not quiet:
            console.print("[red]Refusing to apply rename plan with unresolved errors.[/red]")
        return result
    if dry_run:
        if not quiet:
            show_rename_plan(plan)
        return result

    if log_path is None:
        log_path = _default_log_path()
    conn = get_connection(db_path) if db_path is not None else None
    applied: list[RenameEntry] = []

    for entry in plan.entries:
        old = Path(entry.old_path)
        new = Path(entry.new_path)
        if not old.exists():
            result.errors.append({"path": str(old), "error": "source missing"})
            continue
        if new.exists():
            result.errors.append({"path": str(old), "target": str(new), "error": "target exists"})
            continue
        try:
            old.rename(new)
            applied.append(entry)
            result.renamed += 1
            if conn is not None:
                stat = new.stat()
                conn.execute(
                    """
                    UPDATE files
                    SET path = ?, filename = ?, stem = ?, extension = ?, size_bytes = ?, mtime = ?
                    WHERE path = ?
                    """,
                    (str(new), new.name, new.stem, new.suffix.lower(), stat.st_size, stat.st_mtime, str(old)),
                )
                row = conn.execute("SELECT id FROM files WHERE path = ?", (str(new),)).fetchone()
                if row is not None:
                    conn.execute("DELETE FROM fn_issues WHERE file_id = ?", (row["id"],))
                    issues = health.check_path(new, Path(plan.root))
                    if issues:
                        conn.executemany(
                            "INSERT INTO fn_issues (file_id, component, issue, detail) VALUES (?, ?, ?, ?)",
                            [(row["id"], i.component, i.issue, i.detail) for i in issues],
                        )
            if not quiet:
                console.print(f"[green]Renamed:[/green] {old} -> {new}")
        except OSError as e:
            result.errors.append({"path": str(old), "target": str(new), "error": str(e)})

    if conn is not None:
        conn.commit()
        conn.close()

    log_plan = plan.model_copy(update={"entries": applied})
    write_rename_log(log_plan, log_path)
    result.log_path = str(log_path)
    if not quiet:
        console.print(f"Rename log written to [cyan]{log_path}[/cyan]")
    return result


def undo_rename_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> RenameResult:
    """Undo a previously applied rename log."""
    plan = RenamePlan.model_validate(json.loads(log_path.read_text()))
    result = RenameResult(planned=len(plan.entries), dry_run=dry_run, log_path=str(log_path))
    conn = get_connection(db_path) if db_path is not None and not dry_run else None

    for entry in reversed(plan.entries):
        old = Path(entry.old_path)
        new = Path(entry.new_path)
        if not new.exists():
            result.errors.append({"path": str(new), "error": "renamed file missing"})
            continue
        if old.exists():
            result.errors.append({"path": str(new), "target": str(old), "error": "original path exists"})
            continue
        if dry_run:
            result.undone += 1
            if not quiet:
                console.print(f"[dim]Would undo: {new} -> {old}[/dim]")
            continue
        try:
            new.rename(old)
            result.undone += 1
            if conn is not None:
                stat = old.stat()
                conn.execute(
                    """
                    UPDATE files
                    SET path = ?, filename = ?, stem = ?, extension = ?, size_bytes = ?, mtime = ?
                    WHERE path = ?
                    """,
                    (str(old), old.name, old.stem, old.suffix.lower(), stat.st_size, stat.st_mtime, str(new)),
                )
            if not quiet:
                console.print(f"[green]Restored:[/green] {new} -> {old}")
        except OSError as e:
            result.errors.append({"path": str(new), "target": str(old), "error": str(e)})

    if conn is not None:
        conn.commit()
        conn.close()
    return result
