"""Dedupe group + apply-result models."""

from __future__ import annotations

from pydantic import BaseModel


class DedupeApplyResult(BaseModel):
    removed: int = 0
    quarantined: int = 0
    bytes_freed: int = 0
    skipped: int = 0
    errors: list[dict] = []
    quarantine_dir: str | None = None
    log_path: str | None = None
    dry_run: bool = True
    cancelled: bool = False


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
