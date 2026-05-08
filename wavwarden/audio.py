"""Audio metadata readers.

`soundfile` remains the required reader for core audio properties. If the
optional `wavinfo` package is installed, wavwarden also records richer
professional WAV metadata presence flags without making metadata writes.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence
from pathlib import Path

from wavwarden.models import AudioInfo

# Subtype to bit depth mapping
_SUBTYPE_BIT_DEPTH: dict[str, int] = {
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,  # subtype stays "FLOAT" to distinguish from PCM_32
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


def _scope_has_payload(scope: object) -> bool:
    if scope is None:
        return False
    if isinstance(scope, (str, bytes)):
        return bool(scope)
    if isinstance(scope, Mapping):
        return any(_scope_has_payload(value) for value in scope.values())
    if isinstance(scope, Sequence):
        return any(_scope_has_payload(value) for value in scope)
    values = getattr(scope, "__dict__", None)
    if isinstance(values, dict):
        return any(_scope_has_payload(value) for key, value in values.items() if not key.startswith("_"))
    return bool(scope)


def _read_wavinfo_metadata(path: Path) -> dict[str, object]:
    """Read optional extended WAV metadata flags via wavinfo when available."""
    try:
        import wavinfo
    except ImportError:
        return {"metadata_sources": []}

    try:
        reader = wavinfo.WavInfoReader(path)
    except Exception:
        return {"metadata_sources": ["wavinfo_error"]}

    return {
        "has_bext": _scope_has_payload(getattr(reader, "bext", None)),
        "has_ixml": _scope_has_payload(getattr(reader, "ixml", None)),
        "has_riff_info": _scope_has_payload(getattr(reader, "info", None)),
        "has_adm": _scope_has_payload(getattr(reader, "adm", None)),
        "has_cue_markers": _scope_has_payload(getattr(reader, "cues", None)),
        "has_sampler": _scope_has_payload(getattr(reader, "smpl", None)),
        "metadata_sources": ["wavinfo"],
    }


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
    has_riff_info = False
    has_adm = False
    has_cue_markers = False
    has_sampler = False
    metadata_sources = ["soundfile"]
    ext = path.suffix.lower()
    if ext in (".wav", ".w64", ".rf64"):
        has_bext, has_ixml = _walk_riff_chunks(path)
        if has_bext or has_ixml:
            metadata_sources.append("riff_walk")
        wavinfo_metadata = _read_wavinfo_metadata(path)
        has_bext = has_bext or bool(wavinfo_metadata.get("has_bext"))
        has_ixml = has_ixml or bool(wavinfo_metadata.get("has_ixml"))
        has_riff_info = bool(wavinfo_metadata.get("has_riff_info"))
        has_adm = bool(wavinfo_metadata.get("has_adm"))
        has_cue_markers = bool(wavinfo_metadata.get("has_cue_markers"))
        has_sampler = bool(wavinfo_metadata.get("has_sampler"))
        sources = wavinfo_metadata.get("metadata_sources", [])
        if isinstance(sources, list):
            metadata_sources.extend(str(source) for source in sources)

    return AudioInfo(
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        channels=info.channels,
        duration_s=duration_s,
        subtype=subtype,
        has_bext=has_bext,
        has_ixml=has_ixml,
        has_riff_info=has_riff_info,
        has_adm=has_adm,
        has_cue_markers=has_cue_markers,
        has_sampler=has_sampler,
        metadata_sources=metadata_sources,
    )
