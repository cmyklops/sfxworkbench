"""Tests for wavwarden.ucs."""

import unicodedata

from wavwarden.ucs import looks_ucs, looks_ucs_casefold, normalize_stem, parse_ucs_stem


def test_parse_ucs_stem_extracts_parts() -> None:
    result = parse_ucs_stem("AMB_RAIN_01")

    assert result.is_ucs is True
    assert result.category == "AMB"
    assert result.subcategory == "RAIN"
    assert result.remainder == "01"
    assert result.source == "heuristic"


def test_parse_ucs_stem_accepts_category_and_subcategory_only() -> None:
    result = parse_ucs_stem("SFX_GUNSHOT")

    assert result.is_ucs is True
    assert result.category == "SFX"
    assert result.subcategory == "GUNSHOT"
    assert result.remainder is None


def test_parse_ucs_stem_rejects_non_ucs_names() -> None:
    result = parse_ucs_stem("BOOM")

    assert result.is_ucs is False
    assert result.category is None
    assert result.subcategory is None


def test_looks_ucs_is_case_sensitive_for_scan() -> None:
    assert looks_ucs("AMB_RAIN_01") is True
    assert looks_ucs("amb_rain_01") is False


def test_casefold_check_supports_rename_cleanup() -> None:
    assert looks_ucs_casefold("amb_rain_01") is True


def test_normalize_stem_uses_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "AMB_CAFE_01")

    assert normalize_stem(nfd) == "AMB_CAFE_01"
