"""Validate UCS-looking indexed files against a loaded UCS catalog."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import get_connection
from sfxworkbench.models import UcsValidationIssue, UcsValidationReport, UcsValidationSummary
from sfxworkbench.ucs import normalize_stem, parse_ucs_stem
from sfxworkbench.ucs_catalog import load_catalog, lookup_entry, resolve_catalog_path

console = Console()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_indexed_files(db_path: Path, root: Path | None):
    conn = get_connection(db_path)
    if root is None:
        rows = conn.execute(
            """
            SELECT id, path, filename, stem
            FROM files
            WHERE scan_error IS NULL
            ORDER BY path
            """
        ).fetchall()
    else:
        root = root.resolve()
        rows = conn.execute(
            """
            SELECT id, path, filename, stem
            FROM files
            WHERE (path = ? OR path LIKE ?)
              AND scan_error IS NULL
            ORDER BY path
            """,
            (str(root), str(root) + "/%"),
        ).fetchall()
    conn.close()
    return rows


def build_ucs_validation_report(
    db_path: Path,
    *,
    root: Path | None = None,
    catalog_path: Path | None = None,
    limit: int = 200,
) -> UcsValidationReport:
    """Count UCS-looking indexed filenames that do or do not match the catalog."""
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")

    resolved_catalog_path = resolve_catalog_path(catalog_path)
    catalog = load_catalog(catalog_path)
    if catalog is None or resolved_catalog_path is None:
        raise ValueError("No UCS catalog loaded. Run `sfx ucs import SOURCE` first or pass --catalog.")

    rows = _load_indexed_files(db_path, root)
    issues: list[UcsValidationIssue] = []
    by_miss_reason: dict[str, int] = {}
    ucs_looking = 0
    catalog_matches = 0
    catalog_misses = 0

    for row in rows:
        stem = normalize_stem(row["stem"] or Path(row["path"]).stem)
        parsed = parse_ucs_stem(stem)
        if not parsed.is_ucs:
            continue

        ucs_looking += 1
        entry = lookup_entry(catalog, parsed.category, parsed.subcategory)
        if entry is not None:
            catalog_matches += 1
            continue

        catalog_misses += 1
        reason = "cat_short_subcategory_not_found"
        by_miss_reason[reason] = by_miss_reason.get(reason, 0) + 1
        issues.append(
            UcsValidationIssue(
                file_id=row["id"],
                path=row["path"],
                filename=row["filename"],
                cat_short=parsed.category,
                subcategory=parsed.subcategory,
                reason=reason,
            )
        )

    selected = issues if limit == 0 else issues[:limit]
    summary = UcsValidationSummary(
        files_considered=len(rows),
        ucs_looking=ucs_looking,
        catalog_matches=catalog_matches,
        catalog_misses=catalog_misses,
        non_ucs=len(rows) - ucs_looking,
        by_miss_reason=dict(sorted(by_miss_reason.items())),
    )
    return UcsValidationReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root.resolve()) if root is not None else None,
        db_path=str(db_path),
        catalog_path=str(resolved_catalog_path.resolve()),
        catalog_release_version=catalog.provenance.release_version,
        limit=limit,
        summary=summary,
        issues=selected,
    )


def write_ucs_validation_report(report: UcsValidationReport, output_path: Path, quiet: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    if not quiet:
        console.print(f"UCS validation report written to [cyan]{output_path}[/cyan]")


def show_ucs_validation_report(report: UcsValidationReport) -> None:
    summary = report.summary
    console.print(
        f"Considered [yellow]{summary.files_considered:,}[/yellow] indexed file(s); "
        f"[yellow]{summary.ucs_looking:,}[/yellow] look UCS-shaped, "
        f"[green]{summary.catalog_matches:,}[/green] match the catalog, "
        f"[red]{summary.catalog_misses:,}[/red] miss."
    )

    table = Table(title="UCS validation", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("Non-UCS files", f"{summary.non_ucs:,}")
    table.add_row("UCS-looking files", f"{summary.ucs_looking:,}")
    table.add_row("Catalog matches", f"{summary.catalog_matches:,}")
    table.add_row("Catalog misses", f"{summary.catalog_misses:,}")
    console.print(table)

    if not report.issues:
        return

    issues = Table(title="Sample catalog misses", show_lines=False)
    issues.add_column("File")
    issues.add_column("CatShort")
    issues.add_column("SubCategory")
    issues.add_column("Reason")
    for issue in report.issues[:20]:
        issues.add_row(issue.filename, issue.cat_short or "", issue.subcategory or "", issue.reason)
    console.print(issues)
