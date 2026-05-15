"""Dual-mono audit, reviewed plan, and copy-output conversion."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.apply_logs import apply_session, mark_entries_reviewed
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection, path_scope_filter, path_scope_params, resolve_scope_root
from sfxworkbench.models import (
    DualMonoApplyResult,
    DualMonoEntry,
    DualMonoPlan,
    DualMonoPlanEntry,
    DualMonoPlanSummary,
    DualMonoReport,
    DualMonoReviewResult,
    DualMonoSummary,
)
from sfxworkbench.preservation import build_preservation_rules, move_protected_by
from sfxworkbench.scan import ensure_audio_info
from sfxworkbench.utils import atomic_write_json

console = Console()
_VALID_REVIEW_STATES = {"approved", "rejected", "pending"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _md5_bytes(data: np.ndarray) -> str:
    return hashlib.md5(np.ascontiguousarray(data).tobytes()).hexdigest()


def _load_stereo(path: Path):
    import soundfile as sf

    data, sample_rate = sf.read(str(path), always_2d=True)
    info = sf.info(str(path))
    if data.shape[1] != 2:
        raise ValueError("file is not stereo")
    return data, sample_rate, info


def _load_indexed_stereo_rows(root: Path, db_path: Path):
    conn = get_connection(db_path)
    rows = conn.execute(
        f"""
        SELECT id, path, filename, size_bytes, mtime, md5, sample_rate, bit_depth,
               duration_s, channels
        FROM files
        WHERE {path_scope_filter()}
          AND channels = 2
          AND scan_error IS NULL
        ORDER BY path
        """,
        path_scope_params(root),
    ).fetchall()
    conn.close()
    return rows


def build_dual_mono_report(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    threshold: float = 0.000001,
    limit: int = 200,
) -> DualMonoReport:
    """Report stereo files whose channels are identical or nearly identical."""
    if threshold < 0:
        raise ValueError("--threshold must be 0 or greater")
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    root = resolve_scope_root(root)
    ensure_audio_info(db_path, root)
    rows = _load_indexed_stereo_rows(root, db_path)
    entries: list[DualMonoEntry] = []
    errors: list[dict] = []
    exact = 0
    near_exact = 0
    review = 0
    group_id = 1
    for row in rows:
        path = Path(row["path"])
        try:
            data, sample_rate, _info = _load_stereo(path)
        except Exception as e:
            errors.append({"path": str(path), "error": str(e)})
            continue
        left = data[:, 0]
        right = data[:, 1]
        diff = left - right
        max_abs = float(np.max(np.abs(diff))) if diff.size else 0.0
        rms = float(np.sqrt(np.mean(diff**2))) if diff.size else 0.0
        left_hash = _md5_bytes(left)
        right_hash = _md5_bytes(right)
        if left_hash == right_hash:
            confidence = "exact"
            exact += 1
        elif max_abs <= threshold and rms <= threshold:
            confidence = "near_exact"
            near_exact += 1
        else:
            continue
        evidence = [f"max_abs_difference:{max_abs:.8f}", f"rms_difference:{rms:.8f}"]
        if confidence == "exact":
            evidence.append("channel_hashes_match")
        entries.append(
            DualMonoEntry(
                group_id=group_id,
                file_id=row["id"],
                path=str(path),
                filename=row["filename"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                md5=row["md5"],
                sample_rate=row["sample_rate"] or sample_rate,
                bit_depth=row["bit_depth"],
                duration_s=row["duration_s"],
                channels=row["channels"],
                left_md5=left_hash,
                right_md5=right_hash,
                max_abs_difference=max_abs,
                rms_difference=rms,
                confidence=confidence,
                evidence=evidence,
            )
        )
        group_id += 1
    selected = entries if limit == 0 else entries[:limit]
    return DualMonoReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        db_path=str(db_path),
        limit=limit,
        summary=DualMonoSummary(
            files_considered=len(rows),
            candidates=len(entries),
            exact=exact,
            near_exact=near_exact,
            review=review,
        ),
        entries=selected,
        errors=errors,
    )


def write_dual_mono_report(report: DualMonoReport, output_path: Path, quiet: bool = False) -> None:
    atomic_write_json(output_path, report)
    if not quiet:
        console.print(f"Dual-mono report written to [cyan]{output_path}[/cyan]")


def _summarize_plan(plan: DualMonoPlan) -> DualMonoPlanSummary:
    return DualMonoPlanSummary(
        candidate_entries=len(plan.entries),
        approved_entries=sum(1 for entry in plan.entries if entry.review_status == "approved"),
        rejected_entries=sum(1 for entry in plan.entries if entry.review_status == "rejected"),
    )


def build_dual_mono_plan(
    report_path: Path,
    *,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
) -> DualMonoPlan:
    report = DualMonoReport.model_validate_json(report_path.read_text())
    rules = build_preservation_rules(config_path=config_path, safe_folders=safe_folders)
    entries: list[DualMonoPlanEntry] = []
    errors: list[dict] = []
    root = Path(report.root)
    for item in report.entries:
        protected_match = move_protected_by(Path(item.path), rules)
        if protected_match is not None:
            errors.append({"path": item.path, "safe_folder": protected_match, "error": "protected by safe folder"})
            continue
        source = Path(item.path)
        try:
            relative = source.relative_to(root)
        except ValueError:
            relative = Path(source.name)
        entries.append(
            DualMonoPlanEntry(
                group_id=item.group_id,
                path=item.path,
                output_relative_path=str(relative.with_name(f"{relative.stem}.mono{relative.suffix}")),
                size_bytes=item.size_bytes,
                mtime=item.mtime,
                md5=item.md5,
                confidence=item.confidence,
            )
        )
    plan = DualMonoPlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        source_report=str(report_path),
        root=report.root,
        db_path=report.db_path,
        safe_folders=list(rules.safe_folders),
        summary=DualMonoPlanSummary(candidate_entries=len(entries)),
        entries=entries,
        errors=errors,
    )
    plan.summary = _summarize_plan(plan)
    return plan


def write_dual_mono_plan(plan: DualMonoPlan, output_path: Path, quiet: bool = False) -> None:
    atomic_write_json(output_path, plan)
    if not quiet:
        console.print(f"Dual-mono plan written to [cyan]{output_path}[/cyan]")


def load_dual_mono_plan(plan_path: Path) -> DualMonoPlan:
    return DualMonoPlan.model_validate_json(plan_path.read_text())


def review_dual_mono_plan(
    plan_path: Path,
    *,
    output_path: Path | None = None,
    approve_all: bool = False,
    groups: list[int] | None = None,
    reject_groups: list[int] | None = None,
    quiet: bool = False,
) -> DualMonoReviewResult:
    plan = load_dual_mono_plan(plan_path)
    by_group = {entry.group_id: entry for entry in plan.entries}
    invalid = mark_entries_reviewed(by_group, approve=groups, reject=reject_groups, approve_all=approve_all)
    plan.summary = _summarize_plan(plan)
    output = output_path or plan_path
    atomic_write_json(output, plan)
    result = DualMonoReviewResult(
        plan_path=str(plan_path),
        output_path=str(output),
        total_entries=len(plan.entries),
        approved_entries=plan.summary.approved_entries,
        rejected_entries=plan.summary.rejected_entries,
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(f"Approved [yellow]{result.approved_entries:,}[/yellow] dual-mono entrie(s).")
    return result


def _validate_entry(entry: DualMonoPlanEntry) -> str | None:
    path = Path(entry.path)
    if not path.exists():
        return "source file does not exist"
    stat = path.stat()
    if entry.size_bytes is not None and stat.st_size != entry.size_bytes:
        return "size changed"
    if entry.mtime is not None and stat.st_mtime != entry.mtime:
        return "mtime changed"
    return None


def apply_dual_mono_plan(
    plan_path: Path,
    *,
    output_root: Path,
    dry_run: bool = True,
    require_reviewed: bool = False,
    log_path: Path | None = None,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    quiet: bool = False,
    target_paths: tuple[str, ...] | None = None,
) -> DualMonoApplyResult:
    """Apply a dual-mono plan.

    ``target_paths`` (Tier 3.8): if given, only entries whose ``path`` is in
    this set are merged. Other entries are silently skipped.
    """
    import soundfile as sf

    plan = load_dual_mono_plan(plan_path)
    rules = build_preservation_rules(
        config_path=config_path,
        safe_folders=[Path(folder) for folder in plan.safe_folders] + list(safe_folders or []),
    )
    result = DualMonoApplyResult(planned=len(plan.entries), dry_run=dry_run, output_root=str(output_root))
    protected_output = move_protected_by(output_root, rules)
    if protected_output is not None:
        result.errors.append(
            {"path": str(output_root), "safe_folder": protected_output, "error": "protected by safe folder"}
        )
        return result
    selection: frozenset[str] | None = frozenset(target_paths) if target_paths is not None else None
    written: list[dict] = []
    with apply_session(
        plan_path=plan_path,
        dry_run=dry_run,
        log_path=log_path,
        log_prefix="dual_mono_apply_log",
        tool_version=__version__,
        result=result,
        extra_factory=lambda: {"output_root": str(output_root), "written": written},
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
            protected_source = move_protected_by(Path(entry.path), rules)
            if protected_source is not None:
                result.errors.append(
                    {"path": entry.path, "safe_folder": protected_source, "error": "protected by safe folder"}
                )
                continue
            validation_error = _validate_entry(entry)
            if validation_error is not None:
                result.errors.append({"path": entry.path, "error": validation_error})
                continue
            output_path = output_root / entry.output_relative_path
            if output_path.exists():
                result.errors.append({"path": str(output_path), "error": "output file already exists"})
                continue
            if dry_run:
                result.written += 1
                continue
            try:
                data, sample_rate, info = _load_stereo(Path(entry.path))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(output_path), data[:, 0], sample_rate, subtype=getattr(info, "subtype", None))
                size = output_path.stat().st_size
                result.written += 1
                result.bytes_written += size
                written.append({"source_path": entry.path, "output_path": str(output_path), "bytes_written": size})
            except Exception as e:
                result.errors.append({"path": entry.path, "error": str(e)})
    if not quiet:
        show_dual_mono_apply_result(result)
    return result


def show_dual_mono_report(report: DualMonoReport) -> None:
    table = Table(title="Dual-mono report", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Stereo files considered", f"{report.summary.files_considered:,}")
    table.add_row("Candidates", f"{report.summary.candidates:,}")
    table.add_row("Exact", f"{report.summary.exact:,}")
    table.add_row("Near exact", f"{report.summary.near_exact:,}")
    console.print(table)


def show_dual_mono_plan(plan: DualMonoPlan) -> None:
    table = Table(title="Dual-mono plan", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Candidates", f"{plan.summary.candidate_entries:,}")
    table.add_row("Approved", f"{plan.summary.approved_entries:,}")
    table.add_row("Rejected", f"{plan.summary.rejected_entries:,}")
    console.print(table)


def show_dual_mono_apply_result(result: DualMonoApplyResult) -> None:
    table = Table(title="Dual-mono apply result", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Written", f"{result.written:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)
