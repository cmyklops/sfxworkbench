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
