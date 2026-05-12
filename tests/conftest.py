"""Pytest fixtures for sfxworkbench tests."""

import unicodedata
import wave
from pathlib import Path

import pytest
from sfxworkbench.db import get_connection


def _make_tiny_wav(
    path: Path, sample_rate: int = 44100, channels: int = 1, sampwidth: int = 2, nframes: int = 100
) -> None:
    """Create a minimal valid WAV file using stdlib wave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * nframes * channels * sampwidth)


@pytest.fixture
def tmp_library(tmp_path: Path) -> Path:
    """Create a small fake library tree for testing."""
    root = tmp_path / "library"
    root.mkdir()

    # Valid audio files
    _make_tiny_wav(root / "sounds" / "AMB_RAIN_01.wav")
    _make_tiny_wav(root / "sounds" / "SFX_GUNSHOT_01.wav")
    _make_tiny_wav(root / "deep" / "nested" / "folder" / "BOOM.wav")

    # AppleDouble files
    (root / "sounds" / "._AMB_RAIN_01.wav").write_bytes(b"\x00Apple\x00")
    (root / "._DS_Store_hidden").write_bytes(b"\x00Apple\x00")

    # macOS system junk
    (root / ".DS_Store").write_bytes(b"Bud1\x00\x00\x00\x00")
    (root / "sounds" / ".DS_Store").write_bytes(b"Bud1\x00\x00\x00\x00")

    # Waveform cache dir
    wf_dir = root / "_wfCache"
    wf_dir.mkdir()
    (wf_dir / "AMB_RAIN_01.wav.wf").write_bytes(b"\x00" * 64)
    (wf_dir / "SFX_GUNSHOT_01.wav.wf").write_bytes(b"\x00" * 64)

    # macOS zip artifact dir
    macosx_dir = root / "__MACOSX"
    macosx_dir.mkdir()
    (macosx_dir / "._SomeSound.wav").write_bytes(b"\x00Apple\x00")

    # Peak/analysis sidecars
    (root / "sounds" / "AMB_RAIN_01.wav.reapeaks").write_bytes(b"\x00" * 32)
    (root / "sounds" / "SFX_GUNSHOT_01.sfk").write_bytes(b"\x00" * 32)

    # File with illegal char in name (:)
    (root / "sounds" / "bad:name.wav").write_bytes(
        b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x04\x00\x00\x00\x00\x00\x00\x00"
    )

    # File with NFD-encoded name
    nfd_name = unicodedata.normalize("NFD", "café_sound.wav")
    (root / "sounds" / nfd_name).write_bytes(b"\x00" * 8)

    return root


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return path to a fresh test SQLite DB."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    conn.close()
    return db_path
