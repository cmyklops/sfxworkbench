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
    subtype: str | None = None   # e.g. "PCM_24", "FLOAT"
    has_bext: bool = False
    has_ixml: bool = False
    error: str | None = None


class FilenameIssue(BaseModel):
    component: str
    issue: str
    detail: str


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
    bytes_freed: int = 0
    errors: list[dict] = []
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
