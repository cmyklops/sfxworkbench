"""Reviewed permanent deletion from quarantine logs only."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.apply_logs import apply_session, mark_entries_reviewed
from sfxworkbench.db import get_connection, path_scope_filter, path_scope_params
from sfxworkbench.models import DeleteApplyResult, DeletePlan, DeletePlanEntry, DeletePlanSummary, DeleteReviewResult
from sfxworkbench.preservation import build_preservation_rules, protected_by
from sfxworkbench.utils import atomic_write_json

console = Console()
_VALID_REVIEW_STATES = {"approved", "rejected", "pending"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _md5(path: Path, block: int = 65536) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.md5()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(block):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _path_size_and_files(path: Path) -> tuple[int, int]:
    """Return ``(total_bytes, file_count)`` for *path*.

    A file entry counts as 1 file; a directory entry recursively counts its
    descendant files so the plan can report the real number of items the user
    will permanently delete (not just the number of top-level quarantine
    bundles).
    """
    if path.is_file():
        return path.stat().st_size, 1
    total_bytes = 0
    file_count = 0
    for child in path.rglob("*"):
        if child.is_file():
            total_bytes += child.stat().st_size
            file_count += 1
    return total_bytes, file_count


def _path_size(path: Path) -> int:
    """Back-compat wrapper around :func:`_path_size_and_files` for staleness checks."""
    return _path_size_and_files(path)[0]


def _extract_quarantine_paths(raw: dict, source_log: Path) -> tuple[list[DeletePlanEntry], list[dict]]:
    entries: list[DeletePlanEntry] = []
    errors: list[dict] = []
    next_id = 1
    for item in raw.get("entries", []):
        quarantine_path = item.get("quarantine_path")
        if not quarantine_path:
            continue
        path = Path(quarantine_path)
        if not path.exists():
            errors.append({"path": str(path), "error": "quarantine path does not exist"})
            continue
        size_bytes, file_count = _path_size_and_files(path)
        entries.append(
            DeletePlanEntry(
                entry_id=next_id,
                path=str(path),
                path_type="dir" if path.is_dir() else "file",
                size_bytes=size_bytes,
                file_count=file_count,
                md5=_md5(path),
                source_log=str(source_log),
                source_path=item.get("folder_path") or item.get("path"),
            )
        )
        next_id += 1
    return entries, errors


def _summarize(plan: DeletePlan) -> DeletePlanSummary:
    return DeletePlanSummary(
        candidate_entries=len(plan.entries),
        file_entries=sum(1 for entry in plan.entries if entry.path_type == "file"),
        directory_entries=sum(1 for entry in plan.entries if entry.path_type == "dir"),
        files_planned=sum(entry.file_count for entry in plan.entries),
        approved_entries=sum(1 for entry in plan.entries if entry.review_status == "approved"),
        rejected_entries=sum(1 for entry in plan.entries if entry.review_status == "rejected"),
        bytes_planned=sum(entry.size_bytes or 0 for entry in plan.entries),
    )


def build_delete_plan(
    source_log: Path,
    *,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
) -> DeletePlan:
    """Build a permanent-delete plan from an existing quarantine log."""
    raw = json.loads(source_log.read_text())
    entries, errors = _extract_quarantine_paths(raw, source_log)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    filtered: list[DeletePlanEntry] = []
    for entry in entries:
        protected_match = protected_by(Path(entry.path), rules)
        if protected_match is not None:
            errors.append({"path": entry.path, "safe_folder": protected_match, "error": "protected by safe folder"})
            continue
        filtered.append(entry)
    plan = DeletePlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        source_log=str(source_log),
        safe_folders=list(rules.safe_folders),
        summary=DeletePlanSummary(candidate_entries=len(filtered)),
        entries=filtered,
        errors=errors,
    )
    plan.summary = _summarize(plan)
    return plan


def write_delete_plan(plan: DeletePlan, output_path: Path, quiet: bool = False) -> None:
    atomic_write_json(output_path, plan)
    if not quiet:
        console.print(f"Delete plan written to [cyan]{output_path}[/cyan]")


def load_delete_plan(plan_path: Path) -> DeletePlan:
    return DeletePlan.model_validate_json(plan_path.read_text())


def review_delete_plan(
    plan_path: Path,
    *,
    output_path: Path | None = None,
    approve_all: bool = False,
    entries: list[int] | None = None,
    reject_entries: list[int] | None = None,
    quiet: bool = False,
) -> DeleteReviewResult:
    plan = load_delete_plan(plan_path)
    by_id = {entry.entry_id: entry for entry in plan.entries}
    invalid = mark_entries_reviewed(by_id, approve=entries, reject=reject_entries, approve_all=approve_all)
    plan.summary = _summarize(plan)
    output = output_path or plan_path
    atomic_write_json(output, plan)
    result = DeleteReviewResult(
        plan_path=str(plan_path),
        output_path=str(output),
        total_entries=len(plan.entries),
        approved_entries=plan.summary.approved_entries,
        rejected_entries=plan.summary.rejected_entries,
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(f"Approved [yellow]{result.approved_entries:,}[/yellow] delete entrie(s).")
    return result


def _validate_entry(entry: DeletePlanEntry) -> str | None:
    path = Path(entry.path)
    if not path.exists():
        return "path does not exist"
    if entry.path_type == "file" and not path.is_file():
        return "path is not a file"
    if entry.path_type == "dir" and not path.is_dir():
        return "path is not a directory"
    if entry.size_bytes is not None and _path_size(path) != entry.size_bytes:
        return "size changed"
    if entry.md5 is not None and path.is_file() and _md5(path) != entry.md5:
        return "md5 changed"
    return None


def _drop_indexed_rows_under(db_path: Path, deleted_paths: list[Path]) -> int:
    """Remove rows from ``files`` whose ``path`` is *deleted_paths* or below.

    Pack quarantines update file rows to point at their new quarantine path
    instead of deleting them, so after a permanent delete those rows would
    otherwise linger and inflate ``SUM(size_bytes)``. Dedupe-quarantined rows
    are already gone; this is a no-op for those. The directory case uses
    ``path_scope_filter`` so descendant files are dropped along with the
    folder entry itself.
    """
    if not deleted_paths:
        return 0
    conn = get_connection(db_path)
    try:
        removed = 0
        for path in deleted_paths:
            cursor = conn.execute(
                f"DELETE FROM files WHERE {path_scope_filter()}",
                path_scope_params(path),
            )
            removed += cursor.rowcount or 0
        conn.commit()
    finally:
        conn.close()
    return removed


def apply_delete_plan(
    plan_path: Path,
    *,
    db_path: Path | None = None,
    dry_run: bool = True,
    require_reviewed: bool = False,
    understand_permanent_delete: bool = False,
    log_path: Path | None = None,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    quiet: bool = False,
    target_paths: tuple[str, ...] | None = None,
) -> DeleteApplyResult:
    """Apply approved delete plan entries.

    ``target_paths`` (Tier 3.8): if given, only entries whose ``path`` is in
    this set are deleted. Other entries are silently skipped.
    """
    plan = load_delete_plan(plan_path)
    result = DeleteApplyResult(planned=len(plan.entries), dry_run=dry_run)
    if not dry_run and not understand_permanent_delete:
        result.errors.append({"path": str(plan_path), "error": "missing explicit permanent-delete confirmation"})
        return result
    if require_reviewed and not any(entry.review_status == "approved" for entry in plan.entries):
        result.errors.append({"path": str(plan_path), "error": "plan has no approved entries"})
        return result
    selection: frozenset[str] | None = frozenset(target_paths) if target_paths is not None else None
    rules = build_preservation_rules(
        config_path=config_path,
        safe_folders=[Path(folder) for folder in plan.safe_folders] + list(safe_folders or []),
    )
    deleted_entries: list[dict] = []
    deleted_paths: list[Path] = []
    with apply_session(
        plan_path=plan_path,
        dry_run=dry_run,
        log_path=log_path,
        log_prefix="delete_apply_log",
        tool_version=__version__,
        result=result,
        extra_factory=lambda: {"deleted": deleted_entries},
    ) as resolved_log_path:
        if resolved_log_path is not None:
            result.log_path = str(resolved_log_path)
        for entry in plan.entries:
            if selection is not None and entry.path not in selection:
                result.skipped += 1
                continue
            if require_reviewed and entry.review_status != "approved":
                result.skipped += 1
                continue
            if entry.review_status == "rejected":
                result.skipped += 1
                continue
            protected_match = protected_by(Path(entry.path), rules)
            if protected_match is not None:
                result.errors.append(
                    {"path": entry.path, "safe_folder": protected_match, "error": "protected by safe folder"}
                )
                continue
            validation_error = _validate_entry(entry)
            if validation_error is not None:
                result.errors.append({"path": entry.path, "error": validation_error})
                continue
            result.bytes_deleted += entry.size_bytes or 0
            if dry_run:
                result.deleted += 1
                continue
            path = Path(entry.path)
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                result.deleted += 1
                deleted_entries.append(entry.model_dump())
                deleted_paths.append(path)
            except OSError as e:
                result.errors.append({"path": entry.path, "error": str(e)})
    if not dry_run and db_path is not None and deleted_paths:
        # Drop stale index rows so ``SUM(size_bytes)`` in the status strip
        # reflects what's actually still on disk. Pack quarantines updated
        # rows to point at the now-deleted quarantine paths; without this,
        # the indexed library size would never drop.
        _drop_indexed_rows_under(db_path, deleted_paths)
    if not quiet:
        show_delete_apply_result(result)
    return result


def show_delete_plan(plan: DeletePlan) -> None:
    table = Table(title="Delete plan", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Candidates", f"{plan.summary.candidate_entries:,}")
    table.add_row("Files", f"{plan.summary.file_entries:,}")
    table.add_row("Directories", f"{plan.summary.directory_entries:,}")
    table.add_row("Approved", f"{plan.summary.approved_entries:,}")
    console.print(table)


def show_delete_apply_result(result: DeleteApplyResult) -> None:
    table = Table(title="Delete apply result", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Deleted", f"{result.deleted:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)
