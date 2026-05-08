"""Reviewed dry-run plans for future embedded metadata writes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH, get_connection
from wavwarden.metadata_backends import build_metadata_backends_report
from wavwarden.models import (
    MetadataWriteCommand,
    MetadataWritePlan,
    MetadataWritePlanEntry,
    MetadataWritePlanSummary,
    MetadataWritePreviewResult,
    MetadataWriteReviewResult,
)
from wavwarden.utils import json_dumps

console = Console()

PLAN_SCHEMA_VERSION = 1
_VALID_REVIEW_STATES = {"approved", "rejected", "pending"}

# Conservative first-pass mapping. These are the only accepted tag fields this
# slice is willing to route toward BWF MetaEdit. Everything else remains visible
# in the plan as unsupported rather than disappearing.
BWF_METAEDIT_FIELD_MAP = {
    "description": ("bext", "Description"),
    "originator": ("bext", "Originator"),
    "originator_reference": ("bext", "OriginatorReference"),
}
BWF_METAEDIT_COMMAND_FIELDS = {
    "Description": "description",
    "Originator": "originator",
    "OriginatorReference": "originatorreference",
}
BWF_METAEDIT_FIELD_LIMITS = {
    "Description": 256,
    "Originator": 32,
    "OriginatorReference": 32,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_plan_path() -> Path:
    return Path(f"metadata_write_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


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


def _summarize_plan(plan: MetadataWritePlan) -> MetadataWritePlanSummary:
    file_ids = {entry.file_id for entry in plan.entries}
    return MetadataWritePlanSummary(
        files_considered=len(file_ids),
        accepted_tags_considered=len(plan.entries),
        candidate_entries=len(plan.entries),
        supported_entries=sum(1 for entry in plan.entries if entry.supported),
        unsupported_entries=sum(1 for entry in plan.entries if not entry.supported),
        approved_entries=sum(1 for entry in plan.entries if entry.review_status == "approved"),
        rejected_entries=sum(1 for entry in plan.entries if entry.review_status == "rejected"),
        backend_available=plan.backend.available,
    )


def _target_for_field(field: str, backend: str) -> tuple[str | None, str | None, str, bool]:
    if backend != "bwfmetaedit":
        return None, None, "unsupported_backend", False
    target = BWF_METAEDIT_FIELD_MAP.get(field)
    if target is None:
        return None, None, "unsupported_field", False
    return target[0], target[1], "write_bext", True


def _validate_bwf_value(entry: MetadataWritePlanEntry) -> str | None:
    if entry.target_namespace != "bext" or entry.target_key is None:
        return None
    encoded = entry.value.encode("ascii", errors="ignore")
    if encoded.decode("ascii") != entry.value:
        return f"{entry.target_key} must be ASCII for BWF MetaEdit/BEXT"
    max_bytes = BWF_METAEDIT_FIELD_LIMITS.get(entry.target_key)
    if max_bytes is not None and len(encoded) > max_bytes:
        return f"{entry.target_key} exceeds {max_bytes} ASCII bytes"
    return None


def _base_bwfmetaedit_command(plan: MetadataWritePlan) -> list[str]:
    executable = plan.backend.executable or plan.backend.name
    return [executable, "--simulate", "--reject-overwrite", "--specialchars"]


def render_bwfmetaedit_commands(
    entries: list[MetadataWritePlanEntry], plan: MetadataWritePlan
) -> list[MetadataWriteCommand]:
    """Render simulated BWF MetaEdit commands grouped per target file."""
    grouped: dict[int, list[MetadataWritePlanEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.file_id, []).append(entry)

    commands: list[MetadataWriteCommand] = []
    for file_id in sorted(grouped):
        file_entries = grouped[file_id]
        fields: dict[str, str] = {}
        command = _base_bwfmetaedit_command(plan)
        for entry in sorted(file_entries, key=lambda item: (item.target_key or "", item.entry_id)):
            if entry.target_key is None:
                continue
            command_field = BWF_METAEDIT_COMMAND_FIELDS.get(entry.target_key)
            if command_field is None:
                continue
            fields[entry.target_key] = entry.value
            command.append(f"--{command_field}={entry.value}")
        command.append(file_entries[0].path)
        commands.append(
            MetadataWriteCommand(
                file_id=file_id,
                path=file_entries[0].path,
                command=command,
                fields=fields,
            )
        )
    return commands


def build_metadata_write_plan(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    root: Path | None = None,
    backend: str = "bwfmetaedit",
    bwfmetaedit: str | Path | None = None,
    limit: int = 0,
) -> MetadataWritePlan:
    """Build a reviewed dry-run embedded metadata write plan from accepted tags."""
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    if backend != "bwfmetaedit":
        raise ValueError("Only backend='bwfmetaedit' is supported in this metadata-writing slice")
    resolved_root = root.expanduser().resolve() if root is not None else None
    if resolved_root is not None and not resolved_root.exists():
        raise ValueError(f"path not found: {resolved_root}")

    backend_report = build_metadata_backends_report(bwfmetaedit=bwfmetaedit)
    backend_info = backend_report.backends[0]
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
    if limit:
        rows = rows[:limit]

    entries: list[MetadataWritePlanEntry] = []
    for entry_id, row in enumerate(rows, start=1):
        target_namespace, target_key, action, supported = _target_for_field(row["field"], backend)
        entries.append(
            MetadataWritePlanEntry(
                entry_id=entry_id,
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                md5=row["md5"],
                field=row["field"],
                value=row["value"],
                source=row["source"],
                method=row["method"],
                confidence=row["confidence"],
                evidence=_decode_evidence(row["evidence"]),
                backend=backend,
                target_namespace=target_namespace,
                target_key=target_key,
                action=action,
                supported=supported,
            )
        )

    plan = MetadataWritePlan(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(resolved_root) if resolved_root is not None else None,
        db_path=str(db_path),
        backend=backend_info,
        summary=MetadataWritePlanSummary(),
        entries=entries,
    )
    plan.summary = _summarize_plan(plan)
    return plan


def write_metadata_write_plan(
    plan: MetadataWritePlan,
    output_path: Path | None = None,
    quiet: bool = False,
) -> Path:
    output = output_path or _default_plan_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json_dumps(plan), encoding="utf-8")
    if not quiet:
        console.print(f"Metadata write plan written to [cyan]{output}[/cyan]")
    return output


def load_metadata_write_plan(plan_path: Path) -> MetadataWritePlan:
    return MetadataWritePlan.model_validate(json.loads(plan_path.read_text()))


def review_metadata_write_plan(
    plan_path: Path,
    output_path: Path | None = None,
    approve_all: bool = False,
    entries: list[int] | None = None,
    reject_entries: list[int] | None = None,
    quiet: bool = False,
) -> MetadataWriteReviewResult:
    """Mark selected embedded-write plan entries as approved or rejected."""
    plan = load_metadata_write_plan(plan_path)
    by_id = {entry.entry_id: entry for entry in plan.entries}
    requested_approve = set(entries or [])
    requested_reject = set(reject_entries or [])
    invalid = sorted((requested_approve | requested_reject) - set(by_id))
    if approve_all:
        requested_approve.update(by_id)
    for entry_id in sorted(requested_approve - set(invalid)):
        by_id[entry_id].review_status = "approved"
    for entry_id in sorted(requested_reject - set(invalid)):
        by_id[entry_id].review_status = "rejected"
    plan.summary = _summarize_plan(plan)

    output = output_path or plan_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json_dumps(plan), encoding="utf-8")
    result = MetadataWriteReviewResult(
        plan_path=str(plan_path),
        output_path=str(output),
        total_entries=len(plan.entries),
        approved_entries=plan.summary.approved_entries,
        rejected_entries=plan.summary.rejected_entries,
        invalid_entries=invalid,
    )
    if not quiet:
        console.print(
            f"Approved [yellow]{result.approved_entries:,}[/yellow] and rejected "
            f"[yellow]{result.rejected_entries:,}[/yellow] of "
            f"[yellow]{result.total_entries:,}[/yellow] embedded metadata write entrie(s)."
        )
        if invalid:
            console.print(f"[red]Ignored invalid entry number(s): {', '.join(str(i) for i in invalid)}[/red]")
    return result


def _validate_plan_entry(conn, entry: MetadataWritePlanEntry) -> str | None:
    row = conn.execute(
        "SELECT path, size_bytes, mtime, md5 FROM files WHERE id = ?",
        (entry.file_id,),
    ).fetchone()
    if row is None:
        return "indexed file row is missing"
    if row["path"] != entry.path:
        return f"path changed: expected {entry.path}, got {row['path']}"
    if entry.size_bytes is not None and row["size_bytes"] != entry.size_bytes:
        return f"size changed: expected {entry.size_bytes}, got {row['size_bytes']}"
    if entry.mtime is not None and row["mtime"] != entry.mtime:
        return "mtime changed"
    if entry.md5 is not None and row["md5"] != entry.md5:
        return "md5 changed"
    if not Path(entry.path).exists():
        return "file does not exist"
    return None


def preview_metadata_write_plan(
    plan_path: Path,
    db_path: Path | None = None,
    require_reviewed: bool = False,
    quiet: bool = False,
) -> MetadataWritePreviewResult:
    """Validate a reviewed embedded metadata write plan without mutating audio."""
    plan = load_metadata_write_plan(plan_path)
    effective_db = db_path or Path(plan.db_path)
    result = MetadataWritePreviewResult(planned=len(plan.entries), target=plan.target)
    if plan.target != "embedded_metadata":
        result.errors.append({"path": str(plan_path), "error": f"unsupported metadata target: {plan.target}"})
        return result
    if not plan.backend.available:
        result.errors.append({"path": str(plan_path), "error": f"backend unavailable: {plan.backend.name}"})
        return result
    approved_entries = [entry for entry in plan.entries if entry.review_status == "approved"]
    if require_reviewed and not approved_entries:
        result.errors.append({"path": str(plan_path), "error": "plan has no approved entries"})
        return result

    conn = get_connection(effective_db)
    renderable_entries: list[MetadataWritePlanEntry] = []
    for entry in plan.entries:
        if require_reviewed and entry.review_status != "approved":
            result.skipped += 1
            continue
        if entry.review_status == "rejected":
            result.skipped += 1
            continue
        if entry.review_status not in _VALID_REVIEW_STATES:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": "invalid review status"})
            continue
        if not entry.supported:
            result.skipped += 1
            continue
        value_error = _validate_bwf_value(entry)
        if value_error is not None:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": value_error})
            continue
        validation_error = _validate_plan_entry(conn, entry)
        if validation_error is not None:
            result.errors.append({"entry_id": entry.entry_id, "path": entry.path, "error": validation_error})
            continue
        result.would_write += 1
        renderable_entries.append(entry)
    result.commands = render_bwfmetaedit_commands(renderable_entries, plan)
    conn.close()
    if not quiet:
        show_metadata_write_preview_result(result)
    return result


def show_metadata_write_plan(plan: MetadataWritePlan) -> None:
    table = Table(title="Embedded metadata write plan", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Backend", plan.backend.display_name)
    table.add_row("Backend available", str(plan.backend.available))
    table.add_row("Candidate entries", f"{plan.summary.candidate_entries:,}")
    table.add_row("Supported entries", f"{plan.summary.supported_entries:,}")
    table.add_row("Unsupported entries", f"{plan.summary.unsupported_entries:,}")
    table.add_row("Approved entries", f"{plan.summary.approved_entries:,}")
    console.print(table)


def show_metadata_write_preview_result(result: MetadataWritePreviewResult) -> None:
    table = Table(title="Embedded metadata write preview", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Dry run", str(result.dry_run))
    table.add_row("Planned", f"{result.planned:,}")
    table.add_row("Would write", f"{result.would_write:,}")
    table.add_row("Skipped", f"{result.skipped:,}")
    table.add_row("Errors", f"{len(result.errors):,}")
    console.print(table)
