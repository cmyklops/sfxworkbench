"""Normalized embedded metadata field indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from sfxworkbench.models import AudioInfo


@dataclass(frozen=True)
class MetadataField:
    namespace: str
    key: str
    value: str
    source: str


def _append_value(fields: list[MetadataField], namespace: str, key: str, value: object, source: str) -> None:
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            _append_value(fields, namespace, key, item, source)
        return
    text = str(value).strip()
    if not text:
        return
    fields.append(MetadataField(namespace=namespace, key=key, value=text, source=source))


def read_embedded_metadata_fields(path: Path, audio_info: AudioInfo | None = None) -> list[MetadataField]:
    """Read normalized embedded metadata values from supported containers.

    This is best-effort read-only evidence. If optional readers or malformed
    chunks fail, the caller still keeps the main scan result.
    """
    extension = path.suffix.lower()
    fields: list[MetadataField] = []
    if extension in {".wav", ".rf64"}:
        try:
            from sfxworkbench.metadata_write import read_bext_core_fields, read_riff_info_fields

            if audio_info is None or audio_info.has_bext:
                for key, value in read_bext_core_fields(path).items():
                    _append_value(fields, "bext", key, value, "riff")
            if audio_info is None or audio_info.has_riff_info:
                for key, value in read_riff_info_fields(path).items():
                    _append_value(fields, "riff_info", key, value, "riff")
        except Exception:
            pass
    elif extension in {".mp3", ".flac", ".ogg", ".opus", ".m4a"}:
        try:
            from sfxworkbench.metadata_write import MUTAGEN_FIELD_MAP_BY_EXTENSION, read_mutagen_fields

            keys = sorted({target_key for _, target_key in MUTAGEN_FIELD_MAP_BY_EXTENSION.get(extension, {}).values()})
            for key, value in read_mutagen_fields(path, keys).items():
                _append_value(fields, "tag", key, value, "mutagen")
        except Exception:
            pass
    return fields


def replace_metadata_fields(
    conn: Connection,
    *,
    file_id: int,
    path: Path,
    audio_info: AudioInfo | None = None,
    updated_at: str,
) -> None:
    """Replace normalized metadata fields for one indexed file."""
    conn.execute("DELETE FROM metadata_fields WHERE file_id = ?", (file_id,))
    fields = read_embedded_metadata_fields(path, audio_info=audio_info)
    if not fields:
        return
    conn.executemany(
        """
        INSERT OR IGNORE INTO metadata_fields (
            file_id, namespace, key, value, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(file_id, item.namespace, item.key, item.value, item.source, updated_at) for item in fields],
    )
