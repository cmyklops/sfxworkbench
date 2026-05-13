"""Tests for sfxworkbench.junk shared module."""

import sys
from pathlib import Path

import pytest
from sfxworkbench import junk


def test_apple_double_detection() -> None:
    assert junk.is_apple_double("._foo.wav")
    assert junk.is_apple_double("._.DS_Store")
    assert not junk.is_apple_double(".DS_Store")
    assert not junk.is_apple_double("foo.wav")


def test_is_junk_file_apple_double_overrides_audio_guard() -> None:
    """._foo.wav must be junk even though .wav is in AUDIO_EXTENSIONS."""
    assert junk.is_junk_file(Path("/x/._anything.wav"))
    assert junk.is_junk_file(Path("/x/._anything.aiff"))


def test_is_junk_file_protects_real_audio() -> None:
    assert not junk.is_junk_file(Path("/x/real.wav"))
    assert not junk.is_junk_file(Path("/x/real.aiff"))
    assert not junk.is_junk_file(Path("/x/real.flac"))


def test_is_junk_file_recognizes_known_junk() -> None:
    # .DS_Store is platform-conditional; covered separately below.
    assert junk.is_junk_file(Path("/x/Thumbs.db"))
    assert junk.is_junk_file(Path("/x/foo.reapeaks"))
    assert junk.is_junk_file(Path("/x/foo.sfk"))
    assert junk.is_junk_file(Path("/x/foo.wf"))


def test_ds_store_excluded_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """``.DS_Store`` is futile to clean on macOS — Finder regenerates it the
    moment the enclosing folder is reopened. The cleanup pipeline should
    skip it on Darwin so users don't see meaningless churn.
    """
    monkeypatch.setattr(sys, "platform", "darwin")
    assert not junk.is_junk_file(Path("/x/.DS_Store"))


def test_ds_store_still_junk_on_linux_and_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux / Windows / WSL the file is leftover from a prior macOS mount
    and worth removing — no Finder around to regenerate it.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    assert junk.is_junk_file(Path("/x/.DS_Store"))
    monkeypatch.setattr(sys, "platform", "win32")
    assert junk.is_junk_file(Path("/x/.DS_Store"))


def test_is_junk_dir() -> None:
    assert junk.is_junk_dir(Path("/x/_wfCache"))
    assert junk.is_junk_dir(Path("/x/__MACOSX"))
    assert not junk.is_junk_dir(Path("/x/sounds"))


def test_is_inside_junk_dir() -> None:
    assert junk.is_inside_junk_dir(Path("/x/_wfCache/foo.wav"))
    assert junk.is_inside_junk_dir(Path("/x/__MACOSX/sub/foo.wav"))
    assert not junk.is_inside_junk_dir(Path("/x/sounds/foo.wav"))
