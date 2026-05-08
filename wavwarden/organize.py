"""Report-only folder organization previews."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import get_connection
from wavwarden.junk import AUDIO_EXTENSIONS, is_junk_dir
from wavwarden.models import (
    NestingApplyResult,
    NestingCandidate,
    NestingMove,
    NestingPlan,
    NestingPlanEntry,
    OrganizeAuditReport,
    OrganizeAuditSummary,
    OrganizeEntry,
    OrganizeReviewResult,
    RenameEntry,
    RenamePlan,
    RenameResult,
)
from wavwarden.rename import _update_directory_rows, _update_file_row, apply_rename_plan, undo_rename_log

console = Console()

_SUPPORTED_PATTERNS = {"strip-leading-numbers", "redundant-nesting"}
_DOTTED_OR_DASHED_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-_.]\s*(.+?)\s*$")
_SORT_SPACE_PREFIX_RE = re.compile(r"^\s*(?:0\d+|\d)\s+(.+?)\s*$")
_DOUBLE_SPACE_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s{2,}(.+?)\s*$")
_SEPARATOR_RE = re.compile(r"[\s._-]+")
_LOW_VALUE_WRAPPER_NAMES = {
    "audio",
    "audios",
    "content",
    "contents",
    "designed",
    "file",
    "files",
    "mono",
    "sample",
    "samples",
    "sound",
    "sounds",
    "source",
    "sources",
    "stereo",
    "wav",
    "wave",
    "waves",
    "wavs",
}
_APPLYABLE_LEAF_WRAPPER_NAMES = {
    "audio",
    "audios",
    "file",
    "files",
    "sample",
    "samples",
    "wav",
    "wave",
    "waves",
    "wavs",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_leading_number(name: str) -> str | None:
    """Return a folder name without an obvious manual sort prefix."""
    for pattern in (_DOTTED_OR_DASHED_PREFIX_RE, _DOUBLE_SPACE_PREFIX_RE, _SORT_SPACE_PREFIX_RE):
        match = pattern.match(name)
        if not match:
            continue
        candidate = match.group(1).strip(" -_.")
        if candidate and candidate != name and not candidate.isdigit():
            return candidate
    return None


def _iter_dirs_at_depth(root: Path, depth: int) -> list[Path]:
    if depth < 1:
        raise ValueError("depth must be at least 1")
    dirs: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if len(rel_parts) == depth:
            dirs.append(path)
    return sorted(dirs, key=lambda path: str(path).lower())


def _path_depth(root: Path, path: Path) -> int:
    return len(path.relative_to(root).parts)


def _folder_key(name: str) -> str:
    return _SEPARATOR_RE.sub("", name).casefold()


def _walk_directory_stats(root: Path) -> tuple[dict[Path, dict], list[dict]]:
    stats: dict[Path, dict] = {}
    errors: list[dict] = []

    def onerror(error: OSError) -> None:
        errors.append({"path": error.filename or str(root), "error": str(error)})

    for dirpath, dirnames, filenames in os.walk(root, topdown=False, onerror=onerror, followlinks=False):
        path = Path(dirpath)
        child_paths = [path / dirname for dirname in dirnames if not is_junk_dir(path / dirname)]
        audio_files = sum(1 for name in filenames if Path(name).suffix.lower() in AUDIO_EXTENSIONS)
        stats[path] = {
            "child_dirs": len(child_paths),
            "direct_files": len(filenames),
            "audio_files": audio_files + sum(stats.get(child, {}).get("audio_files", 0) for child in child_paths),
            "children": sorted(child_paths, key=lambda child: child.name.casefold()),
        }
    return stats, errors


def _audit_strip_leading_numbers(root: Path, depth: int) -> OrganizeAuditReport:
    dirs = _iter_dirs_at_depth(root, depth)
    entries: list[OrganizeEntry] = []
    errors: list[dict] = []
    planned_targets: set[Path] = set()

    for path in dirs:
        new_name = _strip_leading_number(path.name)
        if not new_name:
            continue

        target = path.with_name(new_name)
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
            OrganizeEntry(
                old_path=str(path),
                new_path=str(target),
                old_name=path.name,
                new_name=new_name,
            )
        )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern="strip-leading-numbers",
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            planned=len(entries),
            errors=len(errors),
        ),
        entries=entries,
        errors=errors,
    )


def _audit_redundant_nesting(root: Path, depth: int) -> OrganizeAuditReport:
    stats, errors = _walk_directory_stats(root)
    candidates: list[NestingCandidate] = []
    seen: set[tuple[Path, str]] = set()
    dirs = sorted(
        (path for path in stats if path != root and _path_depth(root, path) <= depth),
        key=lambda path: str(path).lower(),
    )

    def add_candidate(
        path: Path,
        kind: str,
        suggested_action: str,
        reason: str,
        target_path: Path | None = None,
        confidence: str = "medium",
    ) -> None:
        key = (path, kind)
        if key in seen:
            return
        seen.add(key)
        path_stats = stats[path]
        candidates.append(
            NestingCandidate(
                path=str(path),
                name=path.name,
                kind=kind,
                suggested_action=suggested_action,
                reason=reason,
                depth=_path_depth(root, path),
                parent_path=str(path.parent),
                target_path=str(target_path) if target_path is not None else None,
                child_dirs=path_stats["child_dirs"],
                direct_files=path_stats["direct_files"],
                audio_files=path_stats["audio_files"],
                confidence=confidence,
            )
        )

    for path in dirs:
        path_stats = stats[path]
        parent_key = _folder_key(path.parent.name)
        name_key = _folder_key(path.name)

        if name_key and name_key == parent_key and path_stats["audio_files"] > 0:
            add_candidate(
                path,
                kind="repeated_folder_name",
                suggested_action="review_flatten_child_into_parent",
                reason="folder name repeats its parent",
                target_path=path.parent,
                confidence="high",
            )

        if path_stats["direct_files"] == 0 and path_stats["child_dirs"] == 1 and path_stats["audio_files"] > 0:
            only_child = path_stats["children"][0]
            add_candidate(
                path,
                kind="single_child_chain",
                suggested_action="review_collapse_wrapper",
                reason="folder only contains one child folder and no direct files",
                target_path=only_child,
            )

        if name_key in _LOW_VALUE_WRAPPER_NAMES and path_stats["audio_files"] > 0:
            add_candidate(
                path,
                kind="low_value_wrapper",
                suggested_action="review_flatten_wrapper",
                reason="generic wrapper folder adds little search context",
                target_path=path.parent,
            )

    return OrganizeAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        pattern="redundant-nesting",
        depth=depth,
        summary=OrganizeAuditSummary(
            directories_scanned=len(dirs),
            candidates=len(candidates),
            errors=len(errors),
        ),
        candidates=candidates,
        errors=errors,
    )


def audit_organization(root: Path, pattern: str = "strip-leading-numbers", depth: int = 1) -> OrganizeAuditReport:
    """Build a report-only folder organization preview."""
    if pattern not in _SUPPORTED_PATTERNS:
        supported = "', '".join(sorted(_SUPPORTED_PATTERNS))
        raise ValueError(f"Supported patterns: '{supported}'")
    if depth < 1:
        raise ValueError("depth must be at least 1")

    root = root.resolve()
    if pattern == "strip-leading-numbers":
        return _audit_strip_leading_numbers(root, depth)
    return _audit_redundant_nesting(root, depth)


def write_organize_audit_report(report: OrganizeAuditReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2))
    if not quiet:
        console.print(f"Organization preview written to [cyan]{output_path}[/cyan]")


def _default_nesting_log_path() -> Path:
    return Path(f"nesting_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


def _write_nesting_plan(plan: NestingPlan, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan.model_dump(), indent=2))


def build_nesting_plan_from_report(
    report_path: Path,
    kind: str = "repeated_folder_name",
    output_path: Path | None = None,
    quiet: bool = False,
) -> NestingPlan:
    """Build a reviewed-plan candidate from a redundant nesting audit."""
    raw_report = json.loads(report_path.read_text())
    report = OrganizeAuditReport.model_validate(raw_report)
    errors: list[dict] = list(report.errors)
    entries: list[NestingPlanEntry] = []
    supported_kinds = {"repeated_folder_name", "single_child_chain", "low_value_wrapper"}

    if report.pattern != "redundant-nesting":
        errors.append({"path": report.root, "error": "source report must use pattern='redundant-nesting'"})
    if kind not in supported_kinds:
        errors.append({"path": report.root, "error": f"candidate kind '{kind}' is report-only"})

    for candidate in report.candidates:
        if candidate.kind != kind:
            continue
        source = Path(candidate.path)
        if not source.exists() or not source.is_dir():
            errors.append({"path": str(source), "error": "source directory missing"})
            continue

        if candidate.kind == "repeated_folder_name":
            target = Path(candidate.target_path) if candidate.target_path is not None else source.parent
            if source.parent != target:
                errors.append({"path": str(source), "target": str(target), "error": "target must be source parent"})
                continue
            if not target.exists() or not target.is_dir():
                errors.append({"path": str(source), "target": str(target), "error": "target directory missing"})
                continue

            moves: list[NestingMove] = []
            planned_targets: set[Path] = set()
            for child in sorted(source.iterdir(), key=lambda path: path.name.casefold()):
                destination = target / child.name
                if destination.exists():
                    errors.append({"path": str(child), "target": str(destination), "error": "target exists"})
                    continue
                if destination in planned_targets:
                    errors.append(
                        {"path": str(child), "target": str(destination), "error": "target planned more than once"}
                    )
                    continue
                planned_targets.add(destination)
                moves.append(
                    NestingMove(
                        old_path=str(child),
                        new_path=str(destination),
                        path_type="dir" if child.is_dir() else "file",
                    )
                )
            action = "flatten_child_into_parent"
            target_path = target
        elif candidate.kind == "single_child_chain":
            children = sorted(source.iterdir(), key=lambda path: path.name.casefold())
            if len(children) != 1 or not children[0].is_dir():
                errors.append({"path": str(source), "error": "source must contain exactly one child directory"})
                continue
            child = children[0]
            if _folder_key(child.name) in _LOW_VALUE_WRAPPER_NAMES:
                continue
            target_path = source.parent
            destination = target_path / child.name
            if destination.exists():
                errors.append({"path": str(child), "target": str(destination), "error": "target exists"})
                continue
            moves = [
                NestingMove(
                    old_path=str(child),
                    new_path=str(destination),
                    path_type="dir",
                )
            ]
            action = "collapse_single_child_wrapper"
        else:
            if _folder_key(source.name) not in _APPLYABLE_LEAF_WRAPPER_NAMES:
                continue
            children = sorted(source.iterdir(), key=lambda path: path.name.casefold())
            if any(child.is_dir() for child in children):
                continue
            target_path = Path(candidate.target_path) if candidate.target_path is not None else source.parent
            if source.parent != target_path:
                errors.append(
                    {"path": str(source), "target": str(target_path), "error": "target must be source parent"}
                )
                continue
            if not target_path.exists() or not target_path.is_dir():
                errors.append({"path": str(source), "target": str(target_path), "error": "target directory missing"})
                continue
            moves = []
            planned_targets: set[Path] = set()
            for child in children:
                destination = target_path / child.name
                if destination.exists():
                    errors.append({"path": str(child), "target": str(destination), "error": "target exists"})
                    continue
                if destination in planned_targets:
                    errors.append(
                        {"path": str(child), "target": str(destination), "error": "target planned more than once"}
                    )
                    continue
                planned_targets.add(destination)
                moves.append(
                    NestingMove(
                        old_path=str(child),
                        new_path=str(destination),
                        path_type="file",
                    )
                )
            action = "flatten_low_value_leaf_wrapper"

        if not moves:
            errors.append({"path": str(source), "error": "no children to move"})
            continue
        entries.append(
            NestingPlanEntry(
                source_path=str(source),
                target_path=str(target_path),
                kind=candidate.kind,
                action=action,
                reason=candidate.reason,
                audio_files=candidate.audio_files,
                moves=moves,
            )
        )

    plan = NestingPlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=report.root,
        source_report=str(report_path),
        entries=sorted(
            entries, key=lambda entry: (len(Path(entry.source_path).parts), entry.source_path), reverse=True
        ),
        errors=errors,
    )
    if output_path is not None:
        _write_nesting_plan(plan, output_path)
        if not quiet:
            console.print(f"Nesting plan written to [cyan]{output_path}[/cyan]")
    return plan


def review_organize_report(
    report_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    entries: list[int] | None = None,
    quiet: bool = False,
) -> OrganizeReviewResult:
    """Stamp an organization report with approved entry indexes."""
    report = json.loads(report_path.read_text())
    total = len(report.get("entries", []))
    requested = set(entries or [])
    invalid = sorted(entry for entry in requested if entry < 1 or entry > total)
    if approve_all:
        approved = set(range(total))
    else:
        approved = {entry - 1 for entry in requested if 1 <= entry <= total}

    existing_review = report.get("review", {})
    approved.update(existing_review.get("approved_entries", []))
    approved_entries = sorted(approved)
    report["review"] = {
        "status": "approved" if len(approved_entries) == total and total else "partially_approved",
        "approved_at": _now_iso(),
        "approved_entries": approved_entries,
    }

    output = output_path or report_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    result = OrganizeReviewResult(
        report_path=str(report_path),
        output_path=str(output),
        total_entries=total,
        approved_entries=len(approved_entries),
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_entries:,}[/yellow] of "
            f"[yellow]{result.total_entries:,}[/yellow] organization entry/entries in [cyan]{output}[/cyan]"
        )
        if invalid:
            console.print(f"[red]Ignored invalid entry number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def _rename_plan_from_report(report: OrganizeAuditReport, raw_report: dict, require_reviewed: bool) -> RenamePlan:
    approved = set(raw_report.get("review", {}).get("approved_entries", []))
    entries: list[RenameEntry] = []
    errors = list(report.errors)
    if report.pattern != "strip-leading-numbers":
        errors.append(
            {
                "path": report.root,
                "error": f"organize pattern '{report.pattern}' is report-only and cannot be applied",
            }
        )
        return RenamePlan(
            generated_at=_now_iso(),
            root=report.root,
            pattern=f"organize:{report.pattern}",
            entries=[],
            errors=errors,
        )
    if require_reviewed and not approved:
        errors.append({"path": raw_report.get("root"), "error": "report has no approved entries"})

    for index, entry in enumerate(report.entries):
        if entry.action != "rename":
            errors.append({"path": entry.old_path, "error": f"entry {index + 1} action is not applicable"})
            continue
        if require_reviewed and index not in approved:
            errors.append({"path": entry.old_path, "error": f"entry {index + 1} is not approved"})
            continue
        entries.append(
            RenameEntry(
                old_path=entry.old_path,
                new_path=entry.new_path,
                old_filename=entry.old_name,
                new_filename=entry.new_name,
                issue_fixes=[entry.reason],
            )
        )

    return RenamePlan(
        generated_at=_now_iso(),
        root=report.root,
        pattern=f"organize:{report.pattern}",
        entries=sorted(entries, key=lambda entry: (len(Path(entry.old_path).parts), entry.old_path), reverse=True),
        errors=errors,
    )


def apply_organize_report(
    report_path: Path,
    db_path: Path | None = None,
    log_path: Path | None = None,
    require_reviewed: bool = False,
    quiet: bool = False,
) -> RenameResult:
    """Apply a reviewed organization report using the rename engine."""
    raw_report = json.loads(report_path.read_text())
    report = OrganizeAuditReport.model_validate(raw_report)
    plan = _rename_plan_from_report(report, raw_report, require_reviewed=require_reviewed)
    return apply_rename_plan(plan, db_path=db_path, log_path=log_path, dry_run=False, quiet=quiet)


def _approved_entry_indexes(raw_plan: dict) -> set[int]:
    return set(raw_plan.get("review", {}).get("approved_entries", []))


def _update_moved_path_rows(conn, old: Path, new: Path, root: Path) -> None:
    if new.is_dir():
        _update_directory_rows(conn, old, new, root)
    else:
        _update_file_row(conn, old, new, root)


def apply_nesting_plan(
    plan_path: Path,
    db_path: Path | None = None,
    log_path: Path | None = None,
    require_reviewed: bool = False,
    dry_run: bool = True,
    quiet: bool = False,
) -> NestingApplyResult:
    """Flatten repeated-folder-name entries from a reviewed nesting plan."""
    raw_plan = json.loads(plan_path.read_text())
    plan = NestingPlan.model_validate(raw_plan)
    approved = _approved_entry_indexes(raw_plan)
    result = NestingApplyResult(planned=len(plan.entries), dry_run=dry_run)
    errors = list(plan.errors)

    if errors:
        result.errors.extend(errors)
        if not quiet:
            console.print("[red]Refusing to apply nesting plan with unresolved errors.[/red]")
        return result
    if require_reviewed and not approved:
        result.errors.append({"path": plan.root, "error": "plan has no approved entries"})
        return result

    selected_entries: list[tuple[int, NestingPlanEntry]] = []
    for index, entry in enumerate(plan.entries):
        if require_reviewed and index not in approved:
            result.errors.append({"path": entry.source_path, "error": f"entry {index + 1} is not approved"})
            continue
        selected_entries.append((index, entry))

    if result.errors:
        return result
    if dry_run:
        result.flattened = len(selected_entries)
        result.moved = sum(len(entry.moves) for _, entry in selected_entries)
        if not quiet:
            show_nesting_plan(plan)
        return result

    if log_path is None:
        log_path = _default_nesting_log_path()
    conn = get_connection(db_path) if db_path is not None else None
    root = Path(plan.root)
    applied: list[NestingPlanEntry] = []

    for _, entry in selected_entries:
        source = Path(entry.source_path)
        target = Path(entry.target_path)
        if not source.exists() or not source.is_dir():
            result.errors.append({"path": str(source), "error": "source directory missing"})
            continue
        if not target.exists() or not target.is_dir():
            result.errors.append({"path": str(source), "target": str(target), "error": "target directory missing"})
            continue

        entry_errors: list[dict] = []
        for move in entry.moves:
            old = Path(move.old_path)
            new = Path(move.new_path)
            if not old.exists():
                entry_errors.append({"path": str(old), "error": "source missing"})
            if new.exists():
                entry_errors.append({"path": str(old), "target": str(new), "error": "target exists"})
        if entry_errors:
            result.errors.extend(entry_errors)
            continue

        moved_for_entry: list[NestingMove] = []
        for move in entry.moves:
            old = Path(move.old_path)
            new = Path(move.new_path)
            try:
                old.rename(new)
                moved_for_entry.append(move)
                result.moved += 1
                if conn is not None:
                    _update_moved_path_rows(conn, old, new, root)
            except OSError as e:
                result.errors.append({"path": str(old), "target": str(new), "error": str(e)})
                break

        if moved_for_entry:
            applied.append(entry.model_copy(update={"moves": moved_for_entry}))
        if moved_for_entry and len(moved_for_entry) == len(entry.moves):
            try:
                source.rmdir()
            except OSError as e:
                result.errors.append({"path": str(source), "error": f"could not remove emptied folder: {e}"})
            result.flattened += 1

    if conn is not None:
        conn.commit()
        conn.close()

    log_plan = plan.model_copy(update={"entries": applied, "errors": []})
    _write_nesting_plan(log_plan, log_path)
    result.log_path = str(log_path)
    if not quiet:
        console.print(f"Nesting undo log written to [cyan]{log_path}[/cyan]")
    return result


def undo_nesting_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> NestingApplyResult:
    """Undo a previously applied nesting flatten log."""
    plan = NestingPlan.model_validate(json.loads(log_path.read_text()))
    result = NestingApplyResult(planned=len(plan.entries), dry_run=dry_run, log_path=str(log_path))
    conn = get_connection(db_path) if db_path is not None and not dry_run else None
    root = Path(plan.root)

    for entry in reversed(plan.entries):
        source = Path(entry.source_path)
        if dry_run:
            result.undone += 1
            result.moved += len(entry.moves)
            continue
        source.mkdir(exist_ok=True)
        entry_errors: list[dict] = []
        for move in reversed(entry.moves):
            old = Path(move.old_path)
            new = Path(move.new_path)
            if not new.exists():
                entry_errors.append({"path": str(new), "error": "flattened path missing"})
            if old.exists():
                entry_errors.append({"path": str(new), "target": str(old), "error": "original path exists"})
        if entry_errors:
            result.errors.extend(entry_errors)
            continue
        for move in reversed(entry.moves):
            old = Path(move.old_path)
            new = Path(move.new_path)
            try:
                new.rename(old)
                result.moved += 1
                if conn is not None:
                    _update_moved_path_rows(conn, new, old, root)
            except OSError as e:
                result.errors.append({"path": str(new), "target": str(old), "error": str(e)})
                break
        else:
            result.undone += 1

    if conn is not None:
        conn.commit()
        conn.close()
    return result


def undo_organize_log(
    log_path: Path,
    db_path: Path | None = None,
    dry_run: bool = True,
    quiet: bool = False,
) -> RenameResult:
    """Undo a previously applied organization log."""
    return undo_rename_log(log_path, db_path=db_path, dry_run=dry_run, quiet=quiet)


def show_nesting_plan(plan: NestingPlan) -> None:
    console.print(
        f"Planned [yellow]{len(plan.entries):,}[/yellow] nesting flatten(s), "
        f"found [yellow]{len(plan.errors):,}[/yellow] error(s)."
    )
    if plan.entries:
        table = Table(title="Repeated folder flatten plan", show_lines=False)
        table.add_column("Repeated Folder", style="white")
        table.add_column("Target", style="cyan")
        table.add_column("Moves", justify="right", style="yellow")
        for entry in plan.entries[:50]:
            table.add_row(entry.source_path, entry.target_path, f"{len(entry.moves):,}")
        console.print(table)
        if len(plan.entries) > 50:
            console.print(f"[dim]...{len(plan.entries) - 50} more flatten(s).[/dim]")
    if plan.errors:
        console.print("[red]Plan has collision/error(s); apply would be refused until resolved.[/red]")


def show_organize_audit_report(report: OrganizeAuditReport) -> None:
    console.print(
        f"Scanned [yellow]{report.summary.directories_scanned:,}[/yellow] folder(s), "
        f"planned [yellow]{report.summary.planned:,}[/yellow] rename(s), "
        f"found [yellow]{report.summary.candidates:,}[/yellow] review candidate(s), "
        f"found [yellow]{report.summary.errors:,}[/yellow] error(s)."
    )
    if report.entries:
        table = Table(title="Folder organization preview", show_lines=False)
        table.add_column("Old", style="white")
        table.add_column("New", style="cyan")
        for entry in report.entries[:50]:
            table.add_row(entry.old_name, entry.new_name)
        console.print(table)
        if len(report.entries) > 50:
            console.print(f"[dim]...{len(report.entries) - 50} more planned rename(s).[/dim]")
    if report.candidates:
        table = Table(title="Folder structure review candidates", show_lines=False)
        table.add_column("Kind", style="cyan")
        table.add_column("Folder", style="white")
        table.add_column("Suggestion", style="yellow")
        table.add_column("Audio", justify="right")
        for candidate in report.candidates[:50]:
            table.add_row(
                candidate.kind,
                candidate.path,
                candidate.suggested_action,
                f"{candidate.audio_files:,}",
            )
        console.print(table)
        if len(report.candidates) > 50:
            console.print(f"[dim]...{len(report.candidates) - 50} more review candidate(s).[/dim]")
    if report.errors:
        console.print("[red]Preview has collision/error(s); apply would be refused until resolved.[/red]")
