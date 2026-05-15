"""Tests for sfxworkbench.db connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sfxworkbench.db import (
    canonical_path_key,
    connection,
    get_connection,
    is_scoped_path,
    path_scope_filter,
    path_scope_params,
    scoped_relative_path,
    windows_collision_path_key,
)


def test_connection_context_manager_closes_on_success(tmp_path: Path) -> None:
    db_path = tmp_path / "ok.db"
    with connection(db_path) as conn:
        row = conn.execute("SELECT 1 AS value").fetchone()
        assert row["value"] == 1
    # After the block the connection must be unusable.
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1").fetchone()


def test_connection_context_manager_closes_on_exception(tmp_path: Path) -> None:
    """If the body raises, the connection still closes (no WAL lock leak)."""
    db_path = tmp_path / "boom.db"

    class _Sentinel(Exception):
        pass

    with pytest.raises(_Sentinel):
        with connection(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
            raise _Sentinel("simulated failure inside the with block")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1").fetchone()


def test_connection_yields_same_kind_of_object_as_get_connection(tmp_path: Path) -> None:
    """``connection`` is a thin wrapper, not a replacement; the underlying object matches."""
    db_path = tmp_path / "same.db"
    bare = get_connection(db_path)
    try:
        bare_type = type(bare)
    finally:
        bare.close()
    with connection(db_path) as wrapped:
        assert type(wrapped) is bare_type


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/Library//FX/", "/Library/FX"),
        ("C:\\Lib\\FX\\", "c:/lib/fx"),
        ("c:/Lib\\FX/file.wav", "c:/lib/fx/file.wav"),
        ("\\\\Server\\Share\\Lib\\A.wav", "//server/share/lib/a.wav"),
    ],
)
def test_canonical_path_key_normalizes_separator_and_windows_case(raw: str, expected: str) -> None:
    assert canonical_path_key(raw) == expected


@pytest.mark.parametrize(
    ("candidate", "root", "expected"),
    [
        ("C:\\Lib", "c:/lib", True),
        ("C:\\Lib\\A.wav", "c:/lib", True),
        ("C:\\Lib2\\A.wav", "c:/lib", False),
        ("C:/Lib\\FX/file.wav", "C:\\LIB", True),
        ("\\\\Server\\Share\\Lib\\A.wav", "\\\\server\\share\\lib", True),
        ("/Library/FX/A.wav", "/Library/FX", True),
        ("/Library/FX2/A.wav", "/Library/FX", False),
    ],
)
def test_is_scoped_path_is_lexical_and_separator_tolerant(candidate: str, root: str, expected: bool) -> None:
    assert is_scoped_path(candidate, root) is expected


def test_scoped_relative_path_returns_slash_relative_value() -> None:
    assert scoped_relative_path("C:\\Lib\\FX\\A.wav", "c:/lib") == "FX/A.wav"
    assert scoped_relative_path("C:\\Lib2\\FX\\A.wav", "c:/lib") is None


def test_path_scope_filter_matches_windows_descendants_and_escapes_like_chars(tmp_path: Path) -> None:
    db_path = tmp_path / "scope.db"
    conn = get_connection(db_path)
    try:
        rows = [
            ("C:\\Lib_%\\A.wav", "A.wav", "A", ".wav", "2026"),
            ("C:\\Lib_%\\Nested\\B.wav", "B.wav", "B", ".wav", "2026"),
            ("C:\\LibX%\\Nope.wav", "Nope.wav", "Nope", ".wav", "2026"),
            ("C:\\Lib_%2\\Nope.wav", "Nope.wav", "Nope", ".wav", "2026"),
        ]
        conn.executemany(
            """
            INSERT INTO files (path, filename, stem, extension, scanned_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        matches = conn.execute(
            f"SELECT path FROM files WHERE {path_scope_filter()} ORDER BY path",
            path_scope_params("c:/lib_%"),
        ).fetchall()
    finally:
        conn.close()

    assert [row["path"] for row in matches] == ["C:\\Lib_%\\A.wav", "C:\\Lib_%\\Nested\\B.wav"]


def test_windows_collision_path_key_collapses_case_and_trailing_dots() -> None:
    assert windows_collision_path_key("C:\\Lib\\CON. ") == windows_collision_path_key("c:/lib/con")


def test_artifact_and_job_schema_is_applied_to_new_database(tmp_path: Path) -> None:
    db_path = tmp_path / "artifacts.db"
    conn = get_connection(db_path)
    try:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"artifacts", "jobs", "artifact_rows", "artifact_rows_fts"} <= tables

        artifact_columns = {row["name"] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        assert {
            "id",
            "path",
            "kind",
            "feature",
            "category",
            "created_at",
            "mtime",
            "size",
            "summary_json",
            "entry_count",
            "error_count",
            "status",
        } <= artifact_columns

        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        assert {
            "id",
            "action",
            "status",
            "started_at",
            "finished_at",
            "progress",
            "output_artifact_id",
            "error",
        } <= job_columns
    finally:
        conn.close()
