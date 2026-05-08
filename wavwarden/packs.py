"""Report-only pack/folder duplicate detection."""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import get_connection
from wavwarden.models import (
    PackApplyResult,
    PackAuditReport,
    PackAuditSummary,
    PackExactGroup,
    PackFolderSummary,
    PackOverlapCandidate,
    PackPlan,
    PackPlanEntry,
    PackPlanFile,
    PackPlanSummary,
    PackReviewResult,
)
from wavwarden.rename import _update_directory_rows
from wavwarden.scan_errors import _md5

console = Console()


@dataclass
class _FolderStats:
    path: Path
    hashes: Counter[str] = field(default_factory=Counter)
    hash_bytes: dict[str, int] = field(default_factory=dict)
    relative_paths: list[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(self.hashes.values())

    @property
    def total_bytes(self) -> int:
        return sum(self.hash_bytes[h] * count for h, count in self.hashes.items())

    @property
    def unique_hashes(self) -> int:
        return len(self.hashes)

    def summary(self) -> PackFolderSummary:
        return PackFolderSummary(
            path=str(self.path),
            file_count=self.file_count,
            total_bytes=self.total_bytes,
            unique_hashes=self.unique_hashes,
        )

    def signature(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self.hashes.items()))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _iter_folder_chain(file_path: Path, root: Path) -> list[Path]:
    folders: list[Path] = []
    current = file_path.parent
    while current != root and _is_relative_to(current, root):
        folders.append(current)
        current = current.parent
    return folders


def _load_folder_stats(root: Path, db_path: Path) -> tuple[dict[Path, _FolderStats], int, int]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT path, md5, size_bytes
        FROM files
        WHERE (path = ? OR path LIKE ?)
        ORDER BY path
        """,
        (str(root), str(root) + "/%"),
    ).fetchall()
    conn.close()

    folders: dict[Path, _FolderStats] = {}
    considered = 0
    without_hash = 0
    for row in rows:
        path = Path(row["path"])
        md5 = row["md5"]
        size = int(row["size_bytes"] or 0)
        if not md5:
            without_hash += 1
            continue
        considered += 1
        for folder in _iter_folder_chain(path, root):
            stats = folders.setdefault(folder, _FolderStats(path=folder))
            stats.hashes[md5] += 1
            stats.hash_bytes.setdefault(md5, size)
            stats.relative_paths.append(str(path.relative_to(folder)))
    return folders, considered, without_hash


def _same_relative_paths(folders: list[_FolderStats]) -> bool:
    first = sorted(folders[0].relative_paths)
    return all(sorted(folder.relative_paths) == first for folder in folders[1:])


def _has_ancestor_pair(paths: list[Path]) -> bool:
    for a, b in combinations(paths, 2):
        if _is_relative_to(a, b) or _is_relative_to(b, a):
            return True
    return False


def _remove_redundant_ancestors(candidates: list[_FolderStats]) -> list[_FolderStats]:
    """Drop folders that only duplicate a descendant folder's exact signature."""
    signatures = {folder.path: folder.signature() for folder in candidates}
    kept: list[_FolderStats] = []
    for folder in candidates:
        has_same_descendant = any(
            other.path != folder.path
            and _is_relative_to(other.path, folder.path)
            and signatures[other.path] == signatures[folder.path]
            for other in candidates
        )
        if not has_same_descendant:
            kept.append(folder)
    return kept


def _exact_groups(candidates: list[_FolderStats]) -> list[PackExactGroup]:
    by_signature: dict[tuple[tuple[str, int], ...], list[_FolderStats]] = defaultdict(list)
    for folder in candidates:
        by_signature[folder.signature()].append(folder)

    groups: list[PackExactGroup] = []
    for folders in by_signature.values():
        if len(folders) < 2:
            continue
        paths = [folder.path for folder in folders]
        if _has_ancestor_pair(paths):
            continue
        folders = sorted(folders, key=lambda folder: str(folder.path))
        groups.append(
            PackExactGroup(
                group_id=0,
                file_count=folders[0].file_count,
                total_bytes=folders[0].total_bytes,
                same_relative_paths=_same_relative_paths(folders),
                folders=[folder.summary() for folder in folders],
            )
        )

    groups.sort(key=lambda group: (group.total_bytes * (len(group.folders) - 1), group.file_count), reverse=True)
    for i, group in enumerate(groups, start=1):
        group.group_id = i
    return groups


def _shared_counts(a: _FolderStats, b: _FolderStats) -> tuple[int, int]:
    shared_files = 0
    shared_bytes = 0
    for md5 in a.hashes.keys() & b.hashes.keys():
        count = min(a.hashes[md5], b.hashes[md5])
        shared_files += count
        shared_bytes += count * min(a.hash_bytes[md5], b.hash_bytes[md5])
    return shared_files, shared_bytes


def _overlap_candidates(
    candidates: list[_FolderStats],
    threshold: float,
    exact_pairs: set[tuple[str, str]],
    max_candidates: int,
) -> list[PackOverlapCandidate]:
    by_hash: dict[str, list[_FolderStats]] = defaultdict(list)
    for folder in candidates:
        for md5 in folder.hashes:
            by_hash[md5].append(folder)

    candidate_pairs: set[tuple[str, str]] = set()
    folder_by_path = {str(folder.path): folder for folder in candidates}
    for folders in by_hash.values():
        for a, b in combinations(sorted(folders, key=lambda folder: str(folder.path)), 2):
            if _is_relative_to(a.path, b.path) or _is_relative_to(b.path, a.path):
                continue
            key = tuple(sorted((str(a.path), str(b.path))))
            if key not in exact_pairs:
                candidate_pairs.add(key)

    overlaps: list[PackOverlapCandidate] = []
    for a_path, b_path in candidate_pairs:
        a = folder_by_path[a_path]
        b = folder_by_path[b_path]
        shared_files, shared_bytes = _shared_counts(a, b)
        smaller_bytes = min(a.total_bytes, b.total_bytes)
        larger_bytes = max(a.total_bytes, b.total_bytes)
        if smaller_bytes <= 0 or larger_bytes <= 0:
            continue
        smaller_coverage = shared_bytes / smaller_bytes
        larger_coverage = shared_bytes / larger_bytes
        if smaller_coverage < threshold:
            continue
        overlaps.append(
            PackOverlapCandidate(
                group_id=0,
                folder_a=a.summary(),
                folder_b=b.summary(),
                shared_files=shared_files,
                shared_bytes=shared_bytes,
                smaller_folder_coverage=round(smaller_coverage, 4),
                larger_folder_coverage=round(larger_coverage, 4),
                unique_files_a=max(a.file_count - shared_files, 0),
                unique_files_b=max(b.file_count - shared_files, 0),
                classification="likely_duplicate_pack" if smaller_coverage >= 0.95 else "overlapping_pack",
            )
        )

    overlaps.sort(key=lambda candidate: (candidate.shared_bytes, candidate.shared_files), reverse=True)
    overlaps = overlaps[:max_candidates]
    for i, candidate in enumerate(overlaps, start=1):
        candidate.group_id = i
    return overlaps


def audit_packs(
    root: Path,
    db_path: Path,
    min_files: int = 2,
    overlap_threshold: float = 0.95,
    max_overlap_candidates: int = 50,
) -> PackAuditReport:
    """Build a report of exact duplicate folders and high-overlap pack candidates."""
    root = root.resolve()
    folders, considered, without_hash = _load_folder_stats(root, db_path)
    candidates = _remove_redundant_ancestors([folder for folder in folders.values() if folder.file_count >= min_files])
    exact = _exact_groups(candidates)
    exact_pairs = {tuple(sorted((a.path, b.path))) for group in exact for a, b in combinations(group.folders, 2)}
    overlaps = _overlap_candidates(
        candidates,
        threshold=overlap_threshold,
        exact_pairs=exact_pairs,
        max_candidates=max_overlap_candidates,
    )
    summary = PackAuditSummary(
        folders_analyzed=len(candidates),
        exact_duplicate_groups=len(exact),
        exact_duplicate_folders=sum(len(group.folders) for group in exact),
        overlap_candidates=len(overlaps),
        indexed_files_considered=considered,
        files_without_hash=without_hash,
    )
    return PackAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        db_path=str(db_path),
        min_files=min_files,
        overlap_threshold=overlap_threshold,
        summary=summary,
        exact_groups=exact,
        overlap_candidates=overlaps,
    )


def write_pack_audit_report(report: PackAuditReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2))
    if not quiet:
        console.print(f"Pack audit report written to [cyan]{output_path}[/cyan]")


def show_pack_audit_report(report: PackAuditReport) -> None:
    summary = report.summary
    console.print(
        f"Analyzed [yellow]{summary.folders_analyzed:,}[/yellow] folder(s), "
        f"found [yellow]{summary.exact_duplicate_groups:,}[/yellow] exact duplicate group(s) "
        f"and [yellow]{summary.overlap_candidates:,}[/yellow] overlap candidate(s)."
    )

    if report.exact_groups:
        table = Table(title="Exact duplicate folder groups", show_lines=False)
        table.add_column("Group", justify="right")
        table.add_column("Files", justify="right")
        table.add_column("Folders", justify="right")
        table.add_column("First folder")
        for group in report.exact_groups[:20]:
            table.add_row(
                str(group.group_id),
                str(group.file_count),
                str(len(group.folders)),
                group.folders[0].path,
            )
        console.print(table)

    if report.overlap_candidates:
        table = Table(title="Pack overlap candidates", show_lines=False)
        table.add_column("Group", justify="right")
        table.add_column("Coverage", justify="right")
        table.add_column("Shared files", justify="right")
        table.add_column("Folder A")
        table.add_column("Folder B")
        for candidate in report.overlap_candidates[:20]:
            table.add_row(
                str(candidate.group_id),
                f"{candidate.smaller_folder_coverage:.1%}",
                str(candidate.shared_files),
                candidate.folder_a.path,
                candidate.folder_b.path,
            )
        console.print(table)


def _default_quarantine_dir(plan_path: Path) -> Path:
    return plan_path.parent / f"wavwarden_pack_quarantine_{_now_stamp()}"


def _default_pack_log_path() -> Path:
    return Path(f"pack_quarantine_log_{_now_stamp()}.json")


def _quarantine_target(path: Path, quarantine_dir: Path) -> Path:
    parts = [part for part in path.resolve().parts if part not in (path.anchor, "/")]
    target = quarantine_dir.joinpath(*parts)
    if not target.exists():
        return target
    parent = target.parent
    stem = target.name
    i = 1
    while True:
        candidate = parent / f"{stem}__{i}"
        if not candidate.exists():
            return candidate
        i += 1


def _folder_files(db_path: Path, folder: Path) -> list[PackPlanFile]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT path, md5, size_bytes
        FROM files
        WHERE path = ? OR path LIKE ?
        ORDER BY path
        """,
        (str(folder), str(folder) + "/%"),
    ).fetchall()
    conn.close()
    files: list[PackPlanFile] = []
    for row in rows:
        path = Path(row["path"])
        files.append(
            PackPlanFile(
                path=str(path),
                relative_path=str(path.relative_to(folder)),
                hash=row["md5"],
                size_bytes=row["size_bytes"],
            )
        )
    return files


def _summarize_plan(entries: list[PackPlanEntry]) -> PackPlanSummary:
    return PackPlanSummary(
        candidate_entries=len(entries),
        quarantine_entries=sum(1 for entry in entries if entry.action == "quarantine_folder"),
        review_entries=sum(1 for entry in entries if entry.action == "review"),
        ignored_entries=sum(1 for entry in entries if entry.action == "ignore"),
        planned_files=sum(entry.file_count for entry in entries if entry.action == "quarantine_folder"),
        planned_bytes=sum(entry.total_bytes for entry in entries if entry.action == "quarantine_folder"),
    )


def _choose_overlap_source(candidate: PackOverlapCandidate) -> tuple[PackFolderSummary, PackFolderSummary]:
    """Return (source_to_quarantine, folder_to_keep) for a fully covered overlap."""
    a = candidate.folder_a
    b = candidate.folder_b
    if a.total_bytes != b.total_bytes:
        return (a, b) if a.total_bytes < b.total_bytes else (b, a)
    if a.file_count != b.file_count:
        return (a, b) if a.file_count < b.file_count else (b, a)
    return (a, b) if a.path > b.path else (b, a)


def build_pack_plan(report_path: Path, output_path: Path | None = None, quiet: bool = False) -> PackPlan:
    """Create a reviewed pack consolidation plan from a pack audit report."""
    report = PackAuditReport.model_validate(json.loads(report_path.read_text()))
    db_path = Path(report.db_path)
    entries: list[PackPlanEntry] = []
    errors: list[dict] = []
    planned_sources: set[str] = set()

    for group in report.exact_groups:
        folders = sorted(group.folders, key=lambda folder: folder.path)
        if len(folders) < 2:
            continue
        keep = folders[0]
        for folder in folders[1:]:
            files = _folder_files(db_path, Path(folder.path))
            entry = PackPlanEntry(
                source_type="exact_duplicate_folder",
                source_group_id=group.group_id,
                folder_path=folder.path,
                keep_folder_path=keep.path,
                action="quarantine_folder",
                reason="folder has the same indexed audio hashes as the keep folder",
                file_count=folder.file_count,
                total_bytes=folder.total_bytes,
                files=files,
            )
            entries.append(entry)
            planned_sources.add(folder.path)

    for candidate in report.overlap_candidates:
        source, keep = _choose_overlap_source(candidate)
        action = "quarantine_folder" if candidate.smaller_folder_coverage >= 1.0 else "review"
        reason = (
            "smaller folder is fully covered by the keep folder"
            if action == "quarantine_folder"
            else "folder overlap is not complete; review unique files before taking action"
        )
        if source.path in planned_sources:
            action = "ignore"
            reason = "folder is already planned by an exact duplicate group"
        files = _folder_files(db_path, Path(source.path))
        entries.append(
            PackPlanEntry(
                source_type="pack_overlap",
                source_group_id=candidate.group_id,
                folder_path=source.path,
                keep_folder_path=keep.path,
                action=action,
                reason=reason,
                file_count=source.file_count,
                total_bytes=source.total_bytes,
                shared_files=candidate.shared_files,
                shared_bytes=candidate.shared_bytes,
                smaller_folder_coverage=candidate.smaller_folder_coverage,
                larger_folder_coverage=candidate.larger_folder_coverage,
                files=files,
            )
        )
        if action == "quarantine_folder":
            planned_sources.add(source.path)

    plan = PackPlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=report.root,
        db_path=report.db_path,
        source_report=str(report_path),
        summary=_summarize_plan(entries),
        entries=entries,
        errors=errors,
    )
    if output_path is not None:
        write_pack_plan(plan, output_path, quiet=quiet)
    return plan


def write_pack_plan(plan: PackPlan, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan.model_dump(), indent=2))
    if not quiet:
        console.print(
            f"Pack plan written to [cyan]{output_path}[/cyan] "
            f"([yellow]{plan.summary.quarantine_entries}[/yellow] quarantine, "
            f"[yellow]{plan.summary.review_entries}[/yellow] review)."
        )


def review_pack_plan(
    plan_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    groups: list[int] | None = None,
    quiet: bool = False,
) -> PackReviewResult:
    """Stamp a pack plan with approved group indexes."""
    plan = json.loads(plan_path.read_text())
    total = len(plan.get("entries", []))
    requested = set(groups or [])
    invalid = sorted(group for group in requested if group < 1 or group > total)
    if approve_all:
        approved = set(range(total))
    else:
        approved = {group - 1 for group in requested if 1 <= group <= total}

    existing_review = plan.get("review", {})
    approved.update(existing_review.get("approved_groups", []))
    approved_groups = sorted(approved)
    plan["review"] = {
        "status": "approved" if len(approved_groups) == total and total else "partially_approved",
        "approved_at": _now_iso(),
        "approved_groups": approved_groups,
    }

    output = output_path or plan_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2))
    result = PackReviewResult(
        plan_path=str(plan_path),
        output_path=str(output),
        total_groups=total,
        approved_groups=len(approved_groups),
        invalid_groups=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_groups:,}[/yellow] of "
            f"[yellow]{result.total_groups:,}[/yellow] pack plan group(s) in [cyan]{output}[/cyan]"
        )
        if invalid:
            console.print(f"[red]Ignored invalid group number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def show_pack_plan(plan: PackPlan) -> None:
    console.print(
        f"Planned [yellow]{plan.summary.quarantine_entries:,}[/yellow] folder quarantine(s), "
        f"[yellow]{plan.summary.review_entries:,}[/yellow] review-only overlap(s), "
        f"[yellow]{plan.summary.ignored_entries:,}[/yellow] ignored duplicate overlap(s)."
    )
    if plan.entries:
        table = Table(title="Pack consolidation plan", show_lines=False)
        table.add_column("Group", justify="right")
        table.add_column("Action", style="cyan")
        table.add_column("Reason", style="yellow")
        table.add_column("Folder")
        table.add_column("Keep Folder")
        for i, entry in enumerate(plan.entries[:50], start=1):
            table.add_row(str(i), entry.action, entry.reason, entry.folder_path, entry.keep_folder_path)
        console.print(table)
        if len(plan.entries) > 50:
            console.print(f"[dim]...{len(plan.entries) - 50} more pack plan group(s).[/dim]")


def _validate_plan_file(file: PackPlanFile) -> str | None:
    path = Path(file.path)
    if not path.exists():
        return "file does not exist"
    if not path.is_file():
        return "path is not a file"
    if file.size_bytes is not None:
        try:
            actual_size = path.stat().st_size
        except OSError as e:
            return str(e)
        if actual_size != file.size_bytes:
            return f"size changed: expected {file.size_bytes}, got {actual_size}"
    if file.hash and len(file.hash) == 32:
        try:
            actual_hash = _md5(path)
        except OSError as e:
            return str(e)
        if actual_hash != file.hash:
            return "md5 changed"
    return None


def _validate_pack_entry(entry: PackPlanEntry) -> list[dict]:
    errors: list[dict] = []
    folder = Path(entry.folder_path)
    keep = Path(entry.keep_folder_path)
    if not folder.exists() or not folder.is_dir():
        errors.append({"path": str(folder), "error": "source folder missing"})
    if not keep.exists() or not keep.is_dir():
        errors.append({"path": str(keep), "error": "keep folder missing"})
    if errors:
        return errors
    for file in entry.files:
        path = Path(file.path)
        if not _is_relative_to(path, folder):
            errors.append({"path": str(path), "error": "planned file is outside source folder"})
            continue
        validation_error = _validate_plan_file(file)
        if validation_error is not None:
            errors.append({"path": str(path), "error": validation_error})
    return errors


def _update_quarantined_rows(db_path: Path, old: Path, new: Path, root: Path) -> None:
    conn = get_connection(db_path)
    try:
        _update_directory_rows(conn, old, new, root)
        conn.commit()
    finally:
        conn.close()


def apply_pack_plan(
    plan_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quarantine_dir: Path | None = None,
    log_path: Path | None = None,
    require_reviewed: bool = False,
    quiet: bool = False,
) -> PackApplyResult:
    """Apply a reviewed pack plan by quarantining redundant folders."""
    raw_plan = json.loads(plan_path.read_text())
    plan = PackPlan.model_validate(raw_plan)
    if db_path is None:
        db_path = Path(plan.db_path)
    if quarantine_dir is None and not dry_run:
        quarantine_dir = _default_quarantine_dir(plan_path)

    approved = set(raw_plan.get("review", {}).get("approved_groups", []))
    result = PackApplyResult(
        planned=sum(1 for entry in plan.entries if entry.action == "quarantine_folder"),
        quarantine_dir=str(quarantine_dir) if quarantine_dir is not None else None,
        dry_run=dry_run,
    )
    if plan.errors:
        result.errors.extend(plan.errors)
        return result
    if require_reviewed and not approved:
        result.errors.append({"path": str(plan_path), "error": "plan has no approved groups"})
        return result

    applied: list[PackPlanEntry] = []
    root = Path(plan.root)
    for index, entry in enumerate(plan.entries):
        if entry.action != "quarantine_folder":
            continue
        if require_reviewed and index not in approved:
            result.errors.append({"path": entry.folder_path, "error": f"group {index + 1} is not approved"})
            continue
        validation_errors = _validate_pack_entry(entry)
        if validation_errors:
            result.errors.extend(validation_errors)
            continue
        source = Path(entry.folder_path)
        result.files_moved += len(entry.files) if dry_run else 0
        result.bytes_quarantined += entry.total_bytes if dry_run else 0
        if dry_run:
            result.quarantined += 1
            if not quiet:
                console.print(f"[dim]Would quarantine folder: {source}[/dim]")
            continue

        assert quarantine_dir is not None
        target = _quarantine_target(source, quarantine_dir)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            applied_entry = entry.model_copy(update={"quarantine_path": str(target)})
            applied.append(applied_entry)
            result.quarantined += 1
            result.files_moved += len(entry.files)
            result.bytes_quarantined += entry.total_bytes
            if db_path is not None:
                _update_quarantined_rows(db_path, source, target, root)
            if not quiet:
                console.print(f"[green]Quarantined folder:[/green] {source} -> {target}")
        except OSError as e:
            result.errors.append({"path": str(source), "target": str(target), "error": str(e)})

    if not dry_run:
        if log_path is None:
            log_path = _default_pack_log_path()
        log_plan = plan.model_copy(update={"entries": applied, "errors": []})
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log_plan.model_dump(), indent=2))
        result.log_path = str(log_path)
        if not quiet:
            console.print(f"Pack undo log written to [cyan]{log_path}[/cyan]")

    return result


def undo_pack_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> PackApplyResult:
    """Undo a previously applied pack quarantine log."""
    plan = PackPlan.model_validate(json.loads(log_path.read_text()))
    if db_path is None:
        db_path = Path(plan.db_path)
    result = PackApplyResult(planned=len(plan.entries), dry_run=dry_run, log_path=str(log_path))
    root = Path(plan.root)

    for entry in reversed(plan.entries):
        if entry.quarantine_path is None:
            result.errors.append({"path": entry.folder_path, "error": "log entry has no quarantine_path"})
            continue
        source = Path(entry.quarantine_path)
        target = Path(entry.folder_path)
        if not source.exists() or not source.is_dir():
            result.errors.append({"path": str(source), "error": "quarantined folder missing"})
            continue
        if target.exists():
            result.errors.append({"path": str(source), "target": str(target), "error": "original folder exists"})
            continue
        if dry_run:
            result.restored += 1
            result.files_moved += len(entry.files)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            result.restored += 1
            result.files_moved += len(entry.files)
            if db_path is not None:
                _update_quarantined_rows(db_path, source, target, root)
            if not quiet:
                console.print(f"[green]Restored pack folder:[/green] {source} -> {target}")
        except OSError as e:
            result.errors.append({"path": str(source), "target": str(target), "error": str(e)})
    return result
