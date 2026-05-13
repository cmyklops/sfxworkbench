"""Format-inconsistency audit models. Reuses ``RelatedSoundFile`` from groups."""

from __future__ import annotations

from pydantic import BaseModel

from sfxworkbench.models.groups import RelatedSoundFile


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
