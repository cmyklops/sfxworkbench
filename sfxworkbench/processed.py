"""Report-only processed/rendered file pattern detection."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection, path_scope_filter, path_scope_params
from sfxworkbench.models import ProcessedFileEntry, ProcessedFileReport, ProcessedFileSummary
from sfxworkbench.utils import atomic_write_json

console = Console()

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PROCESSED_TOKENS = {
    "audiosuite",
    "bounce",
    "bounced",
    "clean",
    "cleaned",
    "comp",
    "compressed",
    "denoise",
    "denoised",
    "eq",
    "limited",
    "limiter",
    "norm",
    "normalized",
    "pitch",
    "pitched",
    "processed",
    "render",
    "rendered",
    "reverb",
    "stretched",
    "stretch",
    "varispeed",
    "wet",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _base_key(stem: str, processed_tokens: set[str]) -> str:
    tokens = [token for token in _tokens(stem) if token not in processed_tokens and not token.isdigit()]
    return " ".join(tokens)


def _load_rows(root: Path, db_path: Path):
    conn = get_connection(db_path)
    rows = conn.execute(
        f"""
        SELECT id, path, filename, stem, size_bytes, mtime, md5
        FROM files
        WHERE {path_scope_filter()}
          AND scan_error IS NULL
        ORDER BY path
        """,
        path_scope_params(root),
    ).fetchall()
    conn.close()
    return rows


def build_processed_file_report(
    root: Path, db_path: Path = DEFAULT_DB_PATH, *, limit: int = 200
) -> ProcessedFileReport:
    """Detect likely rendered/processed variants. No files are changed."""
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    root = root.resolve()
    rows = _load_rows(root, db_path)
    source_by_parent_key: dict[tuple[str, str], str] = {}
    row_tokens: dict[int, set[str]] = {}
    for row in rows:
        tokens = set(_tokens(row["stem"] or Path(row["path"]).stem))
        row_tokens[row["id"]] = tokens
        if tokens & _PROCESSED_TOKENS:
            continue
        key = _base_key(row["stem"] or Path(row["path"]).stem, _PROCESSED_TOKENS)
        if key:
            source_by_parent_key[(str(Path(row["path"]).parent), key)] = row["path"]

    entries: list[ProcessedFileEntry] = []
    grouped = 0
    for row in rows:
        tokens = row_tokens[row["id"]]
        processed_tokens = sorted(tokens & _PROCESSED_TOKENS)
        if not processed_tokens:
            continue
        key = _base_key(row["stem"] or Path(row["path"]).stem, _PROCESSED_TOKENS)
        likely_source = source_by_parent_key.get((str(Path(row["path"]).parent), key))
        if likely_source:
            grouped += 1
        entries.append(
            ProcessedFileEntry(
                path=row["path"],
                filename=row["filename"],
                stem=row["stem"] or Path(row["path"]).stem,
                processed_tokens=processed_tokens,
                likely_source_path=likely_source,
                confidence="high" if likely_source else "review",
                evidence=[f"processed_tokens:{','.join(processed_tokens)}"]
                + ([f"likely_source:{likely_source}"] if likely_source else []),
            )
        )
    selected = entries if limit == 0 else entries[:limit]
    return ProcessedFileReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        db_path=str(db_path),
        limit=limit,
        summary=ProcessedFileSummary(
            files_considered=len(rows),
            candidates=len(entries),
            grouped_with_source=grouped,
        ),
        entries=selected,
    )


def write_processed_file_report(report: ProcessedFileReport, output_path: Path, quiet: bool = False) -> None:
    atomic_write_json(output_path, report)
    if not quiet:
        console.print(f"Processed-file report written to [cyan]{output_path}[/cyan]")


def show_processed_file_report(report: ProcessedFileReport) -> None:
    table = Table(title="Processed-file report", show_lines=False)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Files considered", f"{report.summary.files_considered:,}")
    table.add_row("Candidates", f"{report.summary.candidates:,}")
    table.add_row("Grouped with source", f"{report.summary.grouped_with_source:,}")
    console.print(table)
