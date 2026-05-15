"""Build, apply, and undo logic for redundant-nesting plans.

The nesting workflow is a self-contained subsystem split out of
``sfxworkbench.organize``. Audit/detection lives in ``organize`` (the
``_audit_redundant_nesting`` pass produces ``NestingCandidate`` rows inside
an ``OrganizeAuditReport``); everything that turns those candidates into a
plan and applies it lives here.

Public symbols are re-exported from ``sfxworkbench.organize`` for backwards
compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.apply_logs import default_apply_log_path_for_plan
from sfxworkbench.db import get_connection
from sfxworkbench.models import (
    NestingApplyResult,
    NestingMove,
    NestingPlan,
    NestingPlanEntry,
    OrganizeAuditReport,
)
from sfxworkbench.preservation import PreservationRules, build_preservation_rules
from sfxworkbench.rename import _update_directory_rows, _update_file_row

console = Console()


def _default_nesting_log_path(plan_path: Path) -> Path:
    return default_apply_log_path_for_plan(plan_path, "nesting_log")


def _write_nesting_plan(plan: NestingPlan, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan.model_dump(), indent=2))


def _nesting_protection_errors(entry: NestingPlanEntry, rules: PreservationRules) -> list[dict]:
    if not rules.safe_folders:
        return []
    from sfxworkbench.organize import _protection_error

    errors: list[dict] = []
    source_error = _protection_error(Path(entry.source_path), rules)
    if source_error is not None:
        errors.append(source_error)
    for move in entry.moves:
        move_error = _protection_error(Path(move.old_path), rules)
        if move_error is not None:
            errors.append(move_error)
    return errors


def _approved_entry_indexes(raw_plan: dict) -> set[int]:
    return set(raw_plan.get("review", {}).get("approved_entries", []))


def _update_moved_path_rows(conn, old: Path, new: Path, root: Path) -> None:
    if new.is_dir():
        _update_directory_rows(conn, old, new, root)
    else:
        _update_file_row(conn, old, new, root)


def build_nesting_plan_from_report(
    report_path: Path,
    kind: str = "repeated_folder_name",
    output_path: Path | None = None,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
) -> NestingPlan:
    """Build a reviewed-plan candidate from a redundant nesting audit."""
    from sfxworkbench.organize import (
        _APPLYABLE_LEAF_WRAPPER_NAMES,
        _LOW_VALUE_WRAPPER_NAMES,
        _folder_key,
        _is_numeric_category_parent,
        _is_source_designed_branch,
        _now_iso,
    )

    raw_report = json.loads(report_path.read_text())
    report = OrganizeAuditReport.model_validate(raw_report)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
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
        if _is_source_designed_branch(source):
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
            if _is_numeric_category_parent(source, child):
                continue
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
        entry = NestingPlanEntry(
            source_path=str(source),
            target_path=str(target_path),
            kind=candidate.kind,
            action=action,
            reason=candidate.reason,
            audio_files=candidate.audio_files,
            moves=moves,
        )
        entry_protection_errors = _nesting_protection_errors(entry, rules)
        if entry_protection_errors:
            errors.extend(entry_protection_errors)
            continue
        entries.append(entry)

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


def apply_nesting_plan(
    plan_path: Path,
    db_path: Path | None = None,
    log_path: Path | None = None,
    require_reviewed: bool = False,
    dry_run: bool = True,
    quiet: bool = False,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    allow_partial: bool = False,
) -> NestingApplyResult:
    """Flatten repeated-folder-name entries from a reviewed nesting plan."""
    raw_plan = json.loads(plan_path.read_text())
    plan = NestingPlan.model_validate(raw_plan)
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    approved = _approved_entry_indexes(raw_plan)
    result = NestingApplyResult(planned=len(plan.entries), dry_run=dry_run)
    errors = list(plan.errors)

    if errors:
        result.errors.extend(errors)
        if not allow_partial:
            if not quiet:
                console.print("[red]Refusing to apply nesting plan with unresolved errors.[/red]")
            return result
        if not quiet:
            console.print("[yellow]Plan has unresolved errors; applying valid nesting entries only.[/yellow]")
    if require_reviewed and not approved:
        result.errors.append({"path": plan.root, "error": "plan has no approved entries"})
        return result

    selected_entries: list[tuple[int, NestingPlanEntry]] = []
    for index, entry in enumerate(plan.entries):
        if require_reviewed and index not in approved:
            result.errors.append({"path": entry.source_path, "error": f"entry {index + 1} is not approved"})
            continue
        entry_protection_errors = _nesting_protection_errors(entry, rules)
        if entry_protection_errors:
            result.errors.extend(entry_protection_errors)
            continue
        selected_entries.append((index, entry))

    if result.errors and not allow_partial:
        return result
    if dry_run:
        result.flattened = len(selected_entries)
        result.moved = sum(len(entry.moves) for _, entry in selected_entries)
        if not quiet:
            show_nesting_plan(plan)
        return result

    if log_path is None:
        log_path = _default_nesting_log_path(plan_path)
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
