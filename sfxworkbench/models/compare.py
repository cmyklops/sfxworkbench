"""Compare audit + plan models."""

from __future__ import annotations

from pydantic import BaseModel


class CompareMatch(BaseModel):
    file_id: int
    path: str
    filename: str
    md5: str | None = None
    size_bytes: int | None = None


class CompareEntry(BaseModel):
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    status: str = "new"
    exact_matches: list[CompareMatch] = []


class CompareSummary(BaseModel):
    files_considered: int = 0
    exact_duplicate_files: int = 0
    new_files: int = 0
    hash_errors: int = 0


class CompareReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    against_db: str
    limit: int = 200
    summary: CompareSummary
    entries: list[CompareEntry] = []
    errors: list[dict] = []


class ComparePlanEntry(BaseModel):
    entry_id: int
    path: str
    action: str = "review_import"
    reason: str
    exact_matches: list[CompareMatch] = []
    review_status: str = "pending"


class ComparePlanSummary(BaseModel):
    candidate_entries: int = 0
    skip_import_entries: int = 0
    review_import_entries: int = 0


class ComparePlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    source_report: str
    root: str
    against_db: str
    summary: ComparePlanSummary
    entries: list[ComparePlanEntry] = []
    errors: list[dict] = []
