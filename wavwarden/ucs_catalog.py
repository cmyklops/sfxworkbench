"""Universal Category System catalog import, cache, and lookup.

This module reads the official Universal Category System (UCS) catalog as
distributed by ``UCS Release.zip`` on universalcategorysystem.com. The current
slice supports the Soundminer-flavored ``_categorylist.csv`` layout and writes
a normalized JSON cache. XLSX import is intentionally deferred until a clear
need outweighs the extra dependency.

Discovery chain for ``load_catalog()``:

1. Explicit ``path`` argument
2. ``WAVWARDEN_UCS_DATA`` environment variable
3. ``~/.wavwarden/ucs_catalog.json`` cache file
4. ``None`` — caller falls back to the heuristic UCS parser

Attribution: per ``docs/UCS.md``, the official UCS data is published as a
public-domain initiative. Catalogs imported through this module always carry
``UcsCatalogProvenance`` with a source URL, release version, import timestamp,
and attribution string. Do not redistribute the upstream zip; redistribute the
normalized catalog only with the attribution intact.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH
from wavwarden.models import (
    UcsCatalog,
    UcsCatalogProvenance,
    UcsCategoriesQuery,
    UcsEntry,
    UcsImportResult,
)

console = Console()

OFFICIAL_SOURCE_URL = "https://universalcategorysystem.com/"
OFFICIAL_ATTRIBUTION = (
    "Category data derived from the Universal Category System (UCS), a public "
    "domain initiative. See https://universalcategorysystem.com/."
)
ENV_OVERRIDE = "WAVWARDEN_UCS_DATA"

# CSV column names from ``Soundminer/_categorylist.csv`` in UCS Release v8.2.1.
# The English-language columns sit at the front; the rest are localized
# duplicates we deliberately skip.
_CSV_CATEGORY = "Category"
_CSV_SUBCATEGORY = "SubCategory"
_CSV_CAT_ID = "CatID"
_CSV_CAT_SHORT = "CatShort"
_CSV_EXPLANATIONS = "Explanations"
# Note the trailing space: the official header reads "Synonyms - Comma Separated".
_CSV_SYNONYMS = "Synonyms - Comma Separated"
_REQUIRED_COLUMNS = (
    _CSV_CATEGORY,
    _CSV_SUBCATEGORY,
    _CSV_CAT_ID,
    _CSV_CAT_SHORT,
)

# UTF-8 BOM the official CSV starts with — csv.DictReader respects newlines but
# we strip the BOM ourselves so the first column key is "Category" not
# "﻿Category".
_UTF8_BOM = "﻿"


def default_cache_path() -> Path:
    """Where ``sfx ucs import`` writes the normalized catalog by default."""
    return DEFAULT_DB_PATH.parent / "ucs_catalog.json"


def resolve_catalog_path(path: Path | None = None) -> Path | None:
    """Resolve the catalog discovery chain without reading the catalog."""
    if path is not None:
        return path.expanduser()
    if ENV_OVERRIDE in os.environ and os.environ[ENV_OVERRIDE]:
        return Path(os.environ[ENV_OVERRIDE]).expanduser()
    cache = default_cache_path()
    if cache.exists():
        return cache
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_synonyms(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [item.strip() for item in raw.split(",")]
    return [item for item in parts if item]


def parse_soundminer_csv(
    source_path: Path,
    *,
    release_version: str | None = None,
) -> tuple[UcsCatalog, int]:
    """Parse the Soundminer ``_categorylist.csv`` layout into a normalized catalog.

    Skips rows that lack one of the required columns. Strips the UTF-8 BOM
    when present. Synonyms are split on commas, since the upstream column is a
    quoted comma-joined string inside a single CSV cell.
    """
    text = source_path.read_text(encoding="utf-8-sig")
    if text.startswith(_UTF8_BOM):
        text = text[len(_UTF8_BOM) :]
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError(f"UCS CSV is empty or missing a header: {source_path}")

    fieldnames = [name.lstrip(_UTF8_BOM) for name in reader.fieldnames]
    missing = [col for col in _REQUIRED_COLUMNS if col not in fieldnames]
    if missing:
        raise ValueError(
            f"UCS CSV at {source_path} is missing required columns: {', '.join(missing)}. "
            f"Expected the official Soundminer/_categorylist.csv layout."
        )

    entries: list[UcsEntry] = []
    skipped = 0
    for row in reader:
        cat_short = (row.get(_CSV_CAT_SHORT) or "").strip()
        category = (row.get(_CSV_CATEGORY) or "").strip()
        subcategory = (row.get(_CSV_SUBCATEGORY) or "").strip()
        cat_id = (row.get(_CSV_CAT_ID) or "").strip()
        if not (cat_short and category and subcategory and cat_id):
            skipped += 1
            continue
        entries.append(
            UcsEntry(
                cat_short=cat_short.upper(),
                category=category.upper(),
                subcategory=subcategory.upper(),
                cat_id=cat_id,
                explanations=(row.get(_CSV_EXPLANATIONS) or "").strip() or None,
                synonyms=_split_synonyms(row.get(_CSV_SYNONYMS)),
            )
        )

    provenance = UcsCatalogProvenance(
        source_url=OFFICIAL_SOURCE_URL,
        source_path=str(source_path.resolve()),
        source_format="soundminer_csv",
        release_version=release_version,
        imported_at=_now_iso(),
        attribution=OFFICIAL_ATTRIBUTION,
        entry_count=len(entries),
    )
    catalog = UcsCatalog(
        tool_version=__version__,
        provenance=provenance,
        entries=entries,
    )
    return catalog, skipped


def save_catalog(catalog: UcsCatalog, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog.model_dump(), indent=2), encoding="utf-8")


def load_catalog(path: Path | None = None) -> UcsCatalog | None:
    """Load a normalized UCS catalog, walking the discovery chain.

    Order: explicit ``path`` → ``WAVWARDEN_UCS_DATA`` env var →
    ``default_cache_path()`` → ``None``. Returns ``None`` only when no cache
    exists and no override is set, so callers can fall back gracefully.
    """
    candidate = resolve_catalog_path(path)

    if candidate is None:
        return None
    if not candidate.exists():
        raise FileNotFoundError(f"UCS catalog not found at {candidate}")

    payload = json.loads(candidate.read_text(encoding="utf-8"))
    try:
        return UcsCatalog.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"UCS catalog at {candidate} is malformed: {exc}") from exc


def lookup_entry(catalog: UcsCatalog, cat_short: str | None, subcategory: str | None) -> UcsEntry | None:
    """Return the UCS catalog entry for a filename ``CatShort_SubCategory`` pair."""
    if not cat_short or not subcategory:
        return None
    wanted = (cat_short.strip().upper(), subcategory.strip().upper())
    for entry in catalog.entries:
        if (entry.cat_short, entry.subcategory) == wanted:
            return entry
    return None


# ---------------------------------------------------------------------------
# Import / inspect / query operations used by the CLI
# ---------------------------------------------------------------------------


def import_catalog(
    source_path: Path,
    *,
    output_path: Path | None = None,
    release_version: str | None = None,
) -> tuple[UcsImportResult, UcsCatalog]:
    """Parse a UCS source file and write the normalized JSON cache."""
    if not source_path.exists():
        raise FileNotFoundError(f"UCS source file not found: {source_path}")

    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        catalog, skipped = parse_soundminer_csv(source_path, release_version=release_version)
    elif suffix in {".xlsx", ".xls"}:
        raise NotImplementedError(
            "XLSX import is not implemented in this slice. Convert to CSV first, "
            "or use the Soundminer/_categorylist.csv shipped in UCS Release.zip."
        )
    else:
        raise ValueError(f"Unsupported UCS source format: {suffix}. Expected .csv (Soundminer layout).")

    target = output_path or default_cache_path()
    save_catalog(catalog, target)

    cat_shorts = {entry.cat_short for entry in catalog.entries}
    categories = {entry.category for entry in catalog.entries}

    result = UcsImportResult(
        catalog_path=str(target.resolve()),
        source_path=str(source_path.resolve()),
        source_format=catalog.provenance.source_format,
        release_version=release_version,
        entry_count=len(catalog.entries),
        unique_cat_shorts=len(cat_shorts),
        unique_categories=len(categories),
        skipped_rows=skipped,
    )
    return result, catalog


def query_categories(
    catalog: UcsCatalog,
    *,
    category: str | None = None,
    cat_short: str | None = None,
) -> UcsCategoriesQuery:
    """Filter a loaded catalog by long-form category or short prefix."""
    entries = catalog.entries
    if category is not None:
        wanted = category.strip().upper()
        entries = [e for e in entries if e.category == wanted]
    if cat_short is not None:
        wanted_short = cat_short.strip().upper()
        entries = [e for e in entries if e.cat_short == wanted_short]
    return UcsCategoriesQuery(
        category=category,
        cat_short=cat_short,
        total_loaded=len(catalog.entries),
        matched=len(entries),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# Display helpers (no I/O beyond rich console)
# ---------------------------------------------------------------------------


def show_import_result(result: UcsImportResult, catalog: UcsCatalog) -> None:
    table = Table(title="UCS Import", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Source", result.source_path)
    table.add_row("Source format", result.source_format)
    table.add_row("Release version", result.release_version or "(unspecified)")
    table.add_row("Catalog written to", result.catalog_path)
    table.add_row("Entries", f"{result.entry_count:,}")
    table.add_row("Unique CatShort prefixes", f"{result.unique_cat_shorts:,}")
    table.add_row("Unique long-form categories", f"{result.unique_categories:,}")
    table.add_row("Skipped rows", f"{result.skipped_rows:,}")
    console.print(table)
    console.print(f"[dim]{catalog.provenance.attribution}[/dim]")


def show_catalog_info(catalog: UcsCatalog, source: Path) -> None:
    table = Table(title="UCS Catalog", show_lines=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Loaded from", str(source))
    table.add_row("Source URL", catalog.provenance.source_url)
    table.add_row("Source path", catalog.provenance.source_path)
    table.add_row("Source format", catalog.provenance.source_format)
    table.add_row("Release version", catalog.provenance.release_version or "(unspecified)")
    table.add_row("Imported at", catalog.provenance.imported_at)
    table.add_row("Entries", f"{catalog.provenance.entry_count:,}")
    console.print(table)
    console.print(f"[dim]{catalog.provenance.attribution}[/dim]")


def show_categories_query(query: UcsCategoriesQuery) -> None:
    if query.matched == 0:
        console.print("[yellow]No matching UCS entries.[/yellow]")
        return
    title = f"UCS entries — {query.matched:,} of {query.total_loaded:,}"
    if query.category:
        title += f" • category={query.category}"
    if query.cat_short:
        title += f" • cat_short={query.cat_short}"
    table = Table(title=title, show_lines=False)
    table.add_column("CatShort")
    table.add_column("Category")
    table.add_column("SubCategory")
    table.add_column("CatID")
    for entry in query.entries[:200]:
        table.add_row(entry.cat_short, entry.category, entry.subcategory, entry.cat_id)
    console.print(table)
    if query.matched > 200:
        console.print(f"[dim]Showing first 200 of {query.matched:,}.[/dim]")
