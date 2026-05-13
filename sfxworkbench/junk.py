"""Shared junk-pattern definitions.

The single source of truth for what counts as junk and what counts as audio.
Both `clean.py` and `scan.py` import from here. Adding a new pattern here
makes it visible to both modules in one shot.
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Audio extensions — never treated as junk (safety guard)
# ---------------------------------------------------------------------------

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".wav",
        ".aif",
        ".aiff",
        ".mp3",
        ".flac",
        ".ogg",
        ".opus",
        ".m4a",
        ".w64",
        ".rf64",
    }
)

# ---------------------------------------------------------------------------
# Junk patterns
# ---------------------------------------------------------------------------

# Entire directory trees to remove / skip during scan
JUNK_DIR_NAMES: frozenset[str] = frozenset({"_wfCache", "__MACOSX"})

# Exact filename matches
JUNK_FILENAMES: frozenset[str] = frozenset({".DS_Store", "desktop.ini", "Thumbs.db"})

# Filename suffixes (lowercase). Peak/cache sidecars created by DAWs.
JUNK_SUFFIXES: frozenset[str] = frozenset({".reapeaks", ".sfk", ".pkf", ".wf"})

# AppleDouble files — macOS resource forks left over from exFAT transfers.
APPLE_DOUBLE_PREFIX: str = "._"


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def is_apple_double(name: str) -> bool:
    """True if the filename is a macOS AppleDouble resource fork."""
    return name.startswith(APPLE_DOUBLE_PREFIX)


def is_junk_file(path: Path) -> bool:
    """Return True if this file should be treated as junk.

    AppleDouble files are always junk (macOS resource forks; never contain
    real audio). For other patterns, files with audio extensions are
    protected as a safety guard so we never accidentally delete content.

    ``.DS_Store`` is exempted on macOS: Finder regenerates the file the
    moment the enclosing folder is browsed, so cleanup is pointless churn.
    On Linux / Windows / WSL the file is still detritus from a previous
    macOS mount and worth removing.
    """
    name = path.name
    # AppleDouble: always junk, regardless of apparent extension.
    if is_apple_double(name):
        return True
    # Safety guard for non-AppleDouble: don't touch audio.
    if path.suffix.lower() in AUDIO_EXTENSIONS:
        return False
    if name == ".DS_Store" and sys.platform == "darwin":
        return False
    if name in JUNK_FILENAMES:
        return True
    if path.suffix.lower() in JUNK_SUFFIXES:
        return True
    return False


def is_junk_dir(path: Path) -> bool:
    """True if the directory itself is a junk dir (e.g. `_wfCache/`)."""
    return path.name in JUNK_DIR_NAMES


def is_inside_junk_dir(path: Path) -> bool:
    """True if any path component is a junk dir name."""
    return any(part in JUNK_DIR_NAMES for part in path.parts)
