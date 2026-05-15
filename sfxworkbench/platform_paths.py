"""Cross-platform lexical path policy helpers.

These helpers compare stored path text without forcing host-platform
resolution. That matters for SQLite rows captured on another OS, especially
Windows-style paths being inspected on POSIX.
"""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def normalized_path_text(path: Path | str | None) -> str:
    """Return slash-normalized path text without touching the filesystem."""
    if path is None:
        return ""
    raw = str(path)
    if raw == "":
        return ""

    text = raw.replace("\\", "/")
    is_unc = text.startswith("//")
    is_drive = bool(_WINDOWS_DRIVE_RE.match(text))

    if is_unc:
        remainder = re.sub(r"/+", "/", text[2:])
        text = f"//{remainder}"
    else:
        text = re.sub(r"/+", "/", text)

    if text != "/":
        text = text.rstrip("/")
    if is_drive and text.endswith(":"):
        text = f"{text}/"
    if is_drive and text.endswith(":/"):
        text = text[:-1]

    return text or "/"


def canonical_path_key(path: Path | str | None) -> str:
    """Return a lexical path key for cross-platform scope comparisons."""
    text = normalized_path_text(path)
    if bool(_WINDOWS_DRIVE_RE.match(text)) or text.startswith("//"):
        text = text.casefold()
    return text


def is_windows_path_like(path: Path | str | None) -> bool:
    """Return whether *path* has Windows drive or UNC syntax lexically."""
    if path is None:
        return False
    text = str(path).replace("\\", "/")
    return bool(_WINDOWS_DRIVE_RE.match(text)) or text.startswith("//")


def resolve_scope_root(root: Path | str) -> Path:
    """Resolve POSIX roots while preserving Windows-style lexical test roots."""
    path = Path(root).expanduser()
    if is_windows_path_like(root):
        return path
    return path.resolve()


def is_scoped_path(candidate: Path | str, root: Path | str) -> bool:
    """Return whether *candidate* is *root* or a lexical descendant of it."""
    candidate_key = canonical_path_key(candidate)
    root_key = canonical_path_key(root)
    return candidate_key == root_key or candidate_key.startswith(root_key.rstrip("/") + "/")


def scoped_relative_path(candidate: Path | str, root: Path | str) -> str | None:
    """Return a slash-separated relative path if *candidate* is within *root*."""
    candidate_key = canonical_path_key(candidate)
    root_key = canonical_path_key(root)
    if candidate_key == root_key:
        return ""
    prefix = root_key.rstrip("/") + "/"
    if candidate_key.startswith(prefix):
        candidate_text = normalized_path_text(candidate)
        root_text = normalized_path_text(root)
        return candidate_text[len(root_text.rstrip("/") + "/") :]
    return None


def scoped_relative_parts(candidate: Path | str, root: Path | str) -> tuple[str, ...] | None:
    """Return lexical relative path parts if *candidate* is within *root*."""
    relative = scoped_relative_path(candidate, root)
    if relative is None:
        return None
    if not relative:
        return ()
    return tuple(part for part in relative.split("/") if part)


def path_sort_key(path: Path | str) -> str:
    """Return a stable lexical key for sorting paths across separator styles."""
    return canonical_path_key(path)


def windows_collision_path_key(path: Path | str) -> str:
    """Return a Windows-style case-insensitive path key for target collision checks."""
    key = canonical_path_key(path)
    parts = []
    for part in key.split("/"):
        if part in {"", "."}:
            parts.append(part)
        else:
            parts.append(part.rstrip(" .").casefold())
    return "/".join(parts)


def windows_collision_name_key(name: str) -> str:
    """Return a Windows-style comparison key for one path component."""
    return name.rstrip(" .").casefold()


def safe_relative_display(candidate: Path | str, root: Path | str) -> str:
    """Return a relative display path when scoped, otherwise the original text."""
    relative = scoped_relative_path(candidate, root)
    if relative is None:
        return str(candidate)
    return relative or "."
