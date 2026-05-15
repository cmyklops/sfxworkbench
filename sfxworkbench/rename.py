"""sfx rename command — reversible file and UCS-oriented renames."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import md5
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import health, junk
from sfxworkbench.apply_logs import default_apply_log_path
from sfxworkbench.db import get_connection, path_scope_filter, path_scope_params, scoped_relative_path
from sfxworkbench.models import RenameEntry, RenamePlan, RenameResult
from sfxworkbench.path_safety import (
    avoid_windows_reserved_component,
    existing_windows_collision,
    has_windows_trailing_dot_or_space,
    windows_collision_path_key,
    windows_reserved_basename,
)
from sfxworkbench.preservation import PreservationRules, build_preservation_rules, move_protected_by
from sfxworkbench.ucs import looks_ucs_casefold, normalize_stem

console = Console()
ProgressCallback = Callable[[str, int, int | None, str], None]

_BAD_CHARS_RE = re.compile(r"[:*?\"<>|#&;'\\!]+")
_SAFE_BAD_CHARS_RE = re.compile(r"[:*?\"<>|]+")
_PORTABLE_UNDERSCORE_CHARS_RE = re.compile(r"[:*?\"<>|;\\!]+")
_SEPARATOR_RE = re.compile(r"[\s\-]+")
_UNDERSCORE_RE = re.compile(r"_+")
_PORTABLE_MAX_PATH_BYTES = 240
_PROGRESS_MAX_INTERVAL = 100
_PORTABLE_TRANSLATION = str.maketrans(
    {
        "&": " and ",
        "#": "Sharp",
        "'": "",
        "\u2018": "",
        "\u2019": "",
        "\u201c": "",
        "\u201d": "",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2026": "...",
        "\u00d7": "x",
        "\u0421": "C",
        "\u0441": "c",
    }
)


def _rename_progress_message(
    *,
    processed: int,
    total: int,
    renamed: int,
    skipped: int,
    errors: int,
    current: str | None = None,
) -> str:
    message = f"Processed {processed:,}/{total:,}; renamed {renamed:,}, skipped {skipped:,}, errors {errors:,}"
    if current:
        return f"{message}; current {Path(current).name}"
    return message


def _rename_plan_walk_message(visited: int, candidates: int, current: Path | None = None) -> str:
    location = f"; now {current}" if current is not None else ""
    return f"Walked {visited:,} item(s); found {candidates:,} audio candidate(s){location}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _default_log_path() -> Path:
    return default_apply_log_path("rename_log")


def _sanitize_stem(stem: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    normalized = normalize_stem(stem)
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
    already_ucs = looks_ucs_casefold(path.stem)
    stem, fixes = _sanitize_stem(path.stem)
    suffix = path.suffix.lower()
    if already_ucs:
        return f"{stem}{suffix}", fixes
    fixes.append("ucs_prefix")
    return f"SFX_MISC_{stem}{suffix}", fixes


def _safe_component(name: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    normalized = normalize_stem(name)
    if normalized != name:
        fixes.append("unicode_normalization")
    cleaned = _SAFE_BAD_CHARS_RE.sub("_", normalized)
    if cleaned != normalized:
        fixes.append("illegal_chars")
    stripped = cleaned.strip()
    if stripped != cleaned:
        fixes.append("leading_trailing_space")
    cleaned = _UNDERSCORE_RE.sub("_", stripped)
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "UNTITLED"
        fixes.append("empty_name")
    return cleaned, fixes


def _portable_component(name: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    normalized = normalize_stem(name)
    if normalized != name:
        fixes.append("unicode_normalization")
    had_non_ascii = any(ord(char) > 127 for char in normalized)
    translated = normalized.translate(_PORTABLE_TRANSLATION)
    ascii_name = unicodedata.normalize("NFKD", translated).encode("ascii", "ignore").decode("ascii")
    if had_non_ascii and ascii_name != normalized:
        fixes.append("non_ascii")
    cleaned = _PORTABLE_UNDERSCORE_CHARS_RE.sub("_", ascii_name)
    if translated != normalized or cleaned != ascii_name or any(char in normalized for char in "#&;'\\!"):
        fixes.append("risky_or_illegal_chars")
    if has_windows_trailing_dot_or_space(cleaned):
        fixes.append("trailing_dot_or_space")
    stripped = cleaned.strip()
    if stripped != cleaned:
        fixes.append("leading_trailing_space")
    cleaned = _UNDERSCORE_RE.sub("_", stripped)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip("._ ")
    if windows_reserved_basename(cleaned) is not None:
        fixes.append("windows_reserved_name")
        cleaned, _reserved_changed = avoid_windows_reserved_component(cleaned)
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "UNTITLED"
        fixes.append("empty_name")
    return cleaned, sorted(set(fixes), key=fixes.index)


def _safe_paths_for_audio(path: Path, root: Path) -> list[tuple[Path, Path, list[str]]]:
    planned: list[tuple[Path, Path, list[str]]] = []
    for component_path in [path, *path.parents]:
        if component_path == root or root not in component_path.parents:
            break
        safe_name, fixes = _safe_component(component_path.name)
        if fixes:
            planned.append((component_path, component_path.with_name(safe_name), fixes))
    return planned


def _component_paths_for_audio(path: Path, root: Path, component_fn) -> list[tuple[Path, Path, list[str]]]:
    planned: list[tuple[Path, Path, list[str]]] = []
    for component_path in [path, *path.parents]:
        if component_path == root or root not in component_path.parents:
            break
        new_name, fixes = component_fn(component_path.name)
        if fixes:
            planned.append((component_path, component_path.with_name(new_name), fixes))
    return planned


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _shorten_path_component(
    path: Path, max_path_bytes: int = _PORTABLE_MAX_PATH_BYTES
) -> tuple[Path, list[str]] | None:
    path_bytes = len(str(path).encode("utf-8"))
    if path_bytes <= max_path_bytes:
        return None
    suffix = path.suffix if path.is_file() else ""
    stem = path.stem if path.is_file() else path.name
    marker = "_" + md5(path.name.encode("utf-8")).hexdigest()[:6]
    parent_bytes = len(str(path.parent).encode("utf-8")) + 1
    max_stem_bytes = max(
        1,
        max_path_bytes - parent_bytes - len(marker.encode("utf-8")) - len(suffix.encode("utf-8")),
    )
    shortened = _truncate_utf8(stem, max_stem_bytes).rstrip(" -_.")
    if not shortened:
        shortened = "SHORT"
    return path.with_name(f"{shortened}{marker}{suffix}"), ["path_too_long"]


def _protection_error(path: Path, rules: PreservationRules) -> dict | None:
    protected_match = move_protected_by(path, rules)
    if protected_match is None:
        return None
    return {"path": str(path), "error": "protected by safe folder", "safe_folder": protected_match}


def build_rename_plan(
    root: Path,
    pattern: str = "ucs",
    *,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> RenamePlan:
    """Build a dry-run rename plan for audio files under root."""
    if pattern not in {"ucs", "safe", "portable"}:
        raise ValueError("Only pattern='ucs', pattern='safe', and pattern='portable' are currently supported")

    root = root.resolve()
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    entries_by_path: dict[Path, RenameEntry] = {}
    errors: list[dict] = []
    planned_target_keys: set[str] = set()

    visited = 0
    audio_paths: list[Path] = []
    if progress_callback is not None:
        progress_callback("walking", 0, None, f"Walking {root} for rename candidates")
    for path in root.rglob("*"):
        visited += 1
        if not path.is_file():
            if progress_callback is not None and visited % 500 == 0:
                progress_callback("walking", visited, None, _rename_plan_walk_message(visited, len(audio_paths), path))
            continue
        if junk.is_inside_junk_dir(path) or junk.is_junk_file(path):
            continue
        if path.suffix.lower() not in junk.AUDIO_EXTENSIONS:
            continue
        audio_paths.append(path)
        if progress_callback is not None and visited % 500 == 0:
            progress_callback("walking", visited, None, _rename_plan_walk_message(visited, len(audio_paths), path))

    total_candidates = len(audio_paths)
    if progress_callback is not None:
        progress_callback(
            "planning",
            0,
            total_candidates,
            f"Planning {pattern} rename preview for {total_candidates:,} audio candidate(s)",
        )
    from sfxworkbench.utils import progress_interval

    report_every = min(progress_interval(total_candidates), _PROGRESS_MAX_INTERVAL)

    for index, path in enumerate(sorted(audio_paths), start=1):
        if pattern == "ucs":
            new_filename, fixes = _ucs_filename(path)
            candidates = [(path, path.with_name(new_filename), fixes)]
        elif pattern == "portable":
            candidates = _component_paths_for_audio(path, root, _portable_component)
            if not candidates:
                shortened = _shorten_path_component(path)
                if shortened is not None:
                    target, fixes = shortened
                    candidates = [(path, target, fixes)]
        else:
            candidates = _safe_paths_for_audio(path, root)

        for source, target, fixes in candidates:
            if source == target or source in entries_by_path:
                continue
            protection_error = _protection_error(source, rules)
            if protection_error is not None:
                errors.append(protection_error)
                continue
            existing_collision = existing_windows_collision(source, target)
            if existing_collision is not None:
                if existing_collision.name == target.name:
                    errors.append({"path": str(source), "target": str(target), "error": "target exists"})
                    continue
                errors.append(
                    {
                        "path": str(source),
                        "target": str(target),
                        "error": "target collides on Windows",
                        "conflict": str(existing_collision),
                    }
                )
                continue
            if target.exists():
                errors.append({"path": str(source), "target": str(target), "error": "target exists"})
                continue
            target_key = windows_collision_path_key(target)
            if target_key in planned_target_keys:
                errors.append({"path": str(source), "target": str(target), "error": "target planned more than once"})
                continue
            planned_target_keys.add(target_key)
            entries_by_path[source] = RenameEntry(
                old_path=str(source),
                new_path=str(target),
                old_filename=source.name,
                new_filename=target.name,
                issue_fixes=fixes,
            )
        if progress_callback is not None and (index % report_every == 0 or index == total_candidates):
            progress_callback(
                "planning",
                index,
                total_candidates,
                (
                    f"Planned {index:,}/{total_candidates:,}; "
                    f"renames {len(entries_by_path):,}, errors {len(errors):,}; current {path.name}"
                ),
            )

    return RenamePlan(
        generated_at=_now_iso(),
        root=str(root),
        pattern=pattern,
        entries=sorted(
            entries_by_path.values(), key=lambda entry: (len(Path(entry.old_path).parts), entry.old_path), reverse=True
        ),
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
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(plan.model_dump(), indent=2))


def _refresh_fn_issues(conn, file_id: int, path: Path, root: Path) -> None:
    conn.execute("DELETE FROM fn_issues WHERE file_id = ?", (file_id,))
    issues = health.check_path(path, root)
    if issues:
        conn.executemany(
            "INSERT INTO fn_issues (file_id, component, issue, detail) VALUES (?, ?, ?, ?)",
            [(file_id, i.component, i.issue, i.detail) for i in issues],
        )


def _update_file_row(conn, old: Path, new: Path, root: Path) -> None:
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
        _refresh_fn_issues(conn, row["id"], new, root)


def _update_directory_rows(conn, old: Path, new: Path, root: Path) -> None:
    rows = conn.execute(
        f"SELECT id, path FROM files WHERE {path_scope_filter()}",
        path_scope_params(old),
    ).fetchall()
    updates: list[tuple[str, str, str, str, int]] = []
    refreshed: list[tuple[int, Path]] = []
    for row in rows:
        relative = scoped_relative_path(row["path"], old)
        if relative is None:
            continue
        new_file = new.joinpath(*Path(relative).parts)
        updates.append((str(new_file), new_file.name, new_file.stem, new_file.suffix.lower(), row["id"]))
        refreshed.append((row["id"], new_file))
    conn.executemany(
        """
        UPDATE files
        SET path = ?, filename = ?, stem = ?, extension = ?
        WHERE id = ?
        """,
        updates,
    )
    for file_id, path in refreshed:
        _refresh_fn_issues(conn, file_id, path, root)


def _indexed_target_conflict(conn, old: Path, new: Path) -> str | None:
    rows = conn.execute("SELECT path FROM files").fetchall()
    new_key = windows_collision_path_key(new)
    old_key = windows_collision_path_key(old)
    for row in rows:
        row_key = windows_collision_path_key(row["path"])
        if old.is_dir():
            hits_new = row_key == new_key or row_key.startswith(new_key.rstrip("/") + "/")
            hits_old = row_key == old_key or row_key.startswith(old_key.rstrip("/") + "/")
        else:
            hits_new = row_key == new_key
            hits_old = row_key == old_key
        if hits_new and not hits_old:
            return row["path"]
    return None


def apply_rename_plan(
    plan: RenamePlan,
    db_path: Path | None = None,
    log_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
    allow_partial: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    target_paths: tuple[str, ...] | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> RenameResult:
    """Apply a rename plan, refusing collisions and writing an undo log.

    ``target_paths`` (Tier 3.8): if given, only entries whose ``old_path``
    is in this set are renamed. Filtered entries count toward ``skipped``
    so ``planned`` continues to reflect the original plan size — matches
    the convention used by ``apply_delete_plan``, ``apply_tag_plan``, etc.
    """
    selection: frozenset[str] | None = frozenset(target_paths) if target_paths is not None else None
    result = RenameResult(planned=len(plan.entries), dry_run=dry_run)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    protected_entry_paths: set[str] = set()
    protection_errors = [
        error
        for entry in plan.entries
        if (selection is None or entry.old_path in selection)
        and (error := _protection_error(Path(entry.old_path), rules)) is not None
    ]
    if protection_errors:
        result.errors.extend(protection_errors)
        protected_entry_paths = {str(error["path"]) for error in protection_errors if "path" in error}
        if not allow_partial:
            if not quiet:
                console.print("[red]Refusing to apply rename plan with protected safe-folder paths.[/red]")
            return result
    if plan.errors:
        result.errors.extend(plan.errors)
        if not allow_partial:
            if not quiet:
                console.print("[red]Refusing to apply rename plan with unresolved errors.[/red]")
            return result
        if not quiet:
            console.print(
                "[yellow]Plan has unresolved errors; applying valid entries because --allow-partial was provided.[/yellow]"
            )
    if dry_run:
        if not quiet:
            show_rename_plan(plan)
        return result

    if log_path is None:
        log_path = _default_log_path()
    conn = get_connection(db_path) if db_path is not None else None
    applied: list[RenameEntry] = []
    root = Path(plan.root)

    from sfxworkbench.utils import progress_interval

    total_entries = len(plan.entries)
    report_every = min(progress_interval(total_entries), _PROGRESS_MAX_INTERVAL)
    if progress_callback is not None:
        progress_callback(
            "renaming",
            0,
            total_entries,
            _rename_progress_message(
                processed=0,
                total=total_entries,
                renamed=0,
                skipped=0,
                errors=0,
            ),
        )
    cancelled = False
    for entry_index, entry in enumerate(plan.entries):
        if entry_index > 0 and entry_index % 50 == 0:
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                break
        if progress_callback is not None and entry_index > 0 and entry_index % report_every == 0:
            progress_callback(
                "renaming",
                entry_index,
                total_entries,
                _rename_progress_message(
                    processed=entry_index,
                    total=total_entries,
                    renamed=result.renamed,
                    skipped=result.skipped,
                    errors=len(result.errors),
                    current=entry.old_path,
                ),
            )
        if selection is not None and entry.old_path not in selection:
            result.skipped += 1
            continue
        if entry.old_path in protected_entry_paths:
            continue
        old = Path(entry.old_path)
        new = Path(entry.new_path)
        created_parent = False
        if not old.exists():
            result.errors.append({"path": str(old), "error": "source missing"})
            continue
        if new.exists():
            result.errors.append({"path": str(old), "target": str(new), "error": "target exists"})
            continue
        if conn is not None and (conflict := _indexed_target_conflict(conn, old, new)) is not None:
            result.errors.append(
                {
                    "path": str(old),
                    "target": str(new),
                    "indexed_path": conflict,
                    "error": "target already exists in index",
                }
            )
            continue
        try:
            if "create_parent_folder" in entry.issue_fixes and not new.parent.exists():
                new.parent.mkdir(parents=True)
                created_parent = True
            old.rename(new)
            applied.append(entry)
            result.renamed += 1
            if conn is not None:
                if new.is_dir():
                    _update_directory_rows(conn, old, new, root)
                else:
                    _update_file_row(conn, old, new, root)
            if not quiet:
                console.print(f"[green]Renamed:[/green] {old} -> {new}")
        except OSError as e:
            result.errors.append({"path": str(old), "target": str(new), "error": str(e)})
            if created_parent:
                try:
                    new.parent.rmdir()
                except OSError:
                    pass

    if conn is not None:
        if progress_callback is not None:
            progress_callback("updating_index", result.renamed, total_entries, "Committing rename index updates")
        conn.commit()
        conn.close()

    result.cancelled = cancelled
    log_plan = plan.model_copy(update={"entries": applied})
    if progress_callback is not None:
        progress_callback("writing_log", 0, None, f"Writing rename undo log to {log_path.name}")
    write_rename_log(log_plan, log_path)
    result.log_path = str(log_path)
    if progress_callback is not None:
        processed_entries = result.renamed + result.skipped + len(result.errors)
        completed_entries = min(processed_entries, total_entries) if cancelled else total_entries
        progress_callback(
            "cancelled" if cancelled else "complete",
            completed_entries,
            total_entries,
            _rename_progress_message(
                processed=completed_entries,
                total=total_entries,
                renamed=result.renamed,
                skipped=result.skipped,
                errors=len(result.errors),
            ),
        )
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
    root = Path(plan.root)

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
                if old.is_dir():
                    _update_directory_rows(conn, new, old, root)
                else:
                    _update_file_row(conn, new, old, root)
            if "create_parent_folder" in entry.issue_fixes:
                try:
                    new.parent.rmdir()
                except OSError:
                    pass
            if not quiet:
                console.print(f"[green]Restored:[/green] {new} -> {old}")
        except OSError as e:
            result.errors.append({"path": str(new), "target": str(old), "error": str(e)})

    if conn is not None:
        conn.commit()
        conn.close()
    return result
