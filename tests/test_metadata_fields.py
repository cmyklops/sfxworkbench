"""Tests for the canonical tag-field registry in sfxworkbench.metadata_fields.

Coverage of the DB-ingest helpers (``read_embedded_metadata_fields``,
``replace_metadata_fields``) lives in the scan/metadata-write test suites.
This file focuses on the registry consolidated in PR #3.
"""

from __future__ import annotations

import pytest
from sfxworkbench.metadata_fields import (
    FIELDS,
    canonicalize,
    embedded_keys_for,
    is_multivalue,
    normalize_value_for_dedup,
    values_equal_for_dedup,
)

# -- canonicalize -----------------------------------------------------------


def test_canonicalize_passes_through_canonical_names() -> None:
    for field in FIELDS:
        assert canonicalize(field) == field


def test_canonicalize_collapses_keyword_aliases() -> None:
    assert canonicalize("keywords") == "keyword"
    assert canonicalize("ikey") == "keyword"
    assert canonicalize("KEYWORDS") == "keyword"
    assert canonicalize("  Keyword  ") == "keyword"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ignr", "category"),
        ("isbj", "subcategory"),
        ("inam", "title"),
        ("icmt", "comment"),
    ],
)
def test_canonicalize_resolves_riff_chunk_aliases(raw: str, expected: str) -> None:
    """RIFF chunk keys stored in the metadata_fields table canonicalize to SFX field names."""
    assert canonicalize(raw) == expected


def test_canonicalize_unknown_field_passes_through_lowercased() -> None:
    """Unknown fields still hash consistently; they just aren't in FIELDS."""
    assert canonicalize("Custom_Field") == "custom_field"
    assert canonicalize("  Whatever  ") == "whatever"


# -- is_multivalue ---------------------------------------------------------


def test_is_multivalue_only_keyword() -> None:
    assert is_multivalue("keyword") is True
    for canonical in FIELDS:
        if canonical == "keyword":
            continue
        assert is_multivalue(canonical) is False, f"{canonical} should be single-valued"


def test_is_multivalue_unknown_field_defaults_to_false() -> None:
    assert is_multivalue("not_a_real_field") is False


# -- embedded_keys_for ------------------------------------------------------


def test_embedded_keys_for_description_includes_bext_and_id3() -> None:
    keys = embedded_keys_for("description")
    assert ("bext", "description") in keys
    assert ("id3", "description") in keys


def test_embedded_keys_for_keyword_covers_riff_info_ikey() -> None:
    keys = embedded_keys_for("keyword")
    assert ("riff_info", "ikey") in keys
    assert ("tag", "keywords") in keys


def test_embedded_keys_for_unknown_field_returns_empty() -> None:
    assert embedded_keys_for("custom_field") == ()


def test_embedded_keys_for_ucs_fields_are_empty() -> None:
    """UCS provenance fields live only in accepted_tags, not in metadata_fields."""
    assert embedded_keys_for("ucs_category") == ()
    assert embedded_keys_for("ucs_subcategory") == ()


# -- normalize_value_for_dedup / values_equal_for_dedup ---------------------


def test_normalize_value_for_dedup_collapses_whitespace_and_casefolds() -> None:
    assert normalize_value_for_dedup("  Rain   Heavy  ") == "rain heavy"
    assert normalize_value_for_dedup("Rain\tHeavy") == "rain heavy"
    assert normalize_value_for_dedup("RAIN HEAVY") == "rain heavy"


def test_values_equal_for_dedup_treats_casing_and_whitespace_as_same() -> None:
    assert values_equal_for_dedup("Rain Heavy", "  rain   heavy ")
    assert values_equal_for_dedup("rain heavy", "RAIN HEAVY")


def test_values_equal_for_dedup_distinguishes_meaningful_differences() -> None:
    """Punctuation, dashes, and other characters DO matter for dedup.

    The dedup normalization is intentionally minimal so that values like
    ``"rain-heavy"`` and ``"rain heavy"`` are treated as distinct candidates
    the user can then review.
    """
    assert not values_equal_for_dedup("rain heavy", "rain-heavy")
    assert not values_equal_for_dedup("rain heavy", "rain, heavy")


# -- Sanity: registry shape -------------------------------------------------


def test_registry_canonical_names_appear_in_their_own_aliases() -> None:
    """Every TagField's canonical name should also be listed as an alias."""
    for field in FIELDS.values():
        assert field.canonical in field.aliases, f"{field.canonical!r} missing from own aliases"


def test_registry_aliases_are_lowercase() -> None:
    """Aliases are matched case-insensitively but stored lowercased for clarity."""
    for field in FIELDS.values():
        for alias in field.aliases:
            assert alias == alias.lower(), f"{field.canonical}: alias {alias!r} should be lowercase"


def test_registry_has_no_alias_collisions() -> None:
    """No two fields share an alias (would make canonicalize() non-deterministic)."""
    seen: dict[str, str] = {}
    for field in FIELDS.values():
        for alias in field.aliases:
            assert alias not in seen, f"alias {alias!r} on {field.canonical!r} also belongs to {seen[alias]!r}"
            seen[alias] = field.canonical
