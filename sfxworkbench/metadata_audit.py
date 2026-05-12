"""Report-only metadata and sample-rate audit helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.audit_cmd import _STANDARD_SAMPLE_RATES
from sfxworkbench.db import get_connection
from sfxworkbench.models import MetadataAuditEntry, MetadataAuditReport, MetadataAuditSummary

console = Console()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_sources(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


def _entry_from_row(row, reasons: list[str]) -> MetadataAuditEntry:
    return MetadataAuditEntry(
        path=row["path"],
        filename=row["filename"],
        sample_rate=row["sample_rate"],
        bit_depth=row["bit_depth"],
        channels=row["channels"],
        duration_s=row["duration_s"],
        has_bext=bool(row["has_bext"]),
        has_ixml=bool(row["has_ixml"]),
        has_riff_info=bool(row["has_riff_info"]),
        has_adm=bool(row["has_adm"]),
        has_cue_markers=bool(row["has_cue_markers"]),
        has_sampler=bool(row["has_sampler"]),
        metadata_sources=_parse_sources(row["metadata_sources"]),
        reasons=reasons,
    )


def _limit_clause(limit: int) -> tuple[str, tuple[int, ...]]:
    if limit == 0:
        return "", ()
    return " LIMIT ?", (limit,)


def build_metadata_audit_report(db_path: Path, limit: int = 200) -> MetadataAuditReport:
    """Build a report for files missing BWF/iXML metadata or using unusual sample rates."""
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")

    conn = get_connection(db_path)
    standard_rates = sorted(_STANDARD_SAMPLE_RATES)
    placeholders = ",".join("?" for _ in standard_rates)

    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    missing_metadata_count = conn.execute("SELECT COUNT(*) FROM files WHERE has_bext = 0 AND has_ixml = 0").fetchone()[
        0
    ]
    unusual_sample_rate_count = conn.execute(
        f"SELECT COUNT(*) FROM files WHERE sample_rate IS NOT NULL AND sample_rate NOT IN ({placeholders})",
        tuple(standard_rates),
    ).fetchone()[0]
    sample_rate_rows = conn.execute(
        "SELECT sample_rate, COUNT(*) AS cnt FROM files "
        "WHERE sample_rate IS NOT NULL GROUP BY sample_rate ORDER BY cnt DESC, sample_rate"
    ).fetchall()
    sample_rates = {str(row["sample_rate"]): row["cnt"] for row in sample_rate_rows}

    limit_sql, limit_args = _limit_clause(limit)
    select_columns = """
        SELECT path, filename, sample_rate, bit_depth, channels, duration_s,
               has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
               has_sampler, metadata_sources
        FROM files
    """
    missing_rows = conn.execute(
        select_columns + " WHERE has_bext = 0 AND has_ixml = 0 ORDER BY path" + limit_sql,
        limit_args,
    ).fetchall()
    unusual_rows = conn.execute(
        select_columns
        + f" WHERE sample_rate IS NOT NULL AND sample_rate NOT IN ({placeholders})"
        + " ORDER BY sample_rate, path"
        + limit_sql,
        tuple(standard_rates) + limit_args,
    ).fetchall()
    conn.close()

    missing_entries = [_entry_from_row(row, ["missing_bext_ixml"]) for row in missing_rows]
    unusual_entries = [_entry_from_row(row, ["unusual_sample_rate"]) for row in unusual_rows]

    return MetadataAuditReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        db_path=str(db_path),
        standard_sample_rates=standard_rates,
        limit=limit,
        summary=MetadataAuditSummary(
            total_files=total,
            missing_metadata=missing_metadata_count,
            unusual_sample_rate_files=unusual_sample_rate_count,
            reported_missing_metadata=len(missing_entries),
            reported_unusual_sample_rate_files=len(unusual_entries),
            sample_rates=sample_rates,
        ),
        missing_metadata=missing_entries,
        unusual_sample_rates=unusual_entries,
    )


def write_metadata_audit_report(report: MetadataAuditReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    if not quiet:
        console.print(f"Wrote metadata audit report to [cyan]{output_path}[/cyan]")


def show_metadata_audit_report(report: MetadataAuditReport) -> None:
    summary = report.summary
    table = Table(title="Metadata Audit", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Total indexed files", f"{summary.total_files:,}")
    table.add_row("Missing bext+iXML", f"{summary.missing_metadata:,}")
    table.add_row("Unusual sample-rate files", f"{summary.unusual_sample_rate_files:,}")
    table.add_row("Reported missing metadata rows", f"{summary.reported_missing_metadata:,}")
    table.add_row("Reported unusual sample-rate rows", f"{summary.reported_unusual_sample_rate_files:,}")
    console.print(table)

    if report.unusual_sample_rates:
        rates = Table(title="Unusual Sample Rates", show_lines=False)
        rates.add_column("Sample Rate", justify="right")
        rates.add_column("Filename", style="white")
        for entry in report.unusual_sample_rates[:20]:
            rates.add_row(str(entry.sample_rate), entry.filename)
        console.print(rates)
