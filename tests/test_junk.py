"""Tests for sfxworkbench.junk shared module."""

from pathlib import Path

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
    assert junk.is_junk_file(Path("/x/.DS_Store"))
    assert junk.is_junk_file(Path("/x/Thumbs.db"))
    assert junk.is_junk_file(Path("/x/foo.reapeaks"))
    assert junk.is_junk_file(Path("/x/foo.sfk"))
    assert junk.is_junk_file(Path("/x/foo.wf"))


def test_is_junk_dir() -> None:
    assert junk.is_junk_dir(Path("/x/_wfCache"))
    assert junk.is_junk_dir(Path("/x/__MACOSX"))
    assert not junk.is_junk_dir(Path("/x/sounds"))


def test_is_inside_junk_dir() -> None:
    assert junk.is_inside_junk_dir(Path("/x/_wfCache/foo.wav"))
    assert junk.is_inside_junk_dir(Path("/x/__MACOSX/sub/foo.wav"))
    assert not junk.is_inside_junk_dir(Path("/x/sounds/foo.wav"))
