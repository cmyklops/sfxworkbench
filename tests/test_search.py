"""Tests for wavwarden.search."""

from pathlib import Path

from wavwarden.scan import scan_library
from wavwarden.search import search


def test_search_finds_by_filename(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True)
    results = search(tmp_db, "RAIN")
    assert any("RAIN" in r["filename"] for r in results)


def test_search_finds_by_stem_token(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True)
    results = search(tmp_db, "GUNSHOT")
    assert any("GUNSHOT" in r["filename"] for r in results)


def test_search_returns_dicts_with_metadata(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True)
    results = search(tmp_db, "AMB")
    assert results
    keys = set(results[0].keys())
    expected = {"path", "filename", "stem", "extension", "sample_rate", "is_ucs"}
    assert expected.issubset(keys)


def test_search_empty_query_no_match(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True)
    results = search(tmp_db, "ZZZ_DOES_NOT_EXIST")
    assert results == []


def test_search_respects_limit(tmp_library: Path, tmp_db: Path) -> None:
    scan_library(tmp_library, tmp_db, skip_hash=True)
    results = search(tmp_db, "wav", limit=2)
    assert len(results) <= 2
