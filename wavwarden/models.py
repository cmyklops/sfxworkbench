"""Pydantic v2 data models for wavwarden."""

from pydantic import BaseModel


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


class FileRecord(BaseModel):
    path: str
    filename: str
    stem: str
    extension: str
    size_bytes: int
    mtime: float
    md5: str | None = None
    audio: AudioInfo | None = None
    fn_issues: list[FilenameIssue] = []
    is_ucs: bool = False
    scanned_at: str


class CleanResult(BaseModel):
    removed_files: list[str] = []
    removed_dirs: list[str] = []
    bytes_freed: int = 0
    dry_run: bool = True


class DedupeGroup(BaseModel):
    hash: str
    size_bytes: int
    files: list[str]
