"""Scan-error report models."""

from __future__ import annotations

from pydantic import BaseModel


class ScanErrorEntry(BaseModel):
    path: str
    action: str = "review"
    classification: str
    scan_error: str
    size_bytes: int | None = None
    hash: str | None = None


class ScanErrorPlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    db_path: str
    root: str | None = None
    entries: list[ScanErrorEntry]


class ScanErrorApplyResult(BaseModel):
    planned: int = 0
    quarantined: int = 0
    bytes_quarantined: int = 0
    skipped: int = 0
    errors: list[dict] = []
    quarantine_dir: str | None = None
    dry_run: bool = True
