"""UCS catalog + validation models."""

from __future__ import annotations

from pydantic import BaseModel


class UcsEntry(BaseModel):
    cat_short: str
    category: str
    subcategory: str
    cat_id: str
    explanations: str | None = None
    synonyms: list[str] = []


class UcsCatalogProvenance(BaseModel):
    source_url: str
    source_path: str
    source_format: str
    release_version: str | None = None
    imported_at: str
    attribution: str
    entry_count: int


class UcsCatalog(BaseModel):
    schema_version: int = 1
    tool: str = "sfxworkbench"
    tool_version: str
    provenance: UcsCatalogProvenance
    entries: list[UcsEntry] = []


class UcsImportResult(BaseModel):
    catalog_path: str
    source_path: str
    source_format: str
    release_version: str | None = None
    entry_count: int = 0
    unique_cat_shorts: int = 0
    unique_categories: int = 0
    skipped_rows: int = 0


class UcsCategoriesQuery(BaseModel):
    category: str | None = None
    cat_short: str | None = None
    total_loaded: int = 0
    matched: int = 0
    entries: list[UcsEntry] = []


class UcsValidationIssue(BaseModel):
    file_id: int
    path: str
    filename: str
    cat_short: str | None = None
    subcategory: str | None = None
    reason: str


class UcsValidationSummary(BaseModel):
    files_considered: int = 0
    ucs_looking: int = 0
    catalog_matches: int = 0
    catalog_misses: int = 0
    non_ucs: int = 0
    by_miss_reason: dict[str, int] = {}


class UcsValidationReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str | None = None
    db_path: str
    catalog_path: str
    catalog_release_version: str | None = None
    limit: int = 200
    summary: UcsValidationSummary
    issues: list[UcsValidationIssue] = []
