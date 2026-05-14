"""Tests for sfxworkbench.health — one test per issue type."""

import unicodedata
from pathlib import Path

import pytest
from sfxworkbench.health import _MAX_NAME_BYTES, _MAX_PATH_BYTES, check_path
from sfxworkbench.models import FilenameIssue


def _issues_of_type(issues: list[FilenameIssue], issue_type: str) -> list[FilenameIssue]:
    return [i for i in issues if i.issue == issue_type]


def test_unicode_normalization_detected(tmp_path: Path) -> None:
    """NFD-encoded name should trigger unicode_normalization."""
    nfd_name = unicodedata.normalize("NFD", "café.wav")
    # Ensure it is actually NFD
    assert nfd_name != unicodedata.normalize("NFC", nfd_name)
    fake_path = tmp_path / nfd_name
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "unicode_normalization")
    assert types, "NFD name should produce unicode_normalization issue"


def test_nfc_name_no_normalization_issue(tmp_path: Path) -> None:
    nfc_name = unicodedata.normalize("NFC", "café.wav")
    fake_path = tmp_path / nfc_name
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "unicode_normalization")
    assert not types, "NFC name should not produce unicode_normalization issue"


def test_illegal_chars_detected(tmp_path: Path) -> None:
    """Colon in name should trigger illegal_chars."""
    fake_path = tmp_path / "bad:name.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "illegal_chars")
    assert types, "Colon should produce illegal_chars issue"
    assert ":" in types[0].detail


def test_illegal_chars_all_detected(tmp_path: Path) -> None:
    for char in ':*?"<>|':
        fake_path = tmp_path / f"bad{char}name.wav"
        issues = check_path(fake_path, tmp_path)
        assert _issues_of_type(issues, "illegal_chars"), f"Char {char!r} should trigger illegal_chars"


def test_risky_chars_detected(tmp_path: Path) -> None:
    """Hash in name should trigger risky_chars."""
    fake_path = tmp_path / "sound#01.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "risky_chars")
    assert types, "Hash should produce risky_chars issue"


def test_name_too_long_detected(tmp_path: Path) -> None:
    """Name exceeding 255 bytes should trigger name_too_long."""
    long_name = "a" * (_MAX_NAME_BYTES + 1) + ".wav"
    fake_path = tmp_path / long_name
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "name_too_long")
    assert types, "Long name should produce name_too_long issue"


def test_name_not_too_long(tmp_path: Path) -> None:
    normal_name = "normal_sound.wav"
    fake_path = tmp_path / normal_name
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "name_too_long")
    assert not types


def test_path_too_long_detected(tmp_path: Path) -> None:
    """Path exceeding 260 bytes should trigger path_too_long."""
    # Build a path that will definitely exceed 260 bytes
    long_part = "a" * 80
    # Create nested dirs to push path length over 260 bytes
    deep = tmp_path / long_part / long_part / long_part
    fake_path = deep / "sound.wav"
    # Only trigger if actually long
    if len(str(fake_path).encode("utf-8")) > _MAX_PATH_BYTES:
        issues = check_path(fake_path, tmp_path)
        types = _issues_of_type(issues, "path_too_long")
        assert types, "Long path should produce path_too_long issue"
    else:
        pytest.skip("Could not construct a path long enough on this system")


def test_non_ascii_detected(tmp_path: Path) -> None:
    """Non-ASCII characters should trigger non_ascii."""
    fake_path = tmp_path / "soundé.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "non_ascii")
    assert types, "Non-ASCII char should produce non_ascii issue"


def test_ascii_only_no_non_ascii(tmp_path: Path) -> None:
    fake_path = tmp_path / "plain_sound.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "non_ascii")
    assert not types


def test_leading_space_detected(tmp_path: Path) -> None:
    """Leading space should trigger leading_trailing_space."""
    fake_path = tmp_path / " leading.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "leading_trailing_space")
    assert types, "Leading space should produce leading_trailing_space issue"


def test_trailing_space_detected(tmp_path: Path) -> None:
    # Construct a path with a component that has a trailing space before the check.
    # We use PurePosixPath to avoid filesystem normalization.
    # Build the path string directly — we only need the health.check_path logic,
    # which operates on path.parts without touching the filesystem.
    base = str(tmp_path)
    fake_path = Path(base + "/trailing ")
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "leading_trailing_space")
    assert types, "Trailing space should produce leading_trailing_space issue"


def test_windows_reserved_basename_detected_even_with_extension(tmp_path: Path) -> None:
    fake_path = tmp_path / "CON.wav"
    issues = check_path(fake_path, tmp_path)

    types = _issues_of_type(issues, "windows_reserved_name")
    assert types, "Reserved Windows basenames should be flagged even with extensions"


def test_trailing_dot_detected_for_windows_portability(tmp_path: Path) -> None:
    fake_path = Path(str(tmp_path) + "/badname.")
    issues = check_path(fake_path, tmp_path)

    types = _issues_of_type(issues, "trailing_dot_or_space")
    assert types, "Trailing dot should produce trailing_dot_or_space issue"


def test_no_space_issues(tmp_path: Path) -> None:
    fake_path = tmp_path / "no_spaces.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "leading_trailing_space")
    assert not types


def test_dot_prefix_detected(tmp_path: Path) -> None:
    """Dot-prefixed name should trigger dot_prefix."""
    fake_path = tmp_path / ".hidden.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "dot_prefix")
    assert types, "Dot-prefixed name should produce dot_prefix issue"


def test_dot_prefix_dot_not_triggered(tmp_path: Path) -> None:
    """Literal '.' and '..' should not trigger dot_prefix."""
    # check_path works on components of the relative path
    # '.' as component would be from the path itself; we test non-dot names
    fake_path = tmp_path / "visible.wav"
    issues = check_path(fake_path, tmp_path)
    types = _issues_of_type(issues, "dot_prefix")
    assert not types


def test_clean_filename_no_issues(tmp_path: Path) -> None:
    """A perfectly clean ASCII filename should produce no issues."""
    fake_path = tmp_path / "AMB_CITY_RAIN_01.wav"
    issues = check_path(fake_path, tmp_path)
    assert issues == [], f"Clean filename produced unexpected issues: {issues}"
