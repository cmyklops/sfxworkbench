"""Rename plan + result models."""

from __future__ import annotations

from pydantic import BaseModel


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
    skipped: int = 0
    undone: int = 0
    errors: list[dict] = []
    log_path: str | None = None
    dry_run: bool = True
    cancelled: bool = False
