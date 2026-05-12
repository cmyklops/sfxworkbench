"""Exact-hash import/database comparison reports."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection
from sfxworkbench.junk import AUDIO_EXTENSIONS, is_inside_junk_dir, is_junk_file
from sfxworkbench.models import (
    CompareEntry,
    CompareMatch,
    ComparePlan,
    ComparePlanEntry,
    ComparePlanSummary,
    CompareReport,
    CompareSummary,
)
from sfxworkbench.utils import json_dumps

console = Console()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _md5(path: Path, block: int = 65536) -> str | None:
    h = hashlib.md5()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(block):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _audio_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in AUDIO_EXTENSIONS
        and not is_junk_file(path)
        and not is_inside_junk_dir(path)
    )


def _load_master_hashes(against_db: Path) -> dict[str, list[CompareMatch]]:
    conn = get_connection(against_db)
    rows = conn.execute(
        """
        SELECT id, path, filename, md5, size_bytes
        FROM files
        WHERE md5 IS NOT NULL
        ORDER BY path
        """
    ).fetchall()
    conn.close()
    by_hash: dict[str, list[CompareMatch]] = {}
    for row in rows:
        by_hash.setdefault(row["md5"], []).append(
            CompareMatch(
                file_id=row["id"],
                path=row["path"],
                filename=row["filename"],
                md5=row["md5"],
                size_bytes=row["size_bytes"],
            )
        )
    return by_hash


def build_compare_report(root: Path, against_db: Path = DEFAULT_DB_PATH, *, limit: int = 200) -> CompareReport:
    """Compare a candidate import folder against an existing SQLite index."""
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    root = root.resolve()
    master_hashes = _load_master_hashes(against_db)
    entries: list[CompareEntry] = []
    errors: list[dict] = []
    exact_duplicate_files = 0
    new_files = 0
    hash_errors = 0
    for path in _audio_files(root):
        try:
            stat = path.stat()
        except OSError as e:
            errors.append({"path": str(path), "error": str(e)})
            continue
        digest = _md5(path)
        if digest is None:
            hash_errors += 1
            errors.append({"path": str(path), "error": "could not hash file"})
            continue
        matches = master_hashes.get(digest, [])
        if matches:
            exact_duplicate_files += 1
        else:
            new_files += 1
        entries.append(
            CompareEntry(
                path=str(path),
                filename=path.name,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                md5=digest,
                status="exact_duplicate" if matches else "new",
                exact_matches=matches,
            )
        )
    selected = entries if limit == 0 else entries[:limit]
    return CompareReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        against_db=str(against_db),
        limit=limit,
        summary=CompareSummary(
            files_considered=len(entries) + hash_errors,
            exact_duplicate_files=exact_duplicate_files,
            new_files=new_files,
            hash_errors=hash_errors,
        ),
        entries=selected,
        errors=errors,
    )


def write_compare_report(report: CompareReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_dumps(report), encoding="utf-8")
    if not quiet:
        console.print(f"Compare report written to [cyan]{output_path}[/cyan]")


def build_compare_plan(report_path: Path) -> ComparePlan:
    report = CompareReport.model_validate_json(report_path.read_text())
    entries: list[ComparePlanEntry] = []
    for index, entry in enumerate(report.entries, start=1):
        if entry.status == "exact_duplicate":
            action = "skip_import"
            reason = "candidate file exactly matches indexed file by MD5"
        else:
            action = "review_import"
            reason = "candidate file has no exact MD5 match in the target index"
        entries.append(
            ComparePlanEntry(
                entry_id=index,
                path=entry.path,
                action=action,
                reason=reason,
                exact_matches=entry.exact_matches,
            )
        )
    return ComparePlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        source_report=str(report_path),
        root=report.root,
        against_db=report.against_db,
        summary=ComparePlanSummary(
            candidate_entries=len(entries),
            skip_import_entries=sum(1 for entry in entries if entry.action == "skip_import"),
            review_import_entries=sum(1 for entry in entries if entry.action == "review_import"),
        ),
        entries=entries,
        errors=report.errors,
    )


def write_compare_plan(plan: ComparePlan, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_dumps(plan), encoding="utf-8")
    if not quiet:
        console.print(f"Compare plan written to [cyan]{output_path}[/cyan]")


def show_compare_report(report: CompareReport) -> None:
    table = Table(title="Compare report", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Files considered", f"{report.summary.files_considered:,}")
    table.add_row("Exact duplicates", f"{report.summary.exact_duplicate_files:,}")
    table.add_row("New files", f"{report.summary.new_files:,}")
    table.add_row("Hash errors", f"{report.summary.hash_errors:,}")
    console.print(table)


def show_compare_plan(plan: ComparePlan) -> None:
    table = Table(title="Compare plan", show_lines=False)
    table.add_column("Action")
    table.add_column("Count", justify="right")
    table.add_row("Skip import", f"{plan.summary.skip_import_entries:,}")
    table.add_row("Review import", f"{plan.summary.review_import_entries:,}")
    console.print(table)
