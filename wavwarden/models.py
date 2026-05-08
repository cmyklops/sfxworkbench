"""Pydantic v2 data models for wavwarden.

Models are used for things that cross module boundaries or get serialized
(JSON results, dedupe plans, scan summaries). Internal stats that only
flow CLI-ward stay as plain dicts.
"""

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Audio + filename metadata (passed between modules)
# ---------------------------------------------------------------------------


class AudioInfo(BaseModel):
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    duration_s: float | None = None
    subtype: str | None = None  # e.g. "PCM_24", "FLOAT"
    has_bext: bool = False
    has_ixml: bool = False
    has_riff_info: bool = False
    has_adm: bool = False
    has_cue_markers: bool = False
    has_sampler: bool = False
    metadata_sources: list[str] = []
    error: str | None = None


class FilenameIssue(BaseModel):
    component: str
    issue: str
    detail: str


class UcsParseResult(BaseModel):
    stem: str
    is_ucs: bool = False
    category: str | None = None
    subcategory: str | None = None
    remainder: str | None = None
    source: str = "heuristic"


# ---------------------------------------------------------------------------
# Result types — returned from command modules to the CLI
# ---------------------------------------------------------------------------


class CleanResult(BaseModel):
    removed_files: list[str] = []
    removed_dirs: list[str] = []
    bytes_freed: int = 0
    dry_run: bool = True


class ScanResult(BaseModel):
    total: int = 0
    scanned: int = 0
    skipped: int = 0
    errors: int = 0


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
    tool: str = "wavwarden"
    tool_version: str
    db_path: str
    entries: list[ScanErrorEntry]


class ScanErrorApplyResult(BaseModel):
    planned: int = 0
    quarantined: int = 0
    bytes_quarantined: int = 0
    errors: list[dict] = []
    quarantine_dir: str | None = None
    dry_run: bool = True


class DedupeApplyResult(BaseModel):
    removed: int = 0
    quarantined: int = 0
    bytes_freed: int = 0
    errors: list[dict] = []
    quarantine_dir: str | None = None
    dry_run: bool = True


class AuditResult(BaseModel):
    total_files: int = 0
    scan_errors: int = 0
    missing_metadata: int = 0
    has_bext: int = 0
    has_ixml: int = 0
    ucs_named: int = 0
    unusual_sample_rates: list[dict] = []
    fn_issues_total: int = 0
    fn_issues_by_type: dict[str, int] = {}
    errors: list[dict] = []
    bit_depths: dict[str, int] = {}
    sample_rates: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Dedupe groups
# ---------------------------------------------------------------------------


class DedupeGroup(BaseModel):
    hash: str
    size_bytes: int
    files: list[str]


class DedupeSummary(BaseModel):
    duplicate_groups: int = 0
    duplicate_files: int = 0
    extra_copies: int = 0
    wasted_bytes: int = 0
    largest_group_bytes: int = 0
    largest_group_copies: int = 0


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
    tool: str = "wavwarden"
    tool_version: str
    root: str
    db_path: str
    min_files: int = 2
    overlap_threshold: float = 0.95
    summary: PackAuditSummary
    exact_groups: list[PackExactGroup] = []
    overlap_candidates: list[PackOverlapCandidate] = []


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
    errors: int = 0


class OrganizeAuditReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "wavwarden"
    tool_version: str
    root: str
    pattern: str
    depth: int = 1
    summary: OrganizeAuditSummary
    entries: list[OrganizeEntry] = []
    errors: list[dict] = []


class OrganizeReviewResult(BaseModel):
    report_path: str
    output_path: str
    total_entries: int = 0
    approved_entries: int = 0
    invalid_entries: list[int] = []


class DedupeReviewResult(BaseModel):
    plan_path: str
    output_path: str
    total_groups: int = 0
    approved_groups: int = 0
    invalid_groups: list[int] = []


class RenameEntry(BaseModel):
    old_path: str
    new_path: str
    old_filename: str
    new_filename: str
    action: str = "rename"
    issue_fixes: list[str] = []


class RenamePlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    root: str
    pattern: str
    entries: list[RenameEntry]
    errors: list[dict] = []


class RenameResult(BaseModel):
    planned: int = 0
    renamed: int = 0
    undone: int = 0
    errors: list[dict] = []
    log_path: str | None = None
    dry_run: bool = True
