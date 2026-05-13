"""Similarity crawl, search, segment, audit, and feedback models."""

from __future__ import annotations

from pydantic import BaseModel


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
