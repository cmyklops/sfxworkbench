"""Related-sound grouping models. ``RelatedSoundFile`` is also used by
``format`` audit groups."""

from __future__ import annotations

from pydantic import BaseModel


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
