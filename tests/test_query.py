"""Tests for sfxworkbench.query DSL parser/compiler + the `sfx ls` command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfxworkbench.cli import app
from sfxworkbench.db import get_connection
from sfxworkbench.query import (
    QueryError,
    Term,
    compile_query,
    parse_query,
)
from typer.testing import CliRunner

runner = CliRunner()


# -- parse_query ------------------------------------------------------------


def test_parse_query_empty_returns_no_terms() -> None:
    assert parse_query("") == []
    assert parse_query("   ") == []


def test_parse_query_simple_equality() -> None:
    terms = parse_query("ext:wav")
    assert terms == [Term(field="extension", op="=", value="wav")]


def test_parse_query_extension_in_comma_list() -> None:
    terms = parse_query("ext:wav,flac,aiff")
    assert terms == [Term(field="extension", op="in", value=["wav", "flac", "aiff"])]


def test_parse_query_numeric_operators() -> None:
    assert parse_query("rate:>=48000") == [Term(field="sample_rate", op=">=", value=48000)]
    assert parse_query("size:<1000") == [Term(field="size_bytes", op="<", value=1000)]
    assert parse_query("channels:1") == [Term(field="channels", op="=", value=1)]


def test_parse_query_numeric_range() -> None:
    assert parse_query("sample_rate:44100..96000") == [Term(field="sample_rate", op="between", value=(44100, 96000))]


def test_parse_query_boolean_has_and_missing() -> None:
    assert parse_query("has:bext") == [Term(field="has_bext", op="has", value=None)]
    assert parse_query("missing:bext") == [Term(field="has_bext", op="missing", value=None)]


def test_parse_query_negation() -> None:
    assert parse_query("-ext:mp3") == [Term(field="extension", op="=", value="mp3", negated=True)]
    assert parse_query("-missing:bext") == [Term(field="has_bext", op="missing", value=None, negated=True)]


def test_parse_query_free_text_unprefixed() -> None:
    assert parse_query("rain") == [Term(field="_text", op="like", value="rain")]


def test_parse_query_combines_multiple_terms() -> None:
    terms = parse_query("ext:wav rate:>=48000 missing:bext")
    assert len(terms) == 3
    assert terms[0].field == "extension"
    assert terms[1].field == "sample_rate"
    assert terms[2].field == "has_bext"


def test_parse_query_handles_quoted_phrase() -> None:
    """Quoted phrases survive as a single token even though they contain spaces."""
    terms = parse_query('"car crash"')
    assert terms == [Term(field="_text", op="like", value="car crash")]


def test_parse_query_unmatched_quote_raises() -> None:
    with pytest.raises(QueryError, match="unmatched"):
        parse_query('rain "unclosed')


def test_parse_query_rejects_unknown_field() -> None:
    with pytest.raises(QueryError, match="unknown query field"):
        parse_query("nonsense:foo")


def test_parse_query_rejects_unknown_flag() -> None:
    with pytest.raises(QueryError, match="unknown flag"):
        parse_query("has:nonsense")


def test_parse_query_rejects_range_on_string_field() -> None:
    with pytest.raises(QueryError, match="range queries"):
        parse_query("ext:wav..flac")


def test_parse_query_rejects_comparison_on_string_field() -> None:
    with pytest.raises(QueryError, match="comparison operator"):
        parse_query("ext:>wav")


def test_parse_query_rejects_non_numeric_in_numeric_field() -> None:
    with pytest.raises(QueryError, match="expected a number"):
        parse_query("rate:>=fast")


# -- compile_query ----------------------------------------------------------


def test_compile_query_empty_is_always_true() -> None:
    sql, params = compile_query([])
    assert sql == "1=1"
    assert params == []


def test_compile_query_simple_eq() -> None:
    sql, params = compile_query(parse_query("ext:wav"))
    assert sql == "(LOWER(extension) = LOWER(?))"
    # Extension parameter is normalized to ".wav" so it matches what scan.py stores.
    assert params == [".wav"]


def test_compile_query_numeric_inequality() -> None:
    sql, params = compile_query(parse_query("rate:>=48000"))
    assert sql == "(sample_rate >= ?)"
    assert params == [48000]


def test_compile_query_range() -> None:
    sql, params = compile_query(parse_query("rate:44100..96000"))
    assert sql == "(sample_rate BETWEEN ? AND ?)"
    assert params == [44100, 96000]


def test_compile_query_in_list() -> None:
    sql, params = compile_query(parse_query("ext:wav,flac"))
    # Extension IN uses raw column (the LOWER wrapping is only for equality).
    assert "extension IN" in sql
    # And the values are normalized to include the leading dot.
    assert sorted(params) == [".flac", ".wav"]


def test_compile_query_has_missing_flags() -> None:
    has_sql, _ = compile_query(parse_query("has:bext"))
    miss_sql, _ = compile_query(parse_query("missing:bext"))
    assert has_sql == "(has_bext = 1)"
    assert miss_sql == "(has_bext IS NULL OR has_bext = 0)"


def test_compile_query_negation_wraps_with_not() -> None:
    sql, _ = compile_query(parse_query("-ext:mp3"))
    assert sql == "NOT ((LOWER(extension) = LOWER(?)))"


def test_compile_query_combines_with_and() -> None:
    sql, params = compile_query(parse_query("ext:wav rate:>=48000"))
    assert " AND " in sql
    assert len(params) == 2


def test_compile_query_free_text_searches_path_filename_stem() -> None:
    sql, params = compile_query(parse_query("rain"))
    assert sql.count("LIKE") == 3
    assert params == ["%rain%", "%rain%", "%rain%"]


# -- End-to-end against the test DB ----------------------------------------


def _seed_file(
    tmp_db: Path,
    *,
    path: str,
    extension: str = ".wav",
    sample_rate: int = 48000,
    channels: int = 2,
    bit_depth: int = 24,
    has_bext: int = 0,
    size_bytes: int = 1024,
) -> None:
    with get_connection(tmp_db) as conn:
        conn.execute(
            """
            INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, channels,
                sample_rate, bit_depth, duration_s, has_bext, scan_error, scanned_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1.0, ?, NULL, '2026-05-12T00:00:00Z')
            """,
            (
                path,
                Path(path).name,
                Path(path).stem,
                extension,
                size_bytes,
                channels,
                sample_rate,
                bit_depth,
                has_bext,
            ),
        )
        conn.commit()


def test_cli_ls_filters_by_extension_and_sample_rate(tmp_db: Path) -> None:
    _seed_file(tmp_db, path="/lib/AMB_RAIN_01.wav", sample_rate=48000)
    _seed_file(tmp_db, path="/lib/AMB_RAIN_02.wav", sample_rate=44100)
    _seed_file(tmp_db, path="/lib/AMB_RAIN_03.mp3", extension=".mp3", sample_rate=44100)

    result = runner.invoke(app, ["ls", "ext:wav rate:>=48000", "--db", str(tmp_db), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["matched"] == 1
    assert payload["rows"][0]["path"] == "/lib/AMB_RAIN_01.wav"


def test_cli_ls_missing_bext_finds_files_without_metadata(tmp_db: Path) -> None:
    _seed_file(tmp_db, path="/lib/with_bext.wav", has_bext=1)
    _seed_file(tmp_db, path="/lib/no_bext.wav", has_bext=0)

    result = runner.invoke(app, ["ls", "missing:bext", "--db", str(tmp_db), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    paths = {row["path"] for row in payload["rows"]}
    assert paths == {"/lib/no_bext.wav"}


def test_cli_ls_free_text_matches_path_substring(tmp_db: Path) -> None:
    _seed_file(tmp_db, path="/lib/Pistol/SFX_GUNSHOT_01.wav")
    _seed_file(tmp_db, path="/lib/Ambience/AMB_RAIN_01.wav")

    result = runner.invoke(app, ["ls", "Gunshot", "--db", str(tmp_db), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["matched"] == 1
    assert "Gunshot" in payload["rows"][0]["path"].upper() or "GUNSHOT" in payload["rows"][0]["path"]


def test_cli_ls_invalid_query_returns_exit_1(tmp_db: Path) -> None:
    result = runner.invoke(app, ["ls", "nonsense:foo", "--db", str(tmp_db)])
    assert result.exit_code == 1
    assert "unknown query field" in result.output


def test_cli_ls_invalid_sort_column_returns_exit_1(tmp_db: Path) -> None:
    result = runner.invoke(app, ["ls", "ext:wav", "--db", str(tmp_db), "--sort", "nothing"])
    assert result.exit_code == 1
    assert "--sort" in result.output


def test_cli_ls_sort_accepts_query_dsl_aliases(tmp_db: Path) -> None:
    """PR fix: --sort -size should work (was rejected because column is size_bytes)."""
    _seed_file(tmp_db, path="/lib/A.wav", size_bytes=100)
    _seed_file(tmp_db, path="/lib/B.wav", size_bytes=200)

    # -size resolves to size_bytes via FIELD_ALIASES
    result = runner.invoke(app, ["ls", "ext:wav", "--db", str(tmp_db), "--sort", "-size", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    sizes = [row["size_bytes"] for row in payload["rows"]]
    assert sizes == sorted(sizes, reverse=True)

    # -rate resolves to sample_rate similarly
    result = runner.invoke(app, ["ls", "ext:wav", "--db", str(tmp_db), "--sort", "rate", "--json"])
    assert result.exit_code == 0, result.output


def test_cli_ls_descending_sort(tmp_db: Path) -> None:
    _seed_file(tmp_db, path="/lib/A.wav", size_bytes=100)
    _seed_file(tmp_db, path="/lib/B.wav", size_bytes=200)

    result = runner.invoke(app, ["ls", "ext:wav", "--db", str(tmp_db), "--sort", "-size_bytes", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    sizes = [row["size_bytes"] for row in payload["rows"]]
    assert sizes == sorted(sizes, reverse=True)
