"""UCS filename parsing helpers.

This module intentionally implements sfxworkbench's current UCS heuristic, not a
full Universal Category System validator. Official category catalog support can
be layered in here once redistribution/use terms are verified.
"""

from __future__ import annotations

import re
import unicodedata

from sfxworkbench.models import UcsParseResult

UCS_STEM_RE = re.compile(r"^(?P<category>[A-Z]{2,5})_(?P<subcategory>[A-Z]{2,8})(?:_(?P<remainder>.*)|$)")


def normalize_stem(stem: str) -> str:
    """Normalize filename stems before UCS parsing or rename decisions."""
    return unicodedata.normalize("NFC", stem)


def parse_ucs_stem(stem: str) -> UcsParseResult:
    """Parse a stem with sfxworkbench's UCS-looking-name heuristic."""
    normalized = normalize_stem(stem)
    match = UCS_STEM_RE.match(normalized)
    if match is None:
        return UcsParseResult(stem=normalized)
    return UcsParseResult(
        stem=normalized,
        is_ucs=True,
        category=match.group("category"),
        subcategory=match.group("subcategory"),
        remainder=match.group("remainder"),
    )


def looks_ucs(stem: str) -> bool:
    """Return True when a filename stem looks UCS-named."""
    return parse_ucs_stem(stem).is_ucs


def looks_ucs_casefold(stem: str) -> bool:
    """Return True when a stem would look UCS-named after uppercasing.

    Rename uses this tolerant check to avoid prefixing names that are already
    UCS-shaped but need case cleanup.
    """
    return looks_ucs(normalize_stem(stem).upper())
