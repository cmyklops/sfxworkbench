"""ExifTool-style sibling-file backup helpers.

The pattern: before a destructive write to ``foo.wav``, copy it to a sibling
``foo.wav.original-<YYYYMMDDTHHMMSS.ffffffZ>`` file. The backup lives in the
same directory as the original (so users can see it next to the working copy),
is microsecond-stamped (so even back-to-back writes in the same second don't
clobber each other), and can be garbage collected after a configurable
retention window via :func:`clean_backups`.

Compared to the existing ``backup_dir``-based scheme in ``metadata_write``,
sibling backups:
- Stay next to the file, so a user reviewing one folder sees both the current
  state and the backup without spelunking elsewhere.
- Survive ``mv`` of the file's parent directory (the backup tags along).
- Are trivial to clean up with a single recursive sweep (``clean_backups``).

This module is the standalone backup primitive. Integration with
:func:`sfxworkbench.metadata_write.apply_metadata_write_plan`,
``sfx rename --apply``, and ``sfx organize --apply`` follows in a future PR;
:class:`sfxworkbench.config.BackupConfig` already carries the policy knobs
(``enabled``, ``retain_days``) so that plumbing is mechanical.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sfxworkbench.path_safety import path_exists_windows

# Matches the ``<name>.original-YYYYMMDDTHHMMSS.ffffffZ`` suffix added by
# :func:`make_original_backup`. The fractional ``.ffffff`` portion is required
# (microseconds — six digits) so two backups taken in the same wall-clock second
# can't collide. Groups: 1 = original-filename stem; 2 = ISO timestamp portion
# (without the trailing ``Z``).
_BACKUP_SUFFIX_RE = re.compile(r"^(?P<original>.+)\.original-(?P<stamp>\d{8}T\d{6}\.\d{6})Z$")


@dataclass(frozen=True)
class OriginalBackup:
    """One discovered sibling backup file."""

    backup_path: Path
    """Path to the ``<name>.original-<stamp>Z`` file itself."""

    original_path: Path
    """Path to the file the backup was made from. May or may not still exist."""

    created_at: datetime
    """UTC timestamp parsed from the backup filename."""


def _now_stamp() -> str:
    """Return a UTC timestamp body (``20260512T143022.123456``) — no trailing ``Z``.

    Microsecond precision is required: ``make_original_backup`` writes via
    ``shutil.copy2`` which silently overwrites the destination, so two backups
    taken in the same wall-clock second would otherwise clobber each other and
    invalidate older apply-log undo paths.

    The ``Z`` is appended by :func:`backup_path_for` so callers that supply an
    explicit *stamp* don't have to remember to include it.
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f")


def backup_path_for(path: Path, *, stamp: str | None = None) -> Path:
    """Return the sibling backup path that would be produced for *path*.

    Pure function — does not touch the filesystem. Useful for callers that
    want to record the planned backup target before actually creating it.
    """
    suffix = stamp if stamp is not None else _now_stamp()
    return path.with_name(f"{path.name}.original-{suffix}Z")


def make_original_backup(path: Path, *, stamp: str | None = None) -> Path:
    """Create a ``<path>.original-<UTC ISO stamp>`` sibling and return its path.

    Uses :func:`shutil.copy2` so file mode and mtime are preserved. The
    timestamp portion includes microseconds (``%f``), which is collision-safe
    against repeated writes within the same wall-clock second — important
    because ``shutil.copy2`` silently overwrites the destination, so two
    backups racing to the same path would clobber the first. Callers that
    need predictable filenames (tests, fixtures) can pass an explicit *stamp*.

    Raises :class:`FileNotFoundError` if *path* does not exist; ``shutil``
    raises its own errors on permission / disk-full conditions.
    """
    if not path.exists():
        raise FileNotFoundError(f"cannot back up missing file: {path}")
    target = backup_path_for(path, stamp=stamp)
    if path_exists_windows(target):
        stem = target.stem
        suffix = target.suffix
        parent = target.parent
        index = 1
        while path_exists_windows(target):
            target = parent / f"{stem}__{index}{suffix}"
            index += 1
    shutil.copy2(path, target)
    return target


def parse_backup_filename(backup_path: Path) -> OriginalBackup | None:
    """Return an :class:`OriginalBackup` for *backup_path* if its name matches the pattern.

    Returns ``None`` when *backup_path* does not look like a backup produced by
    :func:`make_original_backup`. The pattern is anchored on the trailing
    ``.original-<stamp>Z`` suffix, so files that accidentally contain that
    substring earlier in their name are still rejected.
    """
    match = _BACKUP_SUFFIX_RE.match(backup_path.name)
    if match is None:
        return None
    stamp = match.group("stamp")
    try:
        created_at = datetime.strptime(stamp, "%Y%m%dT%H%M%S.%f").replace(tzinfo=UTC)
    except ValueError:
        return None
    return OriginalBackup(
        backup_path=backup_path,
        original_path=backup_path.with_name(match.group("original")),
        created_at=created_at,
    )


def discover_backups(root: Path) -> Iterator[OriginalBackup]:
    """Yield every ``.original-<stamp>Z`` sibling backup under *root* (recursive).

    Hidden directories (``.git``, ``.venv``, etc.) are skipped so the sweep
    doesn't wander into developer tooling. Files that don't match the backup
    naming pattern are ignored. Symlinks are not followed.
    """
    if not root.exists():
        return
    for candidate in root.rglob("*.original-*Z"):
        if any(part.startswith(".") for part in candidate.relative_to(root).parts[:-1]):
            continue
        if candidate.is_symlink() or not candidate.is_file():
            continue
        parsed = parse_backup_filename(candidate)
        if parsed is not None:
            yield parsed


@dataclass
class CleanBackupsResult:
    """Outcome of a :func:`clean_backups` sweep."""

    scanned: int = 0
    removed: int = 0
    kept: int = 0
    bytes_freed: int = 0
    dry_run: bool = True
    removed_paths: list[Path] | None = None

    def __post_init__(self) -> None:
        if self.removed_paths is None:
            self.removed_paths = []


def clean_backups(
    root: Path,
    *,
    older_than_days: int,
    dry_run: bool = True,
    now: datetime | None = None,
) -> CleanBackupsResult:
    """Remove ``.original-<stamp>Z`` backups under *root* older than the cutoff.

    Parameters
    ----------
    root:
        Tree to sweep. Missing or non-directory paths produce an empty result.
    older_than_days:
        Backups whose timestamp is older than this many days are eligible for
        deletion. ``0`` deletes every discovered backup (useful for tests).
    dry_run:
        When ``True`` (default), no files are unlinked; the result still
        reports what *would* be removed so the caller can show a preview.
    now:
        Reference time used to compute the cutoff. Defaults to current UTC.
        Injectable for tests.
    """
    if older_than_days < 0:
        raise ValueError("older_than_days must be 0 or greater")
    reference = now if now is not None else datetime.now(UTC)
    cutoff = reference - timedelta(days=older_than_days)
    result = CleanBackupsResult(dry_run=dry_run)
    assert result.removed_paths is not None  # mypy hint
    for backup in discover_backups(root):
        result.scanned += 1
        if backup.created_at > cutoff:
            result.kept += 1
            continue
        size = backup.backup_path.stat().st_size if backup.backup_path.exists() else 0
        result.bytes_freed += size
        result.removed_paths.append(backup.backup_path)
        result.removed += 1
        if not dry_run:
            try:
                backup.backup_path.unlink()
            except OSError:
                # Surface via the count; caller can re-scan if needed.
                result.removed -= 1
                result.bytes_freed -= size
                result.removed_paths.pop()
    return result
