"""Tag suggestion, proposal, plan, apply, and sidecar models."""

from __future__ import annotations

from pydantic import BaseModel


class TagSuggestion(BaseModel):
    field: str
    value: str
    source: str
    method: str
    confidence: float
    evidence: list[str] = []


class TagSuggestionEntry(BaseModel):
    file_id: int
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    suggestions: list[TagSuggestion] = []


class TagSuggestionSummary(BaseModel):
    files_considered: int = 0
    files_with_suggestions: int = 0
    total_suggestions: int = 0
    by_source: dict[str, int] = {}
    by_field: dict[str, int] = {}
    by_confidence_bucket: dict[str, int] = {}


class TagSuggestionReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    ucs_catalog_path: str | None = None
    ucs_catalog_release_version: str | None = None
    min_confidence: float = 0.0
    synonym_limit: int = 0
    synonym_depth: int = 0
    sources: list[str] = []
    fields: list[str] = []
    limit: int = 200
    summary: TagSuggestionSummary
    entries: list[TagSuggestionEntry] = []


class TagProposalEvidence(BaseModel):
    source: str
    value: str
    detail: str


class TagProposal(BaseModel):
    category: str
    subcategory: str
    cat_short: str
    cat_id: str
    confidence: float
    strength: str
    action: str = "review"
    evidence: list[TagProposalEvidence] = []
    notes: list[str] = []


class TagProposalEntry(BaseModel):
    file_id: int
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    proposals: list[TagProposal] = []


class TagProposalSummary(BaseModel):
    files_considered: int = 0
    files_with_proposals: int = 0
    total_proposals: int = 0
    by_strength: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_category: dict[str, int] = {}
    top_opening_tokens: list[dict] = []
    top_blocked_tokens: list[dict] = []


class TagProposalReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    catalog_path: str | None = None
    catalog_release_version: str | None = None
    limit: int = 200
    min_confidence: float = 0.0
    summary: TagProposalSummary
    entries: list[TagProposalEntry] = []


class TagPlanEntry(BaseModel):
    entry_id: int
    file_id: int
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    field: str
    action: str = "add"
    existing_values: list[str] = []
    proposed_value: str
    source: str
    method: str
    confidence: float
    evidence: list[str] = []
    review_status: str = "pending"


class TagPlanSummary(BaseModel):
    files_considered: int = 0
    candidate_entries: int = 0
    add_entries: int = 0
    skip_existing_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0


class TagPlanValueSummary(BaseModel):
    field: str
    value: str
    source: str
    count: int = 0
    approved: int = 0
    rejected: int = 0
    pending: int = 0
    confidence_min: float | None = None
    confidence_max: float | None = None
    sample_files: list[str] = []


class TagPlanSummaryReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    plan_path: str
    total_entries: int = 0
    by_field: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_review_status: dict[str, int] = {}
    values: list[TagPlanValueSummary] = []


class TagPlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    action_mode: str = "plan"
    source_report: str | None = None
    target: str = "db"
    min_confidence: float = 0.0
    sources: list[str] = []
    fields: list[str] = []
    limit: int = 200
    summary: TagPlanSummary
    entries: list[TagPlanEntry] = []
    errors: list[dict] = []


class TagReviewResult(BaseModel):
    plan_path: str
    output_path: str
    total_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0
    invalid_entries: list[int] = []


class TagApplyResult(BaseModel):
    planned: int = 0
    applied: int = 0
    skipped: int = 0
    errors: list[dict] = []
    dry_run: bool = True
    target: str = "db"
    log_path: str | None = None
    cancelled: bool = False


class TagSidecarTag(BaseModel):
    field: str
    value: str
    source: str
    method: str | None = None
    confidence: float | None = None
    evidence: list[str] = []


class TagSidecarEntry(BaseModel):
    file_id: int | None = None
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    tags: list[TagSidecarTag] = []


class TagSidecarReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str | None = None
    db_path: str
    entry_count: int = 0
    tag_count: int = 0
    entries: list[TagSidecarEntry] = []


class TagSidecarImportResult(BaseModel):
    planned: int = 0
    imported: int = 0
    skipped: int = 0
    errors: list[dict] = []
    dry_run: bool = True
