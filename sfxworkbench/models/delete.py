"""Delete-plan, review-result, and apply-result models."""

from __future__ import annotations

from pydantic import BaseModel


class DeletePlanEntry(BaseModel):
    entry_id: int
    path: str
    path_type: str = "file"
    size_bytes: int | None = None
    md5: str | None = None
    source_log: str
    source_path: str | None = None
    review_status: str = "pending"


class DeletePlanSummary(BaseModel):
    candidate_entries: int = 0
    file_entries: int = 0
    directory_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0
    bytes_planned: int = 0


class DeletePlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    source_log: str
    safe_folders: list[str] = []
    summary: DeletePlanSummary
    entries: list[DeletePlanEntry] = []
    errors: list[dict] = []


class DeleteReviewResult(BaseModel):
    plan_path: str
    output_path: str
    total_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0
    invalid_entries: list[int] = []


class DeleteApplyResult(BaseModel):
    planned: int = 0
    deleted: int = 0
    skipped: int = 0
    bytes_deleted: int = 0
    log_path: str | None = None
    errors: list[dict] = []
    dry_run: bool = True
