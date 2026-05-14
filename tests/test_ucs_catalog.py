"""Tests for UCS catalog import, cache, and lookup."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sfxworkbench.models import UcsCatalog
from sfxworkbench.ucs_catalog import (
    ENV_OVERRIDE,
    ENV_SOURCE,
    OFFICIAL_ATTRIBUTION,
    default_cache_path,
    discover_import_source,
    import_catalog,
    load_catalog,
    parse_soundminer_csv,
    query_categories,
    save_catalog,
)

# ---------------------------------------------------------------------------
# Sample data — minimal Soundminer CSV slice with the upstream BOM and a
# multi-language tail so we exercise quoting and column-skipping.
# ---------------------------------------------------------------------------

_SAMPLE_HEADER = (
    "﻿Category,SubCategory,CatID,CatShort,Explanations,Synonyms - Comma Separated,Category_fr,SubCategory_fr,Synonyms_fr"
)
_SAMPLE_ROWS = [
    'AIR,BLOW,AIRBlow,AIR,"Steady air blows.","Aerate, Air, Blow",AIR,SOUFFLE,"souffler"',
    'AIR,HISS,AIRHiss,AIR,"Slow air releases.","Hissing, Leak",AIR,SIFFLEMENT,"fuite"',
    'AMBIENCE,BACKYRD,AMBBack,AMB,"Backyard ambience.","Yard, Garden",AMBIANCE,JARDIN,"cour"',
    'NATURAL DISASTER,EARTHQUAKE,NatlDisastrEqke,NATDIS,"Tremors.","Quake, Tremor",CATASTROPHE,SEISME,"seisme"',
    # Row missing CatShort — should be skipped.
    "BROKEN,ROW,BrokenRow,,,,,,",
]


def _write_sample_csv(path: Path) -> None:
    path.write_text("\n".join([_SAMPLE_HEADER, *_SAMPLE_ROWS]) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_soundminer_csv
# ---------------------------------------------------------------------------


def test_parse_soundminer_csv_strips_bom_and_localized_columns(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)

    catalog, skipped = parse_soundminer_csv(src, release_version="v8.2.1")

    assert skipped == 1
    assert catalog.provenance.source_format == "soundminer_csv"
    assert catalog.provenance.release_version == "v8.2.1"
    assert catalog.provenance.entry_count == 4
    assert catalog.provenance.attribution == OFFICIAL_ATTRIBUTION
    assert len(catalog.entries) == 4

    # Cat shorts and categories are uppercased; long-form categories may have spaces.
    cat_shorts = {e.cat_short for e in catalog.entries}
    assert cat_shorts == {"AIR", "AMB", "NATDIS"}
    assert any(e.category == "NATURAL DISASTER" for e in catalog.entries)


def test_parse_soundminer_csv_splits_synonyms(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)

    catalog, _ = parse_soundminer_csv(src)
    air_blow = next(e for e in catalog.entries if e.cat_short == "AIR" and e.subcategory == "BLOW")
    assert air_blow.synonyms == ["Aerate", "Air", "Blow"]
    assert air_blow.explanations == "Steady air blows."


def test_parse_soundminer_csv_rejects_missing_required_columns(tmp_path: Path) -> None:
    src = tmp_path / "bad.csv"
    src.write_text("Foo,Bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        parse_soundminer_csv(src)


def test_parse_soundminer_csv_rejects_empty_file(tmp_path: Path) -> None:
    src = tmp_path / "empty.csv"
    src.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty or missing a header"):
        parse_soundminer_csv(src)


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_catalog_round_trip(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src, release_version="v8.2.1")

    cache = tmp_path / "ucs_catalog.json"
    save_catalog(catalog, cache)

    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tool"] == "sfxworkbench"
    assert payload["provenance"]["source_url"] == "https://universalcategorysystem.com/"
    assert payload["provenance"]["entry_count"] == 4

    loaded = load_catalog(cache)
    assert isinstance(loaded, UcsCatalog)
    assert loaded.provenance.entry_count == 4
    assert {e.cat_short for e in loaded.entries} == {"AIR", "AMB", "NATDIS"}


def test_load_catalog_explicit_path_takes_priority(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src)
    explicit = tmp_path / "explicit.json"
    save_catalog(catalog, explicit)

    # Set both env override and a fake default cache; explicit must win.
    monkeypatch.setenv(ENV_OVERRIDE, str(tmp_path / "wrong_env_cache.json"))
    monkeypatch.setattr(
        "sfxworkbench.ucs_catalog.default_cache_path",
        lambda: tmp_path / "wrong_default_cache.json",
    )

    loaded = load_catalog(explicit)
    assert loaded is not None
    assert loaded.provenance.source_path == str(src.resolve())


def test_load_catalog_uses_env_override(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src)
    env_cache = tmp_path / "env.json"
    save_catalog(catalog, env_cache)

    monkeypatch.setenv(ENV_OVERRIDE, str(env_cache))
    monkeypatch.setattr(
        "sfxworkbench.ucs_catalog.default_cache_path",
        lambda: tmp_path / "missing_default.json",
    )

    loaded = load_catalog(None)
    assert loaded is not None
    assert loaded.provenance.entry_count == 4


def test_load_catalog_falls_back_to_default_cache(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src)
    cache = tmp_path / "default_cache.json"
    save_catalog(catalog, cache)

    # Clear env override and point default_cache_path() at our temp file.
    monkeypatch.delenv(ENV_OVERRIDE, raising=False)
    monkeypatch.setattr("sfxworkbench.ucs_catalog.default_cache_path", lambda: cache)

    loaded = load_catalog(None)
    assert loaded is not None
    assert loaded.provenance.entry_count == 4


def test_load_catalog_returns_none_when_nothing_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(ENV_OVERRIDE, raising=False)
    monkeypatch.setattr(
        "sfxworkbench.ucs_catalog.default_cache_path",
        lambda: tmp_path / "definitely_does_not_exist.json",
    )
    assert load_catalog(None) is None


def test_load_catalog_explicit_path_must_exist(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_catalog(tmp_path / "missing.json")


def test_load_catalog_rejects_malformed_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "wrong": "shape"}), encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        load_catalog(bad)


def test_default_cache_path_lives_alongside_index_db() -> None:
    cache = default_cache_path()
    assert cache.name == "ucs_catalog.json"
    # Sibling of the default index.db location.
    assert cache.parent == Path(os.path.expanduser("~/.sfxworkbench"))


def test_discover_import_source_prefers_env_source(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    fallback = tmp_path / "reports" / "_categorylist.csv"
    fallback.parent.mkdir()
    _write_sample_csv(fallback)

    monkeypatch.setenv(ENV_SOURCE, str(src))

    assert discover_import_source([fallback.parent]) == src


def test_discover_import_source_checks_known_shallow_locations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(ENV_SOURCE, raising=False)
    root = tmp_path / "UCS Release" / "Soundminer"
    root.mkdir(parents=True)
    src = root / "_categorylist.csv"
    _write_sample_csv(src)

    assert discover_import_source([tmp_path]) == src


# ---------------------------------------------------------------------------
# import_catalog (CLI-facing wrapper)
# ---------------------------------------------------------------------------


def test_import_catalog_writes_cache_and_returns_summary(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    cache = tmp_path / "sfxworkbench" / "ucs_catalog.json"

    result, catalog = import_catalog(src, output_path=cache, release_version="v8.2.1")

    assert cache.exists()
    assert result.entry_count == 4
    assert result.unique_cat_shorts == 3
    assert result.unique_categories == 3
    assert result.skipped_rows == 1
    assert result.release_version == "v8.2.1"
    assert catalog.provenance.entry_count == 4


def test_import_catalog_rejects_xlsx_source_in_this_slice(tmp_path: Path) -> None:
    fake = tmp_path / "fake.xlsx"
    fake.write_bytes(b"not a real xlsx")
    with pytest.raises(NotImplementedError):
        import_catalog(fake)


def test_import_catalog_rejects_unknown_extension(tmp_path: Path) -> None:
    bad = tmp_path / "fake.txt"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported UCS source format"):
        import_catalog(bad)


def test_import_catalog_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_catalog(tmp_path / "missing.csv")


# ---------------------------------------------------------------------------
# query_categories
# ---------------------------------------------------------------------------


def test_query_categories_filters_by_category_long_form(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src)

    result = query_categories(catalog, category="natural disaster")
    assert result.matched == 1
    assert result.entries[0].cat_short == "NATDIS"


def test_query_categories_filters_by_cat_short(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src)

    result = query_categories(catalog, cat_short="air")
    assert result.matched == 2
    assert {e.subcategory for e in result.entries} == {"BLOW", "HISS"}


def test_query_categories_combined_filter_returns_intersection(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src)

    result = query_categories(catalog, category="AIR", cat_short="AIR")
    assert result.matched == 2

    result_disjoint = query_categories(catalog, category="AIR", cat_short="AMB")
    assert result_disjoint.matched == 0


def test_query_categories_no_filter_returns_all(tmp_path: Path) -> None:
    src = tmp_path / "_categorylist.csv"
    _write_sample_csv(src)
    catalog, _ = parse_soundminer_csv(src)

    result = query_categories(catalog)
    assert result.matched == result.total_loaded == 4
