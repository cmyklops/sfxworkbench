"""Tests for wavwarden.audio — AudioInfo from real WAV files."""

import struct
import sys
import types
import wave
from pathlib import Path

import pytest
from wavwarden.models import AudioInfo


def _make_wav(
    path: Path,
    sample_rate: int = 44100,
    channels: int = 1,
    sampwidth: int = 2,
    nframes: int = 100,
) -> Path:
    """Create a minimal valid WAV file using stdlib wave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * nframes * channels * sampwidth)
    return path


def _make_wav_with_bext(path: Path) -> Path:
    """Create a WAV with a minimal bext chunk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal bext chunk (602 bytes of zeros)
    bext_data = b"bext" + struct.pack("<I", 602) + b"\x00" * 602
    # fmt chunk
    fmt_data = b"fmt " + struct.pack("<I", 16) + struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    # data chunk
    data_chunk = b"data" + struct.pack("<I", 4) + b"\x00" * 4
    # RIFF wrapper
    inner = fmt_data + bext_data + data_chunk
    riff = b"RIFF" + struct.pack("<I", len(inner) + 4) + b"WAVE" + inner
    path.write_bytes(riff)
    return path


def _make_wav_with_malformed_side_chunk(path: Path) -> Path:
    """Create a WAV that Finder-like readers tolerate but libsndfile may reject."""
    path.parent.mkdir(parents=True, exist_ok=True)
    bext_data = b"bext" + struct.pack("<I", 602) + b"\x00" * 602
    malformed = b"\x00mix" + struct.pack("<I", 4) + b"side"
    fmt_data = b"fmt " + struct.pack("<I", 16) + struct.pack("<HHIIHH", 1, 2, 48000, 192000, 4, 16)
    data_chunk = b"data" + struct.pack("<I", 48000 * 4) + (b"\x00" * (48000 * 4))
    inner = bext_data + malformed + fmt_data + data_chunk
    riff = b"RIFF" + struct.pack("<I", len(inner) + 4) + b"WAVE" + inner
    path.write_bytes(riff)
    return path


def test_read_audio_info_basic(tmp_path: Path) -> None:
    """AudioInfo should return correct metadata for a simple 44100 Hz mono 16-bit WAV."""
    wav = _make_wav(tmp_path / "test.wav", sample_rate=44100, channels=1, sampwidth=2, nframes=44100)

    from wavwarden.audio import read_audio_info

    info = read_audio_info(wav)

    # If soundfile is not installed, we get an error — skip gracefully
    if info.error and "soundfile not installed" in info.error:
        pytest.skip("soundfile not installed")

    assert info.error is None, f"Unexpected error: {info.error}"
    assert info.sample_rate == 44100
    assert info.channels == 1
    assert info.duration_s is not None
    assert abs(info.duration_s - 1.0) < 0.01, f"Expected ~1.0s, got {info.duration_s}"


def test_read_audio_info_falls_back_for_malformed_side_chunk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wav = _make_wav_with_malformed_side_chunk(tmp_path / "malformed-side.wav")

    class FakeSoundFile:
        @staticmethod
        def info(path: str):
            raise RuntimeError("Error in WAV file. No 'data' chunk marker.")

    monkeypatch.setitem(sys.modules, "soundfile", FakeSoundFile)

    from wavwarden.audio import read_audio_info

    info = read_audio_info(wav)

    assert info.error is None
    assert info.sample_rate == 48000
    assert info.channels == 2
    assert info.bit_depth == 16
    assert info.duration_s == 1.0
    assert info.has_bext is True
    assert "riff_fallback" in info.metadata_sources


def test_read_audio_info_stereo(tmp_path: Path) -> None:
    wav = _make_wav(tmp_path / "stereo.wav", sample_rate=48000, channels=2, sampwidth=2, nframes=100)

    from wavwarden.audio import read_audio_info

    info = read_audio_info(wav)

    if info.error and "soundfile not installed" in info.error:
        pytest.skip("soundfile not installed")

    assert info.error is None
    assert info.sample_rate == 48000
    assert info.channels == 2


def test_read_audio_info_24bit(tmp_path: Path) -> None:
    wav = _make_wav(tmp_path / "24bit.wav", sample_rate=96000, channels=1, sampwidth=3, nframes=100)

    from wavwarden.audio import read_audio_info

    info = read_audio_info(wav)

    if info.error and "soundfile not installed" in info.error:
        pytest.skip("soundfile not installed")

    assert info.error is None
    assert info.bit_depth == 24
    assert info.sample_rate == 96000


def test_read_audio_info_bext_detected(tmp_path: Path) -> None:
    """WAV with bext chunk should have has_bext=True."""
    wav = _make_wav_with_bext(tmp_path / "bext.wav")

    from wavwarden.audio import read_audio_info

    info = read_audio_info(wav)

    if info.error and "soundfile not installed" in info.error:
        pytest.skip("soundfile not installed")

    # Even if soundfile errors, the RIFF walk should still have set has_bext via our code
    # But if soundfile errors, we return early. So only check if no error.
    if info.error is None:
        assert info.has_bext is True, "Should detect bext chunk"


def test_read_audio_info_no_bext(tmp_path: Path) -> None:
    wav = _make_wav(tmp_path / "no_bext.wav")

    from wavwarden.audio import read_audio_info

    info = read_audio_info(wav)

    if info.error and "soundfile not installed" in info.error:
        pytest.skip("soundfile not installed")

    if info.error is None:
        assert info.has_bext is False
        assert info.has_ixml is False


def test_read_audio_info_nonexistent_file(tmp_path: Path) -> None:
    """Non-existent file should return an AudioInfo with an error field."""
    from wavwarden.audio import read_audio_info

    info = read_audio_info(tmp_path / "nonexistent.wav")

    if info.error and "soundfile not installed" in info.error:
        pytest.skip("soundfile not installed")

    assert info.error is not None, "Non-existent file should produce an error"
    assert info.sample_rate is None


def test_audio_info_model_defaults() -> None:
    """AudioInfo Pydantic model should have correct defaults."""
    info = AudioInfo()
    assert info.sample_rate is None
    assert info.bit_depth is None
    assert info.channels is None
    assert info.duration_s is None
    assert info.subtype is None
    assert info.has_bext is False
    assert info.has_ixml is False
    assert info.has_riff_info is False
    assert info.has_adm is False
    assert info.has_cue_markers is False
    assert info.has_sampler is False
    assert info.metadata_sources == []
    assert info.error is None


def test_read_audio_info_uses_optional_wavinfo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wav = _make_wav(tmp_path / "metadata.wav")

    class FakeWavInfoReader:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.bext = types.SimpleNamespace(description="")
            self.ixml = types.SimpleNamespace(project="Demo")
            self.info = {"INAM": "Door close"}
            self.adm = None
            self.cues = [{"label": "start"}]
            self.smpl = types.SimpleNamespace(loops=[])

    monkeypatch.setitem(sys.modules, "wavinfo", types.SimpleNamespace(WavInfoReader=FakeWavInfoReader))

    from wavwarden.audio import read_audio_info

    info = read_audio_info(wav)

    if info.error and "soundfile not installed" in info.error:
        pytest.skip("soundfile not installed")

    assert info.error is None
    assert info.has_ixml is True
    assert info.has_riff_info is True
    assert info.has_cue_markers is True
    assert info.has_adm is False
    assert info.has_sampler is False
    assert "wavinfo" in info.metadata_sources
