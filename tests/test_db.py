"""Tests for sfxworkbench.db connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sfxworkbench.db import connection, get_connection


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
