"""Report-only tag suggestions from filename, path, and group evidence.

This module is Phase B of the metadata tagging plan in
``docs/METADATA_TAGGING.md``. It is a pure suggestor: it never writes to audio
files, never mutates the filesystem, and never modifies the SQLite index.
Suggestions are produced as data so a future ``sfx tag review`` / ``sfx tag
apply`` flow can act on them.

Each suggestion carries ``field``, ``value``, ``source``, ``method``,
``confidence``, and ``evidence`` so the reviewer can reason about provenance.
The same field can receive multiple suggestions from different sources; the
reviewer (human or future automated step) chooses which to apply.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import get_connection
from wavwarden.groups import audit_related_groups
from wavwarden.models import (
    RelatedSoundFile,
    RelatedSoundGroup,
    TagSuggestion,
    TagSuggestionEntry,
    TagSuggestionReport,
    TagSuggestionSummary,
)
from wavwarden.ucs import normalize_stem, parse_ucs_stem

console = Console()

# Confidence anchors. Tuned so group-derived evidence outranks raw filename
# guesses, and UCS structure outranks unstructured filename heuristics. Values
# are deliberate floats so a future UCS catalog match can sit at 0.95 above the
# 0.75 heuristic.
_CONFIDENCE_UCS_HEURISTIC = 0.75
_CONFIDENCE_GROUP = 0.85
_CONFIDENCE_FILENAME_ABBREVIATION = 0.65
_CONFIDENCE_FILENAME_TAKE = 0.60
_CONFIDENCE_FILENAME_DESCRIPTION = 0.55
_CONFIDENCE_PATH = 0.50

# Common SFX abbreviations. Conservative list — only expand when the token is
# unambiguous. Falls back to the original token if not in the dict.
_ABBREVIATIONS: dict[str, str] = {
    "AMB": "Ambience",
    "AMBI": "Ambience",
    "BG": "Background",
    "BGN": "Background",
    "DSGN": "Designed",
    "FOLEY": "Foley",
    "FX": "Effect",
    "IMP": "Impact",
    "IMPCT": "Impact",
    "MUS": "Music",
    "SFX": "Sound Effect",
    "VOX": "Vocal",
    "WHSH": "Whoosh",
}

# Channel-marker normalization (markers come from groups.py uppercased).
_CHANNEL_LABELS: dict[str, str] = {
    "L": "Left",
    "LEFT": "Left",
    "R": "Right",
    "RIGHT": "Right",
    "MID": "Mid",
    "SIDE": "Side",
    "MS": "Mid-Side",
    "MONO": "Mono",
    "STEREO": "Stereo",
    "ORTF": "ORTF",
    "XY": "XY",
}

# Folder names with no descriptive content — duplicated from organize.py rather
# than imported to avoid coupling reporting to organization internals.
_LOW_VALUE_FOLDER_NAMES: frozenset[str] = frozenset(
    {
        "audio",
        "audios",
        "content",
        "contents",
        "designed",
        "file",
        "files",
        "mono",
        "sample",
        "samples",
        "sound",
        "sounds",
        "source",
        "sources",
        "stereo",
        "wav",
        "wave",
        "waves",
        "wavs",
    }
)

_SEPARATOR_RE = re.compile(r"[\s._\-]+")
_TRAILING_NUMBER_RE = re.compile(
    r"^(?P<base>.+?)(?:[\s._\-]*(?:take|tk)?[\s._\-]*)?(?P<number>\d{1,4})$",
    re.IGNORECASE,
)
_LEADING_SORT_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-_.\s]+(.+?)\s*$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _confidence_bucket(confidence: float) -> str:
    if confidence < 0.5:
        return "lo"
    if confidence < 0.8:
        return "mid"
    return "hi"


def _tokenize(text: str) -> list[str]:
    """Split a stem on common separators, drop empty tokens."""
    return [token for token in _SEPARATOR_RE.split(text) if token]


def _title_case_token(token: str) -> str:
    """Title-case a token while expanding known SFX abbreviations.

    Returns the abbreviation expansion when present, otherwise a normal
    Title-Case form. Pure-numeric tokens are returned unchanged so a take
    number like ``"01"`` survives the description.
    """
    if not token:
        return token
    if token.isdigit():
        return token
    upper = token.upper()
    if upper in _ABBREVIATIONS:
        return _ABBREVIATIONS[upper]
    return token[:1].upper() + token[1:].lower()


def _strip_take_suffix(tokens: list[str]) -> tuple[list[str], str | None]:
    """If the last token is a bare integer or ``take_NN``, return the take.

    Returns ``(tokens_without_take, take_number_str_or_None)``.
    """
    if not tokens:
        return tokens, None
    last = tokens[-1]
    if last.isdigit() and len(last) <= 4:
        return tokens[:-1], last
    take_match = re.fullmatch(r"(?:take|tk)[-_]?(\d{1,4})", last, re.IGNORECASE)
    if take_match:
        return tokens[:-1], take_match.group(1)
    return tokens, None


def _format_description(tokens: list[str]) -> str:
    return " ".join(_title_case_token(token) for token in tokens if token)


def _is_meaningful_folder(name: str) -> bool:
    stripped = name.strip()
    if not stripped:
        return False
    if stripped.lower() in _LOW_VALUE_FOLDER_NAMES:
        return False
    if stripped.isdigit():
        return False
    if _LEADING_SORT_PREFIX_RE.match(stripped):
        # "01_Ambience" → still meaningful once the prefix is stripped, but the
        # raw form should not be emitted; the path suggestor strips the prefix
        # before emitting.
        return True
    return True


def _strip_leading_sort_prefix(name: str) -> str:
    match = _LEADING_SORT_PREFIX_RE.match(name)
    if match:
        return match.group(1).strip()
    return name.strip()


# ---------------------------------------------------------------------------
# Individual suggestors. Each takes pure data and returns suggestions only.
# ---------------------------------------------------------------------------


def suggest_from_ucs_stem(stem: str) -> list[TagSuggestion]:
    """Emit ``category``/``subcategory``/``description``/``take_number`` from a UCS-named stem."""
    parsed = parse_ucs_stem(stem)
    if not parsed.is_ucs:
        return []

    suggestions: list[TagSuggestion] = []
    evidence = [stem]

    if parsed.category:
        suggestions.append(
            TagSuggestion(
                field="category",
                value=parsed.category,
                source="ucs_stem",
                method="ucs_heuristic",
                confidence=_CONFIDENCE_UCS_HEURISTIC,
                evidence=evidence,
            )
        )
    if parsed.subcategory:
        suggestions.append(
            TagSuggestion(
                field="subcategory",
                value=parsed.subcategory,
                source="ucs_stem",
                method="ucs_heuristic",
                confidence=_CONFIDENCE_UCS_HEURISTIC,
                evidence=evidence,
            )
        )

    # Description: title-cased subcategory + non-numeric remainder tokens.
    description_tokens: list[str] = []
    if parsed.subcategory:
        description_tokens.append(parsed.subcategory)
    take: str | None = None
    if parsed.remainder:
        remainder_tokens = _tokenize(parsed.remainder)
        remainder_tokens, take = _strip_take_suffix(remainder_tokens)
        description_tokens.extend(remainder_tokens)
    description_value = _format_description(description_tokens)
    if description_value:
        suggestions.append(
            TagSuggestion(
                field="description",
                value=description_value,
                source="ucs_stem",
                method="ucs_heuristic",
                confidence=_CONFIDENCE_UCS_HEURISTIC,
                evidence=evidence,
            )
        )
    if take is not None:
        suggestions.append(
            TagSuggestion(
                field="take_number",
                value=take,
                source="ucs_stem",
                method="ucs_heuristic",
                confidence=_CONFIDENCE_UCS_HEURISTIC,
                evidence=evidence,
            )
        )
    return suggestions


def suggest_from_filename(stem: str, *, skip_description: bool = False) -> list[TagSuggestion]:
    """Emit ``description`` and ``take_number`` for non-UCS filenames.

    ``skip_description`` suppresses the description suggestion when a higher
    confidence source (UCS or group) has already produced one — but the take
    number is still useful as corroboration.
    """
    suggestions: list[TagSuggestion] = []
    if not stem:
        return suggestions

    tokens = _tokenize(stem)
    if not tokens:
        return suggestions

    tokens_no_take, take = _strip_take_suffix(tokens)

    if take is not None:
        suggestions.append(
            TagSuggestion(
                field="take_number",
                value=take,
                source="filename",
                method="trailing_number",
                confidence=_CONFIDENCE_FILENAME_TAKE,
                evidence=[stem],
            )
        )

    if skip_description:
        return suggestions

    has_abbreviation = any(token.upper() in _ABBREVIATIONS for token in tokens_no_take)
    description_value = _format_description(tokens_no_take)
    if description_value:
        suggestions.append(
            TagSuggestion(
                field="description",
                value=description_value,
                source="filename",
                method="abbreviation_expansion" if has_abbreviation else "title_case",
                confidence=(
                    _CONFIDENCE_FILENAME_ABBREVIATION if has_abbreviation else _CONFIDENCE_FILENAME_DESCRIPTION
                ),
                evidence=[stem],
            )
        )
    return suggestions


def suggest_from_path(file_path: Path, root: Path) -> list[TagSuggestion]:
    """Emit one ``description`` suggestion per meaningful parent folder."""
    try:
        relative = file_path.resolve().relative_to(root.resolve())
    except ValueError:
        return []

    suggestions: list[TagSuggestion] = []
    parent_parts = relative.parts[:-1]  # drop the filename
    for raw_name in parent_parts:
        if not _is_meaningful_folder(raw_name):
            continue
        cleaned = _strip_leading_sort_prefix(raw_name)
        if cleaned.lower() in _LOW_VALUE_FOLDER_NAMES:
            continue
        tokens = _tokenize(cleaned)
        value = _format_description(tokens)
        if not value:
            continue
        suggestions.append(
            TagSuggestion(
                field="description",
                value=value,
                source="path",
                method="folder_chain",
                confidence=_CONFIDENCE_PATH,
                evidence=[raw_name],
            )
        )
    return suggestions


def suggest_from_group(file_in_group: RelatedSoundFile, group: RelatedSoundGroup) -> list[TagSuggestion]:
    """Emit suggestions for a file that belongs to a related sound group."""
    suggestions: list[TagSuggestion] = []
    evidence = [
        f"group:{group.group_id}",
        f"reason:{group.reason}",
        f"inferred_stem:{group.inferred_stem}",
    ]

    description_value = _format_description(_tokenize(group.inferred_stem))
    if description_value:
        suggestions.append(
            TagSuggestion(
                field="description",
                value=description_value,
                source="group",
                method="group_inferred_stem",
                confidence=_CONFIDENCE_GROUP,
                evidence=evidence,
            )
        )

    marker = file_in_group.marker
    if marker is None:
        return suggestions

    if group.reason == "channel_set":
        label = _CHANNEL_LABELS.get(marker.upper(), marker)
        suggestions.append(
            TagSuggestion(
                field="channel_position",
                value=label,
                source="group",
                method="channel_marker",
                confidence=_CONFIDENCE_GROUP,
                evidence=evidence + [f"marker:{marker}"],
            )
        )
    elif group.reason == "numbered_sequence" and marker.isdigit():
        suggestions.append(
            TagSuggestion(
                field="take_number",
                value=marker,
                source="group",
                method="numbered_sequence_marker",
                confidence=_CONFIDENCE_GROUP,
                evidence=evidence + [f"marker:{marker}"],
            )
        )
    return suggestions


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class _GroupIndex:
    """Map ``path -> (group, RelatedSoundFile)`` for fast lookup."""

    by_path: dict[str, tuple[RelatedSoundGroup, RelatedSoundFile]] = field(default_factory=dict)


def _build_group_index(root: Path, db_path: Path) -> _GroupIndex:
    related = audit_related_groups(root, db_path=db_path, min_files=2, limit=0)
    index = _GroupIndex()
    for group in related.groups:
        for member in group.files:
            index.by_path[member.path] = (group, member)
    return index


def _load_files(root: Path, db_path: Path):
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT id, path, filename, stem, size_bytes, mtime, md5
        FROM files
        WHERE (path = ? OR path LIKE ?)
          AND scan_error IS NULL
        ORDER BY path
        """,
        (str(root), str(root) + "/%"),
    ).fetchall()
    conn.close()
    return rows


def build_tag_suggestion_report(
    root: Path,
    db_path: Path,
    min_confidence: float = 0.0,
    limit: int = 200,
) -> TagSuggestionReport:
    """Walk the index for files under ``root`` and produce per-file suggestions."""
    if min_confidence < 0 or min_confidence > 1:
        raise ValueError("--min-confidence must be between 0 and 1")
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")

    root = root.resolve()
    rows = _load_files(root, db_path)
    group_index = _build_group_index(root, db_path)

    entries: list[TagSuggestionEntry] = []
    by_source: dict[str, int] = {}
    by_field: dict[str, int] = {}
    by_bucket: dict[str, int] = {}
    files_with_suggestions = 0
    total_suggestions = 0

    for row in rows:
        path = Path(row["path"])
        stem_raw = row["stem"] or path.stem
        stem = normalize_stem(stem_raw)

        ucs_suggestions = suggest_from_ucs_stem(stem)
        has_ucs_description = any(s.field == "description" for s in ucs_suggestions)

        group_match = group_index.by_path.get(str(path))
        group_suggestions: list[TagSuggestion] = []
        if group_match is not None:
            group, member = group_match
            group_suggestions = suggest_from_group(member, group)
        has_group_description = any(s.field == "description" for s in group_suggestions)

        # Skip filename description when a higher-confidence source already
        # produced one. Keep filename's take_number — it corroborates.
        skip_filename_description = has_ucs_description or has_group_description
        filename_suggestions = suggest_from_filename(stem, skip_description=skip_filename_description)

        path_suggestions = suggest_from_path(path, root)

        all_suggestions = ucs_suggestions + group_suggestions + filename_suggestions + path_suggestions
        if min_confidence > 0:
            all_suggestions = [s for s in all_suggestions if s.confidence >= min_confidence]
        if not all_suggestions:
            continue

        files_with_suggestions += 1
        total_suggestions += len(all_suggestions)
        for suggestion in all_suggestions:
            by_source[suggestion.source] = by_source.get(suggestion.source, 0) + 1
            by_field[suggestion.field] = by_field.get(suggestion.field, 0) + 1
            bucket = _confidence_bucket(suggestion.confidence)
            by_bucket[bucket] = by_bucket.get(bucket, 0) + 1

        entries.append(
            TagSuggestionEntry(
                file_id=row["id"],
                path=str(path),
                filename=row["filename"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                md5=row["md5"],
                suggestions=all_suggestions,
            )
        )

    selected = entries if limit == 0 else entries[:limit]

    summary = TagSuggestionSummary(
        files_considered=len(rows),
        files_with_suggestions=files_with_suggestions,
        total_suggestions=total_suggestions,
        by_source=dict(sorted(by_source.items())),
        by_field=dict(sorted(by_field.items())),
        by_confidence_bucket=dict(sorted(by_bucket.items())),
    )

    return TagSuggestionReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        db_path=str(db_path),
        min_confidence=min_confidence,
        limit=limit,
        summary=summary,
        entries=selected,
    )


def write_tag_suggestion_report(
    report: TagSuggestionReport,
    output_path: Path,
    quiet: bool = False,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    if not quiet:
        console.print(f"Tag suggestion report written to [cyan]{output_path}[/cyan]")


def show_tag_suggestion_report(report: TagSuggestionReport) -> None:
    summary = report.summary
    console.print(
        f"Considered [yellow]{summary.files_considered:,}[/yellow] file(s); "
        f"produced [yellow]{summary.total_suggestions:,}[/yellow] suggestion(s) "
        f"across [yellow]{summary.files_with_suggestions:,}[/yellow] file(s)."
    )

    if summary.by_source:
        sources = Table(title="Suggestions by source", show_lines=False)
        sources.add_column("Source", style="cyan")
        sources.add_column("Count", justify="right")
        for source, count in summary.by_source.items():
            sources.add_row(source, f"{count:,}")
        console.print(sources)

    if summary.by_field:
        fields = Table(title="Suggestions by field", show_lines=False)
        fields.add_column("Field", style="cyan")
        fields.add_column("Count", justify="right")
        for field_name, count in summary.by_field.items():
            fields.add_row(field_name, f"{count:,}")
        console.print(fields)

    if not report.entries:
        return

    sample = Table(title="Sample suggestions (first 20 files)", show_lines=False)
    sample.add_column("File")
    sample.add_column("Field")
    sample.add_column("Value")
    sample.add_column("Source")
    sample.add_column("Conf", justify="right")
    for entry in report.entries[:20]:
        for suggestion in entry.suggestions:
            sample.add_row(
                entry.filename,
                suggestion.field,
                suggestion.value,
                suggestion.source,
                f"{suggestion.confidence:.2f}",
            )
    console.print(sample)
