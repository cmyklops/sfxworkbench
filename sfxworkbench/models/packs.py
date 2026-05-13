"""Pack audit, plan, review, and apply-result models."""

from __future__ import annotations

from pydantic import BaseModel


class PackFolderSummary(BaseModel):
    path: str
    file_count: int = 0
    total_bytes: int = 0
    unique_hashes: int = 0


class PackExactGroup(BaseModel):
    group_id: int
    file_count: int = 0
    total_bytes: int = 0
    same_relative_paths: bool = False
    folders: list[PackFolderSummary] = []


class PackOverlapCandidate(BaseModel):
    group_id: int
    folder_a: PackFolderSummary
    folder_b: PackFolderSummary
    shared_files: int = 0
    shared_bytes: int = 0
    smaller_folder_coverage: float = 0.0
    larger_folder_coverage: float = 0.0
    unique_files_a: int = 0
    unique_files_b: int = 0
    classification: str = "overlap"


class PackAuditSummary(BaseModel):
    folders_analyzed: int = 0
    exact_duplicate_groups: int = 0
    exact_duplicate_folders: int = 0
    overlap_candidates: int = 0
    indexed_files_considered: int = 0
    files_without_hash: int = 0


class PackAuditReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    min_files: int = 2
    overlap_threshold: float = 0.95
    summary: PackAuditSummary
    exact_groups: list[PackExactGroup] = []
    overlap_candidates: list[PackOverlapCandidate] = []


class PackPlanFile(BaseModel):
    path: str
    relative_path: str
    hash: str | None = None
    size_bytes: int | None = None


class PackPlanEntry(BaseModel):
    source_type: str
    source_group_id: int
    folder_path: str
    keep_folder_path: str
    action: str = "quarantine_folder"
    reason: str
    file_count: int = 0
    total_bytes: int = 0
    shared_files: int | None = None
    shared_bytes: int | None = None
    smaller_folder_coverage: float | None = None
    larger_folder_coverage: float | None = None
    files: list[PackPlanFile] = []
    quarantine_path: str | None = None
    protected_by: str | None = None
    keep_protected_by: str | None = None
    preservation_evidence: list[dict] = []
    keep_preservation_evidence: list[dict] = []


class PackPlanSummary(BaseModel):
    candidate_entries: int = 0
    quarantine_entries: int = 0
    review_entries: int = 0
    ignored_entries: int = 0
    protected_entries: int = 0
    planned_files: int = 0
    planned_bytes: int = 0


class PackPlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    source_report: str | None = None
    safe_folders: list[str] = []
    preservation_priority: dict = {}
    summary: PackPlanSummary
    entries: list[PackPlanEntry] = []
    errors: list[dict] = []


class PackReviewResult(BaseModel):
    plan_path: str
    output_path: str
    total_groups: int = 0
    approved_groups: int = 0
    invalid_groups: list[int] = []


class PackApplyResult(BaseModel):
    planned: int = 0
    quarantined: int = 0
    restored: int = 0
    files_moved: int = 0
    bytes_quarantined: int = 0
    errors: list[dict] = []
    quarantine_dir: str | None = None
    log_path: str | None = None
    dry_run: bool = True
