"""Filename health checks extracted from audit.py — importable for Phase 1."""

import unicodedata
from pathlib import Path

from wavwarden.models import FilenameIssue

# Characters that are illegal on Windows/exFAT (breaks cross-platform portability)
_ILLEGAL_CHARS = set(':*?"<>|')
# Characters that cause issues in shells, URLs, or some DAWs even on macOS
_RISKY_CHARS = set("#&;'\\!")
# Max safe byte length for a single path component (APFS/HFS+ limit is 255 bytes UTF-8)
_MAX_NAME_BYTES = 255
# Warn when a full absolute path exceeds this (Windows MAX_PATH default)
_MAX_PATH_BYTES = 260


def check_path(path: Path, root: Path) -> list[FilenameIssue]:
    """
    Return a list of FilenameIssue objects for this path.

    Checks performed on every component of the path relative to root:
      1. unicode_normalization  — name is NFD; rsync will silently skip it on APFS (NFC)
      2. illegal_chars          — contains characters illegal on Windows/exFAT (:*?"<>|)
      3. risky_chars            — contains characters that break shells or some DAWs (#&;\\'!)
      4. name_too_long          — component exceeds 255 UTF-8 bytes (APFS/HFS+ limit)
      5. path_too_long          — full absolute path exceeds 260 bytes (Windows MAX_PATH)
      6. non_ascii              — contains non-ASCII characters (informational)
      7. leading_trailing_space — name starts or ends with a space
      8. dot_prefix             — name starts with a dot (hidden on macOS/Linux)
    """
    issues: list[FilenameIssue] = []
    abs_str = str(path)

    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts

    for component in rel_parts:
        # 1. Unicode normalization: NFD names are invisible to rsync on APFS
        nfc = unicodedata.normalize("NFC", component)
        if component != nfc:
            issues.append(
                FilenameIssue(
                    component=component,
                    issue="unicode_normalization",
                    detail=(
                        f"Name is NFD-normalized. rsync will silently skip this path "
                        f"when copying to APFS. Use `ditto` or normalize names first. "
                        f"NFC form: {nfc!r}"
                    ),
                )
            )

        # 2. Illegal characters (Windows/exFAT)
        found_illegal = sorted(_ILLEGAL_CHARS & set(component))
        if found_illegal:
            issues.append(
                FilenameIssue(
                    component=component,
                    issue="illegal_chars",
                    detail=f"Contains characters illegal on Windows/exFAT: {found_illegal}",
                )
            )

        # 3. Risky characters (shells, DAWs, URLs)
        found_risky = sorted(_RISKY_CHARS & set(component))
        if found_risky:
            issues.append(
                FilenameIssue(
                    component=component,
                    issue="risky_chars",
                    detail=f"Contains characters that may break shells or DAW imports: {found_risky}",
                )
            )

        # 4. Component byte length
        name_bytes = len(component.encode("utf-8"))
        if name_bytes > _MAX_NAME_BYTES:
            issues.append(
                FilenameIssue(
                    component=component,
                    issue="name_too_long",
                    detail=f"Component is {name_bytes} UTF-8 bytes; APFS limit is {_MAX_NAME_BYTES}.",
                )
            )

        # 6. Non-ASCII (informational)
        if any(ord(c) > 127 for c in component):
            issues.append(
                FilenameIssue(
                    component=component,
                    issue="non_ascii",
                    detail="Contains non-ASCII characters. May cause issues on non-Unicode filesystems.",
                )
            )

        # 7. Leading/trailing spaces
        if component != component.strip():
            issues.append(
                FilenameIssue(
                    component=component,
                    issue="leading_trailing_space",
                    detail="Name starts or ends with a space. Breaks many tools and shells.",
                )
            )

        # 8. Dot-prefixed (hidden files)
        if component.startswith(".") and component not in (".", ".."):
            issues.append(
                FilenameIssue(
                    component=component,
                    issue="dot_prefix",
                    detail="Name starts with a dot; file will be hidden on macOS/Linux.",
                )
            )

    # 5. Full path byte length (check once per file)
    path_bytes = len(abs_str.encode("utf-8"))
    if path_bytes > _MAX_PATH_BYTES:
        issues.append(
            FilenameIssue(
                component=abs_str,
                issue="path_too_long",
                detail=f"Full path is {path_bytes} bytes; Windows MAX_PATH is {_MAX_PATH_BYTES}.",
            )
        )

    return issues
