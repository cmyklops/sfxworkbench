"""Dual-mono detection, plan, review, and apply-result models."""

from __future__ import annotations

from pydantic import BaseModel


class DualMonoEntry(BaseModel):
    group_id: int
    file_id: int | None = None
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    duration_s: float | None = None
    channels: int | None = None
    left_md5: str | None = None
    right_md5: str | None = None
    max_abs_difference: float | None = None
    rms_difference: float | None = None
    confidence: str = "review"
    evidence: list[str] = []


class DualMonoSummary(BaseModel):
    files_considered: int = 0
    candidates: int = 0
    exact: int = 0
    near_exact: int = 0
    review: int = 0


class DualMonoReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    limit: int = 200
    summary: DualMonoSummary
    entries: list[DualMonoEntry] = []
    errors: list[dict] = []


class DualMonoPlanEntry(BaseModel):
    group_id: int
    path: str
    output_relative_path: str
    output_format: str = "wav"
    target_channels: int = 1
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    confidence: str = "review"
    review_status: str = "pending"


class DualMonoPlanSummary(BaseModel):
    candidate_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0


class DualMonoPlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    source_report: str
    root: str
    db_path: str
    safe_folders: list[str] = []
    summary: DualMonoPlanSummary
    entries: list[DualMonoPlanEntry] = []
    errors: list[dict] = []


class DualMonoReviewResult(BaseModel):
    plan_path: str
    output_path: str
    total_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0
    invalid_entries: list[int] = []


class DualMonoApplyResult(BaseModel):
    planned: int = 0
    written: int = 0
    skipped: int = 0
    bytes_written: int = 0
    output_root: str | None = None
    log_path: str | None = None
    errors: list[dict] = []
    dry_run: bool = True
