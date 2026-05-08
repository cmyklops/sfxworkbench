"""Audio metadata reader using soundfile (handles 32-bit float, RF64, AIFF, FLAC)."""

import struct
from pathlib import Path

from wavwarden.models import AudioInfo

# Subtype to bit depth mapping
_SUBTYPE_BIT_DEPTH: dict[str, int] = {
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,    # subtype stays "FLOAT" to distinguish from PCM_32
    "DOUBLE": 64,
}


def _walk_riff_chunks(path: Path) -> tuple[bool, bool]:
    """Walk RIFF/RF64 chunks to detect bext and iXML. Returns (has_bext, has_ixml)."""
    has_bext = False
    has_ixml = False
    try:
        with open(path, "rb") as f:
            header = f.read(12)
            if len(header) < 12:
                return False, False
            riff_id, _, wave_id = struct.unpack_from("<4sI4s", header)
            if riff_id not in (b"RIFF", b"RF64") or wave_id != b"WAVE":
                return False, False
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                chunk_id, chunk_size = struct.unpack_from("<4sI", hdr)
                tag = chunk_id.decode("latin-1").rstrip("\x00").strip()
                if tag == "bext":
                    has_bext = True
                elif tag == "iXML":
                    has_ixml = True
                f.seek(chunk_size + (chunk_size % 2), 1)
    except Exception:
        pass
    return has_bext, has_ixml


def read_audio_info(path: Path) -> AudioInfo:
    """Read audio metadata using soundfile (handles 32-bit float, RF64, AIFF, FLAC)."""
    try:
        import soundfile as sf
    except ImportError:
        return AudioInfo(error="soundfile not installed; run: pip install soundfile")

    try:
        info = sf.info(str(path))
    except Exception as e:
        return AudioInfo(error=str(e))

    subtype = info.subtype if hasattr(info, "subtype") else None
    bit_depth = _SUBTYPE_BIT_DEPTH.get(subtype) if subtype else None

    frames = info.frames
    sample_rate = info.samplerate
    duration_s = round(frames / sample_rate, 3) if sample_rate > 0 else None

    has_bext = False
    has_ixml = False
    ext = path.suffix.lower()
    if ext in (".wav", ".w64", ".rf64"):
        has_bext, has_ixml = _walk_riff_chunks(path)

    return AudioInfo(
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        channels=info.channels,
        duration_s=duration_s,
        subtype=subtype,
        has_bext=has_bext,
        has_ixml=has_ixml,
    )
