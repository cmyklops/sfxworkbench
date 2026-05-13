"""Pydantic v2 data models for sfxworkbench.

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


class SimilarityDescriptor(BaseModel):
    file_id: int
    path: str
    backend: str = "deterministic_v1"
    backend_version: str | None = None
    parameters_hash: str | None = None
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    max_duration_s: float | None = None
    analyzed_duration_s: float | None = None
    peak: float | None = None
    rms: float | None = None
    crest_factor: float | None = None
    silence_ratio: float | None = None
    clipping_count: int = 0
    zero_crossing_rate: float | None = None
    transient_density: float | None = None
    spectral_centroid: float | None = None
    spectral_bandwidth: float | None = None
    spectral_rolloff: float | None = None
    spectral_flatness: float | None = None
    segment_count: int = 0
    segment_method: str | None = None
    duration_bucket: str | None = None
    generated_at: str
    error: str | None = None


class SimilarityCrawlSummary(BaseModel):
    total_files: int = 0
    analyzed: int = 0
    skipped: int = 0
    errors: int = 0
    segments_detected: int = 0
    pending: int = 0
    stale: int = 0


class SimilarityCrawlReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    run_id: int | None = None
    backend: str = "deterministic_v1"
    backend_version: str | None = None
    segment_method: str | None = None
    parameters_hash: str | None = None
    root: str
    db_path: str
    cache_path: str | None = None
    max_duration_s: float | None = None
    max_files: int | None = None
    force: bool = False
    status: str = "completed"
    stop_reason: str | None = None
    summary: SimilarityCrawlSummary
    descriptors: list[SimilarityDescriptor] = []


class SimilarityBackendCapability(BaseModel):
    backend: str
    backend_version: str
    status: str
    scope: list[str] = []
    model_version: str | None = None
    parameters: dict = {}
    notes: list[str] = []


class SimilarityBackendsReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    default_backend: str = "deterministic_v1"
    capabilities: list[SimilarityBackendCapability] = []


class SimilaritySearchResult(BaseModel):
    scope: str = "file"
    file_id: int
    path: str
    filename: str
    distance: float
    score: float
    segment_index: int | None = None
    segment_start_s: float | None = None
    segment_end_s: float | None = None
    segment_duration_s: float | None = None
    segment_confidence: float | None = None
    segment_method: str | None = None
    duration_s: float | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    peak: float | None = None
    rms: float | None = None
    crest_factor: float | None = None
    silence_ratio: float | None = None
    clipping_count: int = 0
    zero_crossing_rate: float | None = None
    transient_density: float | None = None
    spectral_centroid: float | None = None
    spectral_bandwidth: float | None = None
    spectral_rolloff: float | None = None
    spectral_flatness: float | None = None
    duration_bucket: str | None = None


class SimilaritySearchReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    backend: str = "deterministic_v1"
    query_path: str
    db_path: str
    scope: str = "file"
    max_duration_s: float | None = None
    candidates_considered: int = 0
    limit: int = 20
    query_descriptor: SimilarityDescriptor
    results: list[SimilaritySearchResult] = []


class SimilaritySegment(BaseModel):
    file_id: int
    path: str
    filename: str | None = None
    backend: str = "deterministic_v1"
    max_duration_s: float | None = None
    segment_index: int
    start_s: float
    end_s: float
    duration_s: float
    peak: float | None = None
    rms: float | None = None
    crest_factor: float | None = None
    silence_ratio: float | None = None
    zero_crossing_rate: float | None = None
    spectral_centroid: float | None = None
    spectral_bandwidth: float | None = None
    spectral_rolloff: float | None = None
    spectral_flatness: float | None = None
    confidence: float | None = None
    method: str
    generated_at: str


class SimilaritySegmentsSummary(BaseModel):
    files_with_segments: int = 0
    segments: int = 0


class SimilaritySegmentsReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    backend: str = "deterministic_v1"
    root: str
    db_path: str
    max_duration_s: float | None = None
    limit: int = 200
    summary: SimilaritySegmentsSummary
    segments: list[SimilaritySegment] = []


class SimilarityAuditFile(BaseModel):
    file_id: int
    path: str
    filename: str
    md5: str | None = None
    duration_s: float | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    duration_bucket: str | None = None


class SimilarityAuditPair(BaseModel):
    scope: str = "file"
    left_file_id: int
    right_file_id: int
    left_path: str
    right_path: str
    left_segment_index: int | None = None
    left_segment_start_s: float | None = None
    left_segment_end_s: float | None = None
    right_segment_index: int | None = None
    right_segment_start_s: float | None = None
    right_segment_end_s: float | None = None
    distance: float
    score: float
    shared_duration_bucket: bool = False


class SimilarityAuditGroup(BaseModel):
    group_id: int
    file_count: int = 0
    pair_count: int = 0
    min_score: float
    max_score: float
    files: list[SimilarityAuditFile] = []
    pairs: list[SimilarityAuditPair] = []


class SimilarityAuditSummary(BaseModel):
    descriptors_considered: int = 0
    candidate_comparisons: int = 0
    candidate_pairs: int = 0
    exact_md5_pairs_excluded: int = 0
    candidate_groups: int = 0
    reported_groups: int = 0


class SimilarityAuditReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    backend: str = "deterministic_v1"
    root: str
    db_path: str
    scope: str = "file"
    threshold: float = 0.92
    max_duration_s: float | None = None
    exclude_exact_md5: bool = True
    limit: int = 200
    summary: SimilarityAuditSummary
    groups: list[SimilarityAuditGroup] = []


class SimilarityFeedbackEntry(BaseModel):
    id: int
    backend: str = "deterministic_v1"
    scope: str = "file"
    state: str
    left_file_id: int
    right_file_id: int
    left_path: str
    right_path: str
    left_filename: str
    right_filename: str
    left_segment_index: int | None = None
    right_segment_index: int | None = None
    note: str | None = None
    created_at: str
    updated_at: str


class SimilarityFeedbackSummary(BaseModel):
    total: int = 0
    by_state: dict[str, int] = {}


class SimilarityFeedbackReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    db_path: str
    backend: str = "deterministic_v1"
    scope: str | None = None
    state: str | None = None
    limit: int = 200
    summary: SimilarityFeedbackSummary
    entries: list[SimilarityFeedbackEntry] = []


class SimilarityFeedbackChange(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    db_path: str
    backend: str = "deterministic_v1"
    action: str
    removed: int = 0
    entry: SimilarityFeedbackEntry | None = None


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
    tool: str = "sfxworkbench"
    tool_version: str
    db_path: str
    entries: list[ScanErrorEntry]


class ScanErrorApplyResult(BaseModel):
    planned: int = 0
    quarantined: int = 0
    bytes_quarantined: int = 0
    skipped: int = 0  # Tier 3.8: entries dropped by ``target_paths`` filter
    errors: list[dict] = []
    quarantine_dir: str | None = None
    dry_run: bool = True


class DedupeApplyResult(BaseModel):
    removed: int = 0
    quarantined: int = 0
    bytes_freed: int = 0
    skipped: int = 0  # Tier 3.8: entries dropped by ``target_paths`` filter
    errors: list[dict] = []
    quarantine_dir: str | None = None
    log_path: str | None = None
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
    output_dir: str
    include_similarity: bool = False
    report_paths: dict[str, str] = {}
    summary: AuditBundleSummary
    audit: AuditResult
    errors: list[dict] = []


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
    # Count of files where readback mismatch triggered an automatic restore from
    # the pre-apply backup. Added in PR #7 to make the rollback path observable
    # in the apply result and downstream apply-log JSON.
    files_restored: int = 0
    backup_dir: str | None = None
    log_path: str | None = None
    backups: list[dict] = []
    write_results: list[dict] = []
    readback: list[dict] = []
    errors: list[dict] = []
    dry_run: bool = True
    target: str = "embedded_metadata"


class MetadataWriteUndoResult(BaseModel):
    planned: int = 0
    restored: int = 0
    skipped: int = 0
    bytes_restored: int = 0
    log_path: str | None = None
    errors: list[dict] = []
    dry_run: bool = True
    target: str = "embedded_metadata"


class RelatedSoundFile(BaseModel):
    path: str
    filename: str
    marker: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    duration_s: float | None = None
    md5: str | None = None


class RelatedSoundGroup(BaseModel):
    group_id: int
    parent_path: str
    inferred_stem: str
    reason: str
    confidence: str = "medium"
    file_count: int = 0
    sample_rates: list[int] = []
    bit_depths: list[int] = []
    channels: list[int] = []
    markers: list[str] = []
    files: list[RelatedSoundFile] = []


class RelatedGroupsSummary(BaseModel):
    indexed_files_considered: int = 0
    candidate_groups: int = 0
    reported_groups: int = 0
    grouped_files: int = 0
    numbered_sequence_groups: int = 0
    channel_set_groups: int = 0
    mixed_format_groups: int = 0


class RelatedGroupsReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    min_files: int = 2
    limit: int = 200
    summary: RelatedGroupsSummary
    groups: list[RelatedSoundGroup] = []


class FormatInconsistency(BaseModel):
    field: str
    values: list[int]


class FormatAuditGroup(BaseModel):
    group_id: int
    source_group_id: int
    parent_path: str
    inferred_stem: str
    related_group_reason: str
    action: str = "review_only"
    file_count: int = 0
    inconsistencies: list[FormatInconsistency] = []
    files: list[RelatedSoundFile] = []


class FormatAuditSummary(BaseModel):
    related_groups_considered: int = 0
    inconsistent_groups: int = 0
    reported_groups: int = 0
    affected_files: int = 0
    sample_rate_groups: int = 0
    bit_depth_groups: int = 0
    channel_layout_groups: int = 0


class FormatAuditReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    db_path: str
    min_files: int = 2
    limit: int = 200
    summary: FormatAuditSummary
    groups: list[FormatAuditGroup] = []


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
    skipped: int = 0  # Tier 3.8: entries dropped by ``target_paths`` filter
    undone: int = 0
    errors: list[dict] = []
    log_path: str | None = None
    dry_run: bool = True


# ---------------------------------------------------------------------------
# UCS catalog (imported from official Soundminer CSV / XLSX release)
# ---------------------------------------------------------------------------


class UcsEntry(BaseModel):
    cat_short: str  # e.g. "AIR" — uppercase filename prefix (3–5 chars in v8.2.1)
    category: str  # e.g. "AIR" or "NATURAL DISASTER" (long form, may contain spaces)
    subcategory: str  # e.g. "BLOW", "EARTHQUAKE" — uppercase in-filename token
    cat_id: str  # e.g. "AIRBlow" — Soundminer identifier (kept for provenance)
    explanations: str | None = None
    synonyms: list[str] = []


class UcsCatalogProvenance(BaseModel):
    source_url: str
    source_path: str
    source_format: str  # "soundminer_csv" | "official_xlsx" | "user_json"
    release_version: str | None = None  # e.g. "v8.2.1"
    imported_at: str
    attribution: str
    entry_count: int


class UcsCatalog(BaseModel):
    schema_version: int = 1
    tool: str = "sfxworkbench"
    tool_version: str
    provenance: UcsCatalogProvenance
    entries: list[UcsEntry] = []


class UcsImportResult(BaseModel):
    catalog_path: str
    source_path: str
    source_format: str
    release_version: str | None = None
    entry_count: int = 0
    unique_cat_shorts: int = 0
    unique_categories: int = 0
    skipped_rows: int = 0


class UcsCategoriesQuery(BaseModel):
    category: str | None = None
    cat_short: str | None = None
    total_loaded: int = 0
    matched: int = 0
    entries: list[UcsEntry] = []


class UcsValidationIssue(BaseModel):
    file_id: int
    path: str
    filename: str
    cat_short: str | None = None
    subcategory: str | None = None
    reason: str


class UcsValidationSummary(BaseModel):
    files_considered: int = 0
    ucs_looking: int = 0
    catalog_matches: int = 0
    catalog_misses: int = 0
    non_ucs: int = 0
    by_miss_reason: dict[str, int] = {}


class UcsValidationReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str | None = None
    db_path: str
    catalog_path: str
    catalog_release_version: str | None = None
    limit: int = 200
    summary: UcsValidationSummary
    issues: list[UcsValidationIssue] = []


# ---------------------------------------------------------------------------
# Tag suggestions (Phase B — report-only)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Advanced maintenance workflows (M4)
# ---------------------------------------------------------------------------


class CompareMatch(BaseModel):
    file_id: int
    path: str
    filename: str
    md5: str | None = None
    size_bytes: int | None = None


class CompareEntry(BaseModel):
    path: str
    filename: str
    size_bytes: int | None = None
    mtime: float | None = None
    md5: str | None = None
    status: str = "new"
    exact_matches: list[CompareMatch] = []


class CompareSummary(BaseModel):
    files_considered: int = 0
    exact_duplicate_files: int = 0
    new_files: int = 0
    hash_errors: int = 0


class CompareReport(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    root: str
    against_db: str
    limit: int = 200
    summary: CompareSummary
    entries: list[CompareEntry] = []
    errors: list[dict] = []


class ComparePlanEntry(BaseModel):
    entry_id: int
    path: str
    action: str = "review_import"
    reason: str
    exact_matches: list[CompareMatch] = []
    review_status: str = "pending"


class ComparePlanSummary(BaseModel):
    candidate_entries: int = 0
    skip_import_entries: int = 0
    review_import_entries: int = 0


class ComparePlan(BaseModel):
    schema_version: int = 1
    generated_at: str
    tool: str = "sfxworkbench"
    tool_version: str
    source_report: str
    root: str
    against_db: str
    summary: ComparePlanSummary
    entries: list[ComparePlanEntry] = []
    errors: list[dict] = []


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
