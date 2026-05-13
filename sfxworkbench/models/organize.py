"""Organize audit + nesting plan models."""

from __future__ import annotations

from pydantic import BaseModel


class OrganizeEntry(BaseModel):
    old_path: str
    new_path: str
    old_name: str
    new_name: str
    action: str = "rename"
    reason: str = "strip_leading_number"


class OrganizeAuditSummary(BaseModel):
    directories_scanned: int = 0
    planned: int = 0
    candidates: int = 0
    errors: int = 0


class NestingCandidate(BaseModel):
    path: str
    name: str
    kind: str
    suggested_action: str
    reason: str
    depth: int
    parent_path: str | None = None
    target_path: str | None = None
    child_dirs: int = 0
    direct_files: int = 0
    audio_files: int = 0
    confidence: str = "medium"


class OrganizeAuditReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    pattern: str
    depth: int = 1
    summary: OrganizeAuditSummary
    entries: list[OrganizeEntry] = []
    candidates: list[NestingCandidate] = []
    errors: list[dict] = []


class OrganizeReviewResult(BaseModel):
    report_path: str
    output_path: str
    total_entries: int = 0
    approved_entries: int = 0
    invalid_entries: list[int] = []


class NestingMove(BaseModel):
    old_path: str
    new_path: str
    path_type: str


class NestingPlanEntry(BaseModel):
    source_path: str
    target_path: str
    kind: str = "repeated_folder_name"
    action: str = "flatten_child_into_parent"
    reason: str = "folder name repeats its parent"
    audio_files: int = 0
    moves: list[NestingMove] = []


class NestingPlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    source_report: str | None = None
    entries: list[NestingPlanEntry] = []
    errors: list[dict] = []


class NestingApplyResult(BaseModel):
    planned: int = 0
    flattened: int = 0
    moved: int = 0
    undone: int = 0
    errors: list[dict] = []
    log_path: str | None = None
    dry_run: bool = True
