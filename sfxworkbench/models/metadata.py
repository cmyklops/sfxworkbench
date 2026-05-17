"""Metadata audit, view, and write-plan models."""

from __future__ import annotations

from pydantic import BaseModel


class MetadataAuditEntry(BaseModel):
    path: str
    filename: str
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    duration_s: float | None = None
    has_bext: bool = False
    has_ixml: bool = False
    has_riff_info: bool = False
    has_adm: bool = False
    has_cue_markers: bool = False
    has_sampler: bool = False
    metadata_sources: list[str] = []
    reasons: list[str] = []


class MetadataAuditSummary(BaseModel):
    total_files: int = 0
    missing_metadata: int = 0
    unusual_sample_rate_files: int = 0
    reported_missing_metadata: int = 0
    reported_unusual_sample_rate_files: int = 0
    sample_rates: dict[str, int] = {}


class MetadataAuditReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    db_path: str
    root: str | None = None
    action_mode: str = "audit"
    standard_sample_rates: list[int] = []
    limit: int = 200
    summary: MetadataAuditSummary
    missing_metadata: list[MetadataAuditEntry] = []
    unusual_sample_rates: list[MetadataAuditEntry] = []


class MetadataViewTag(BaseModel):
    field: str
    value: str
    source: str
    method: str | None = None
    confidence: float | None = None
    evidence: list[str] = []


class MetadataViewEmbeddedField(BaseModel):
    namespace: str
    key: str
    value: str
    source: str


class MetadataViewUcs(BaseModel):
    stem: str
    is_ucs: bool = False
    category: str | None = None
    subcategory: str | None = None
    remainder: str | None = None
    source: str = "heuristic"
    catalog_match: bool = False
    catalog_category: str | None = None
    catalog_subcategory: str | None = None
    catalog_cat_short: str | None = None
    catalog_cat_id: str | None = None
    catalog_release_version: str | None = None


class MetadataViewFile(BaseModel):
    file_id: int
    path: str
    filename: str
    stem: str | None = None
    extension: str | None = None
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    duration_s: float | None = None
    subtype: str | None = None
    has_bext: bool = False
    has_ixml: bool = False
    has_riff_info: bool = False
    has_adm: bool = False
    has_cue_markers: bool = False
    has_sampler: bool = False
    metadata_sources: list[str] = []
    is_ucs: bool = False
    scan_error: str | None = None
    ucs: MetadataViewUcs | None = None
    embedded_fields: list[MetadataViewEmbeddedField] = []
    accepted_tags: list[MetadataViewTag] = []


class MetadataViewReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    db_path: str
    query: str
    catalog_path: str | None = None
    limit: int = 5
    match_count: int = 0
    files: list[MetadataViewFile] = []


class MetadataWriteBackend(BaseModel):
    name: str
    display_name: str
    available: bool = False
    executable: str | None = None
    version: str | None = None
    version_command: list[str] = []
    error: str | None = None
    supported_extensions: list[str] = []
    writes_embedded_metadata: bool = True
    writes_bext: bool = False
    writes_ixml: bool = False
    notes: list[str] = []


class MetadataWriteBackendsReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    recommended_backend: str = "auto"
    backends: list[MetadataWriteBackend] = []


class MetadataWritePlanEntry(BaseModel):
    entry_id: int
    file_id: int
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    field: str
    value: str
    source: str
    method: str | None = None
    confidence: float | None = None
    evidence: list[str] = []
    backend: str = "bwfmetaedit"
    target_namespace: str | None = None
    target_key: str | None = None
    action: str = "unsupported_field"
    existing_value: str | None = None
    supported: bool = False
    review_status: str = "pending"


class MetadataWritePlanSummary(BaseModel):
    files_considered: int = 0
    accepted_tags_considered: int = 0
    candidate_entries: int = 0
    supported_entries: int = 0
    conflict_entries: int = 0
    skip_existing_entries: int = 0
    replace_entries: int = 0
    unsupported_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0
    backend_available: bool = False


class MetadataWritePlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str | None = None
    db_path: str
    action_mode: str = "write_plan"
    target: str = "embedded_metadata"
    dry_run_only: bool = True
    replace_existing: bool = False
    backend: MetadataWriteBackend
    backends: list[MetadataWriteBackend] = []
    summary: MetadataWritePlanSummary
    entries: list[MetadataWritePlanEntry] = []
    errors: list[dict] = []


class MetadataWriteReviewResult(BaseModel):
    plan_path: str
    output_path: str
    total_entries: int = 0
    approved_entries: int = 0
    rejected_entries: int = 0
    invalid_entries: list[int] = []


class MetadataWriteCommand(BaseModel):
    file_id: int
    path: str
    command: list[str] = []
    fields: dict[str, str | list[str]] = {}
    entry_count: int = 0
    allow_overwrite: bool = False
    simulated: bool = True


class MetadataWritePreviewResult(BaseModel):
    planned: int = 0
    would_write: int = 0
    skipped: int = 0
    errors: list[dict] = []
    dry_run: bool = True
    target: str = "embedded_metadata"
    commands: list[MetadataWriteCommand] = []


class MetadataWriteFixtureFile(BaseModel):
    file_id: int
    source_path: str
    fixture_path: str
    backend: str | None = None
    command: list[str] = []
    expected_fields: dict[str, str | list[str]] = {}
    metadata_written: bool = False
    write_result: dict | None = None
    errors: list[str] = []


class MetadataWriteFixtureBundle(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    plan_path: str
    output_dir: str
    dry_run: bool = True
    files: list[MetadataWriteFixtureFile] = []
    errors: list[dict] = []


class MetadataWriteReadbackFile(BaseModel):
    file_id: int
    source_path: str
    fixture_path: str
    expected_fields: dict[str, str | list[str]] = {}
    actual_fields: dict[str, str | list[str]] = {}
    matched_fields: list[str] = []
    mismatched_fields: dict[str, dict[str, str | list[str] | None]] = {}
    errors: list[str] = []


class MetadataWriteReadbackSummary(BaseModel):
    files_checked: int = 0
    matched_files: int = 0
    mismatched_files: int = 0
    error_files: int = 0


class MetadataWriteReadbackReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    manifest_path: str
    summary: MetadataWriteReadbackSummary
    files: list[MetadataWriteReadbackFile] = []
    errors: list[dict] = []


class MetadataWriteApplyResult(BaseModel):
    planned: int = 0
    applied: int = 0
    skipped: int = 0
    files_written: int = 0
    files_backed_up: int = 0
    files_verified: int = 0
    files_restored: int = 0
    backup_dir: str | None = None
    log_path: str | None = None
    backups: list[dict] = []
    write_results: list[dict] = []
    readback: list[dict] = []
    errors: list[dict] = []
    dry_run: bool = True
    target: str = "embedded_metadata"
    cancelled: bool = False


class MetadataWriteUndoResult(BaseModel):
    planned: int = 0
    restored: int = 0
    skipped: int = 0
    bytes_restored: int = 0
    log_path: str | None = None
    errors: list[dict] = []
    dry_run: bool = True
    target: str = "embedded_metadata"
