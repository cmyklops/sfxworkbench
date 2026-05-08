"""Report-only pack/folder duplicate detection."""

from __future__ import annotations

import json
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
    PackAuditReport,
    PackAuditSummary,
    PackExactGroup,
    PackFolderSummary,
    PackOverlapCandidate,
)

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
