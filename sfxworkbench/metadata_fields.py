"""Normalized embedded metadata field indexing and the canonical tag-field registry.

This module owns two related but distinct concerns:

1. **DB-ingest helpers** (``MetadataField``, ``read_embedded_metadata_fields``,
   ``replace_metadata_fields``) — read a file's embedded chunks and populate the
   ``metadata_fields`` SQLite table. Consumed by ``scan.py`` and
   ``metadata_write.py``.

2. **Canonical tag-field registry** (``TagField``, ``FIELDS``, ``canonicalize``,
   ``is_multivalue``, ``embedded_keys_for``, ``normalize_value_for_dedup``,
   ``values_equal_for_dedup``) — single source of truth for which SFX-workbench
   field names exist, which aliases they accept (including container-specific
   keys like RIFF ``ikey``), which are multivalue, and how to compare values
   when deduplicating. Consumed by ``tag_plan.py`` and ``tui_data.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


# ---------------------------------------------------------------------------
# Canonical tag-field registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TagField:
    """One canonical sfxworkbench tag field.

    A canonical field is the workbench's preferred name for a logical metadata
    concept (e.g. ``"description"``, ``"keyword"``). Each field carries:

    - ``canonical`` — the canonical name itself.
    - ``aliases`` — accepted user-visible synonyms plus container-specific
      keys (RIFF ``ikey``, ``ignr`` etc.) that should canonicalize to this
      field. Always includes ``canonical``. Lookups are case-insensitive.
    - ``multivalue`` — ``True`` for fields where a file legitimately carries
      multiple distinct values (keywords); ``False`` for single-value fields
      (description, title) where any existing value blocks an additional add.
    - ``embedded_keys`` — ``(namespace, key)`` pairs in the ``metadata_fields``
      SQLite table where existing values for this field can be found. Empty
      tuple for fields that only live in the ``accepted_tags`` table.
    """

    canonical: str
    aliases: tuple[str, ...]
    multivalue: bool
    embedded_keys: tuple[tuple[str, str], ...]


_FIELDS_RAW: tuple[TagField, ...] = (
    TagField(
        canonical="description",
        aliases=("description",),
        multivalue=False,
        embedded_keys=(
            ("bext", "description"),
            ("tag", "description"),
            ("id3", "description"),
            ("vorbis", "description"),
            ("mp4", "description"),
        ),
    ),
    TagField(
        canonical="keyword",
        aliases=("keyword", "keywords", "ikey"),
        multivalue=True,
        embedded_keys=(
            ("riff_info", "ikey"),
            ("tag", "keywords"),
        ),
    ),
    TagField(
        canonical="category",
        aliases=("category", "genre", "ignr"),
        multivalue=False,
        embedded_keys=(
            ("riff_info", "ignr"),
            ("tag", "genre"),
            ("tag", "category"),
        ),
    ),
    TagField(
        canonical="subcategory",
        aliases=("subcategory", "ww:subcategory", "isbj"),
        multivalue=False,
        embedded_keys=(
            ("riff_info", "isbj"),
            ("tag", "ww:subcategory"),
            ("tag", "subcategory"),
        ),
    ),
    TagField(
        canonical="title",
        aliases=("title", "inam"),
        multivalue=False,
        embedded_keys=(
            ("riff_info", "inam"),
            ("tag", "title"),
            ("id3", "title"),
            ("vorbis", "title"),
            ("mp4", "title"),
        ),
    ),
    TagField(
        canonical="comment",
        aliases=("comment", "icmt"),
        multivalue=False,
        embedded_keys=(
            ("riff_info", "icmt"),
            ("tag", "comment"),
            ("id3", "comment"),
            ("vorbis", "comment"),
            ("mp4", "comment"),
        ),
    ),
    TagField(
        canonical="ucs_category",
        aliases=("ucs_category", "ww:ucs_category"),
        multivalue=False,
        embedded_keys=(("tag", "ww:ucs_category"),),
    ),
    TagField(
        canonical="ucs_subcategory",
        aliases=("ucs_subcategory", "ww:ucs_subcategory"),
        multivalue=False,
        embedded_keys=(("tag", "ww:ucs_subcategory"),),
    ),
    TagField(
        canonical="originator",
        aliases=("originator", "organization"),
        multivalue=False,
        embedded_keys=(
            ("bext", "originator"),
            ("tag", "organization"),
        ),
    ),
    TagField(
        canonical="originator_reference",
        aliases=("originator_reference", "encodedby"),
        multivalue=False,
        embedded_keys=(
            ("bext", "originatorreference"),
            ("tag", "encodedby"),
        ),
    ),
    TagField(
        canonical="take_number",
        aliases=("take_number", "ww:take_number"),
        multivalue=False,
        embedded_keys=(("tag", "ww:take_number"),),
    ),
    TagField(
        canonical="channel_position",
        aliases=("channel_position", "ww:channel_position"),
        multivalue=False,
        embedded_keys=(("tag", "ww:channel_position"),),
    ),
)

FIELDS: dict[str, TagField] = {field.canonical: field for field in _FIELDS_RAW}
"""Canonical name → :class:`TagField`. Single source of truth for the registry."""

_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias.lower(): field.canonical for field in _FIELDS_RAW for alias in field.aliases
}


def canonicalize(name: str) -> str:
    """Return the canonical field name for *name*.

    Strips whitespace and matches case-insensitively against every known alias
    (including container-specific RIFF keys). Unknown names pass through
    lowercased so unfamiliar fields still hash consistently downstream.
    """
    normalized = name.strip().lower()
    return _ALIAS_TO_CANONICAL.get(normalized, normalized)


def is_multivalue(canonical: str) -> bool:
    """Return ``True`` if *canonical* names a multivalue field (e.g. keywords)."""
    field = FIELDS.get(canonical)
    return field.multivalue if field is not None else False


def embedded_keys_for(canonical: str) -> tuple[tuple[str, str], ...]:
    """Return the ``(namespace, key)`` pairs for *canonical* in the metadata_fields table."""
    field = FIELDS.get(canonical)
    return field.embedded_keys if field is not None else ()


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_value_for_dedup(value: str) -> str:
    """Return a casefold + whitespace-collapsed form of *value* for dedup comparisons.

    Two values that differ only in casing or internal whitespace are treated as
    the same when deciding whether a new tag would duplicate an existing one.
    Use :func:`values_equal_for_dedup` if you just want a boolean.
    """
    return _WHITESPACE_RE.sub(" ", value).strip().casefold()


def values_equal_for_dedup(a: str, b: str) -> bool:
    """Return ``True`` if *a* and *b* match after dedup-normalization."""
    return normalize_value_for_dedup(a) == normalize_value_for_dedup(b)
