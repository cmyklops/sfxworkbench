"""Processed-file detection models."""

from __future__ import annotations

from pydantic import BaseModel


class ProcessedFileEntry(BaseModel):
    path: str
    filename: str
    stem: str
    processed_tokens: list[str] = []
    likely_source_path: str | None = None
    confidence: str = "review"
    evidence: list[str] = []


class ProcessedFileSummary(BaseModel):
    files_considered: int = 0
    candidates: int = 0
    grouped_with_source: int = 0


class ProcessedFileReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str | None = None
    limit: int = 200
    summary: ProcessedFileSummary
    entries: list[ProcessedFileEntry] = []
