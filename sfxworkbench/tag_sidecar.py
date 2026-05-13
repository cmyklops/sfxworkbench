"""JSON sidecar export/import for DB-only accepted tags."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection
from sfxworkbench.models import TagSidecarEntry, TagSidecarImportResult, TagSidecarReport, TagSidecarTag
from sfxworkbench.utils import atomic_write_json

console = Console()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _md5(path: Path, block: int = 65536) -> str | None:
    h = hashlib.md5()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(block):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _decode_evidence(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def build_tag_sidecar_report(
    db_path: Path = DEFAULT_DB_PATH,
    root: Path | None = None,
    limit: int = 0,
) -> TagSidecarReport:
    """Build a JSON sidecar payload from accepted DB-only tags."""
    if limit < 0:
        raise ValueError("limit must be 0 or greater")
    resolved_root = root.expanduser().resolve() if root is not None else None
    if resolved_root is not None and not resolved_root.exists():
        raise ValueError(f"path not found: {resolved_root}")

    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT f.id AS file_id, f.path, f.filename, f.size_bytes, f.mtime, f.md5,
               t.field, t.value, t.source, t.method, t.confidence, t.evidence
        FROM accepted_tags t
        JOIN files f ON f.id = t.file_id
        ORDER BY f.path, t.field, t.value, t.source
        """
    ).fetchall()
    conn.close()
    if resolved_root is not None:
        rows = [
            row
            for row in rows
            if Path(row["path"]) == resolved_root or _is_relative_to(Path(row["path"]), resolved_root)
        ]

    entries_by_path: dict[str, TagSidecarEntry] = {}
    for row in rows:
        entry = entries_by_path.setdefault(
            row["path"],
            TagSidecarEntry(
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                md5=row["md5"],
            ),
        )
        entry.tags.append(
            TagSidecarTag(
                field=row["field"],
                value=row["value"],
                source=row["source"],
                method=row["method"],
                confidence=row["confidence"],
                evidence=_decode_evidence(row["evidence"]),
            )
        )

    entries = list(entries_by_path.values())
    reported_entries = entries if limit == 0 else entries[:limit]
    return TagSidecarReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(resolved_root) if resolved_root is not None else None,
        db_path=str(db_path),
        entry_count=len(reported_entries),
        tag_count=sum(len(entry.tags) for entry in reported_entries),
        entries=reported_entries,
    )


def write_tag_sidecar_report(report: TagSidecarReport, output_path: Path, quiet: bool = False) -> None:
    atomic_write_json(output_path, report)
    if not quiet:
        console.print(f"Tag sidecar written to [cyan]{output_path}[/cyan]")


def load_tag_sidecar_report(sidecar_path: Path) -> TagSidecarReport:
    return TagSidecarReport.model_validate(json.loads(sidecar_path.read_text()))


def _validate_sidecar_entry(row, entry: TagSidecarEntry) -> str | None:
    if row is None:
        return "indexed file row is missing"
    if entry.size_bytes is not None and row["size_bytes"] != entry.size_bytes:
        return f"size changed: expected {entry.size_bytes}, got {row['size_bytes']}"
    if entry.mtime is not None and row["mtime"] != entry.mtime:
        return "mtime changed"
    if entry.md5 is not None and row["md5"] != entry.md5:
        return "md5 changed"
    path = Path(entry.path)
    if not path.exists():
        return "file does not exist"
    try:
        stat = path.stat()
    except OSError as e:
        return str(e)
    if entry.size_bytes is not None and stat.st_size != entry.size_bytes:
        return f"file size changed: expected {entry.size_bytes}, got {stat.st_size}"
    if entry.mtime is not None and stat.st_mtime != entry.mtime:
        return "file mtime changed"
    if entry.md5 is not None and len(entry.md5) == 32:
        current_md5 = _md5(path)
        if current_md5 != entry.md5:
            return "file md5 changed"
    return None


def import_tag_sidecar(
    sidecar_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    dry_run: bool = True,
    quiet: bool = False,
) -> TagSidecarImportResult:
    """Import accepted tags from a JSON sidecar into SQLite."""
    report = load_tag_sidecar_report(sidecar_path)
    result = TagSidecarImportResult(
        planned=sum(len(entry.tags) for entry in report.entries),
        dry_run=dry_run,
    )
    conn = get_connection(db_path)
    now = _now_iso()
    for entry in report.entries:
        row = conn.execute(
            "SELECT id, path, size_bytes, mtime, md5 FROM files WHERE path = ?",
            (entry.path,),
        ).fetchone()
        validation_error = _validate_sidecar_entry(row, entry)
        if validation_error is not None:
            result.errors.append({"path": entry.path, "error": validation_error})
            continue
        assert row is not None
        for tag in entry.tags:
            existing = conn.execute(
                "SELECT 1 FROM accepted_tags WHERE file_id = ? AND field = ? AND value = ?",
                (row["id"], tag.field, tag.value),
            ).fetchone()
            if existing is not None:
                result.skipped += 1
                continue
            if dry_run:
                result.imported += 1
                continue
            conn.execute(
                """
                INSERT INTO accepted_tags (
                    file_id, field, value, source, method, confidence,
                    evidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    tag.field,
                    tag.value,
                    tag.source,
                    tag.method,
                    tag.confidence,
                    json.dumps(tag.evidence),
                    now,
                    now,
                ),
            )
            result.imported += 1
    if not dry_run:
        conn.commit()
    conn.close()
    if not quiet:
        show_tag_sidecar_import_result(result)
    return result


def show_tag_sidecar_report(report: TagSidecarReport) -> None:
    table = Table(title="Tag sidecar", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Files with tags", f"{report.entry_count:,}")
    table.add_row("Tags", f"{report.tag_count:,}")
    console.print(table)


def show_tag_sidecar_import_result(result: TagSidecarImportResult) -> None:
    table = Table(title="Tag sidecar import", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Imported", f"{result.imported:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)
