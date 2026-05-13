"""Tests for sfxworkbench.backups and the `sfx maintenance clean-backups` command."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sfxworkbench.backups import (
    backup_path_for,
    clean_backups,
    discover_backups,
    make_original_backup,
    parse_backup_filename,
)
from sfxworkbench.cli import app
from typer.testing import CliRunner

runner = CliRunner()


# -- make_original_backup ---------------------------------------------------


def test_make_original_backup_creates_sibling_with_timestamp(tmp_path: Path) -> None:
    target = tmp_path / "audio.wav"
    target.write_bytes(b"original content")

    backup = make_original_backup(target)

    assert backup.parent == target.parent
    assert backup.name.startswith("audio.wav.original-")
    assert backup.name.endswith("Z")
    assert backup.read_bytes() == b"original content"
    # Original is untouched.
    assert target.read_bytes() == b"original content"


def test_make_original_backup_preserves_mode_and_mtime(tmp_path: Path) -> None:
    target = tmp_path / "audio.wav"
    target.write_bytes(b"x")
    target.chmod(0o640)
    historical_mtime = time.time() - 1000
    os.utime(target, (historical_mtime, historical_mtime))

    backup = make_original_backup(target)

    assert backup.stat().st_mode & 0o777 == 0o640
    # mtime is preserved to second precision via shutil.copy2.
    assert abs(backup.stat().st_mtime - historical_mtime) < 1


def test_make_original_backup_uses_explicit_stamp_when_given(tmp_path: Path) -> None:
    target = tmp_path / "audio.wav"
    target.write_bytes(b"x")

    backup = make_original_backup(target, stamp="20260512T143022.123456")

    assert backup.name == "audio.wav.original-20260512T143022.123456Z"


def test_make_original_backup_does_not_clobber_within_same_second(tmp_path: Path) -> None:
    """Regression for the P1 bug: second-only timestamps would silently overwrite."""
    target = tmp_path / "audio.wav"
    target.write_bytes(b"v1")
    first = make_original_backup(target)
    target.write_bytes(b"v2")
    second = make_original_backup(target)

    # The two backups must be distinct files even if taken in the same wall second.
    assert first != second
    assert first.exists()
    assert second.exists()
    # Each preserves the source content captured at backup time.
    assert first.read_bytes() == b"v1"
    assert second.read_bytes() == b"v2"


def test_make_original_backup_raises_when_source_missing(tmp_path: Path) -> None:
    missing = tmp_path / "ghost.wav"

    with pytest.raises(FileNotFoundError):
        make_original_backup(missing)


def test_backup_path_for_is_pure(tmp_path: Path) -> None:
    target = tmp_path / "audio.wav"
    path = backup_path_for(target, stamp="20260101T000000.000000")
    # Pure: no file is created.
    assert not path.exists()
    assert path.name == "audio.wav.original-20260101T000000.000000Z"


# -- parse_backup_filename --------------------------------------------------


def test_parse_backup_filename_round_trips(tmp_path: Path) -> None:
    backup_path = tmp_path / "rain.wav.original-20260512T120000.654321Z"
    parsed = parse_backup_filename(backup_path)

    assert parsed is not None
    assert parsed.backup_path == backup_path
    assert parsed.original_path == tmp_path / "rain.wav"
    assert parsed.created_at == datetime(2026, 5, 12, 12, 0, 0, 654321, tzinfo=UTC)


@pytest.mark.parametrize(
    "name",
    [
        "rain.wav",
        "rain.original.wav",  # ".original" not in suffix position
        "rain.wav.original-",
        "rain.wav.original-20260512",  # missing time portion
        "rain.wav.original-20260512T120000",  # missing microseconds + trailing Z
        "rain.wav.original-20260512T120000Z",  # missing microseconds (pre-P1-fix shape)
        "rain.wav.original-20260512T120000.123456",  # missing trailing Z
        "rain.wav.original-NOTATIMESTAMPZ",
    ],
)
def test_parse_backup_filename_rejects_non_matching_names(tmp_path: Path, name: str) -> None:
    assert parse_backup_filename(tmp_path / name) is None


# -- discover_backups -------------------------------------------------------


def test_discover_backups_finds_only_backup_files(tmp_path: Path) -> None:
    (tmp_path / "rain.wav").write_bytes(b"x")
    (tmp_path / "rain.wav.original-20260101T000000.000000Z").write_bytes(b"backup1")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "wind.wav.original-20260201T000000.000000Z").write_bytes(b"backup2")
    (tmp_path / "not_a_backup.txt").write_bytes(b"")
    # Hidden directory: should be skipped.
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "foo.wav.original-20260101T000000.000000Z").write_bytes(b"hidden")

    found = sorted(b.backup_path.name for b in discover_backups(tmp_path))
    assert found == [
        "rain.wav.original-20260101T000000.000000Z",
        "wind.wav.original-20260201T000000.000000Z",
    ]


def test_discover_backups_handles_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    assert list(discover_backups(missing)) == []


# -- clean_backups ----------------------------------------------------------


def _make_backup_at(tmp_path: Path, name: str, stamp: str) -> Path:
    """Build a backup filename for tests. *stamp* may be the legacy second-only
    form or the new ``YYYYMMDDTHHMMSS.ffffff`` form; second-only stamps are
    padded with zero microseconds for compatibility with the post-P1 regex."""
    if "." not in stamp:
        stamp = f"{stamp}.000000"
    path = tmp_path / f"{name}.original-{stamp}Z"
    path.write_bytes(b"backup-bytes")
    return path


def test_clean_backups_dry_run_removes_nothing(tmp_path: Path) -> None:
    old = _make_backup_at(tmp_path, "old.wav", "20240101T000000")
    fresh = _make_backup_at(tmp_path, "fresh.wav", "20260512T000000")

    result = clean_backups(
        tmp_path,
        older_than_days=30,
        dry_run=True,
        now=datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC),
    )

    assert result.dry_run is True
    assert result.scanned == 2
    assert result.removed == 1
    assert result.kept == 1
    assert result.bytes_freed == len(b"backup-bytes")
    # No files actually removed.
    assert old.exists()
    assert fresh.exists()


def test_clean_backups_apply_removes_eligible_backups(tmp_path: Path) -> None:
    old = _make_backup_at(tmp_path, "old.wav", "20240101T000000")
    fresh = _make_backup_at(tmp_path, "fresh.wav", "20260512T000000")

    result = clean_backups(
        tmp_path,
        older_than_days=30,
        dry_run=False,
        now=datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC),
    )

    assert result.removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_clean_backups_older_than_zero_removes_everything(tmp_path: Path) -> None:
    a = _make_backup_at(tmp_path, "a.wav", "20260512T000000")
    b = _make_backup_at(tmp_path, "b.wav", "20260512T120000")
    later = datetime(2026, 5, 13, 0, 0, 0, tzinfo=UTC)

    result = clean_backups(tmp_path, older_than_days=0, dry_run=False, now=later)

    assert result.removed == 2
    assert not a.exists()
    assert not b.exists()


def test_clean_backups_negative_days_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="older_than_days must be 0 or greater"):
        clean_backups(tmp_path, older_than_days=-1)


def test_clean_backups_handles_unwritable_file_gracefully(tmp_path: Path, monkeypatch) -> None:
    """If an unlink raises, the counts back out — the user can re-run and see the failure."""
    backup = _make_backup_at(tmp_path, "stubborn.wav", "20240101T000000")

    original_unlink = Path.unlink

    def boom(self: Path, missing_ok: bool = False) -> None:
        if self == backup:
            raise PermissionError("nope")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", boom)

    result = clean_backups(
        tmp_path,
        older_than_days=0,
        dry_run=False,
        now=datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC),
    )

    assert result.removed == 0
    assert result.kept == 0
    assert result.scanned == 1
    assert backup.exists()


# -- CLI: sfx maintenance clean-backups -------------------------------------


def test_cli_maintenance_clean_backups_dry_run_by_default(tmp_path: Path) -> None:
    backup = _make_backup_at(tmp_path, "old.wav", "20240101T000000")

    result = runner.invoke(
        app,
        ["maintenance", "clean-backups", str(tmp_path), "--older-than-days", "0", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["command"] == "maintenance_clean_backups"
    assert payload["dry_run"] is True
    assert payload["removed"] == 1
    # File still exists.
    assert backup.exists()


def test_cli_maintenance_clean_backups_apply_removes(tmp_path: Path) -> None:
    backup = _make_backup_at(tmp_path, "old.wav", "20240101T000000")

    result = runner.invoke(
        app,
        ["maintenance", "clean-backups", str(tmp_path), "--older-than-days", "0", "--apply", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    assert payload["removed"] == 1
    assert not backup.exists()


def test_cli_maintenance_clean_backups_rejects_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "ghost"
    result = runner.invoke(app, ["maintenance", "clean-backups", str(missing)])
    assert result.exit_code == 1
    assert "path not found" in result.output


# Backup retention sanity: the cutoff math uses the *reference* time so tests
# can pin it. Independently sanity check that the helper applies it correctly
# for a span of days that's clearly older than the cutoff.
def test_clean_backups_cutoff_math(tmp_path: Path) -> None:
    fresh_stamp = (datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC) - timedelta(days=10)).strftime("%Y%m%dT%H%M%S")
    old_stamp = (datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC) - timedelta(days=60)).strftime("%Y%m%dT%H%M%S")
    fresh = _make_backup_at(tmp_path, "fresh.wav", fresh_stamp)
    old = _make_backup_at(tmp_path, "old.wav", old_stamp)

    result = clean_backups(
        tmp_path,
        older_than_days=30,
        dry_run=False,
        now=datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC),
    )

    assert result.removed == 1
    assert fresh.exists()
    assert not old.exists()
