"""Audio + filename metadata and top-level result/audit shells."""

from __future__ import annotations

from pydantic import BaseModel


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


class CleanResult(BaseModel):
    removed_files: list[str] = []
    removed_dirs: list[str] = []
    bytes_freed: int = 0
    dry_run: bool = True
    cancelled: bool = False


class ScanResult(BaseModel):
    total: int = 0
    scanned: int = 0
    skipped: int = 0
    errors: int = 0


class AuditResult(BaseModel):
    generated_at: str | None = None
    root: str | None = None
    db_path: str | None = None
    action_mode: str = "audit"
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


class AuditBundleSummary(BaseModel):
    total_files: int = 0
    scan_errors: int = 0
    filename_issues: int = 0
    missing_metadata: int = 0
    unusual_sample_rate_files: int = 0
    duplicate_groups: int = 0
    duplicate_files: int = 0
    related_groups: int = 0
    format_inconsistent_groups: int = 0
    pack_exact_duplicate_groups: int = 0
    pack_overlap_candidates: int = 0
    ucs_catalog_matches: int = 0
    ucs_catalog_misses: int = 0
    reports_written: int = 0
    errors: int = 0


class AuditBundleReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    action_mode: str = "full_audit"
    output_dir: str
    include_similarity: bool = False
    report_paths: dict[str, str] = {}
    summary: AuditBundleSummary
    audit: AuditResult
    errors: list[dict] = []
