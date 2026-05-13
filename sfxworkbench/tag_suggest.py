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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.config import ConfidenceProfile
from sfxworkbench.db import get_connection, path_scope_filter, path_scope_params
from sfxworkbench.groups import audit_related_groups
from sfxworkbench.models import (
    RelatedSoundFile,
    RelatedSoundGroup,
    TagSuggestion,
    TagSuggestionEntry,
    TagSuggestionReport,
    TagSuggestionSummary,
    UcsCatalog,
)
from sfxworkbench.ucs import normalize_stem, parse_ucs_stem
from sfxworkbench.ucs_catalog import load_catalog, lookup_entry, resolve_catalog_path

console = Console()

# Confidence anchors. Sourced from the default :class:`ConfidenceProfile` so
# the Pydantic model is the single source of truth and user-overridable via
# ``~/.config/sfxworkbench/config.toml`` once a future PR plumbs the active
# profile through to the individual suggestors. Tuning lives in
# :mod:`sfxworkbench.config`.
_DEFAULT_CONFIDENCE = ConfidenceProfile()
_CONFIDENCE_UCS_HEURISTIC = _DEFAULT_CONFIDENCE.ucs_heuristic
_CONFIDENCE_UCS_CATALOG = _DEFAULT_CONFIDENCE.ucs_catalog
_CONFIDENCE_GROUP = _DEFAULT_CONFIDENCE.group
_CONFIDENCE_FILENAME_ABBREVIATION = _DEFAULT_CONFIDENCE.filename_abbreviation
_CONFIDENCE_FILENAME_TAKE = _DEFAULT_CONFIDENCE.filename_take
_CONFIDENCE_FILENAME_DESCRIPTION = _DEFAULT_CONFIDENCE.filename_description
_CONFIDENCE_PATH = _DEFAULT_CONFIDENCE.path
_CONFIDENCE_SYNONYM = _DEFAULT_CONFIDENCE.synonym

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
# Tier post-feedback: SFX libraries often ship lowercase concatenated
# compounds with a trailing catalog number (e.g. ``Afghanmeninteriorbusyc3401``).
# Splitting on the digit boundary first surfaces the catalog number as its own
# token, and ``wordninja`` (Viterbi dynamic-programming splitter over a built-in
# word-frequency list) recovers ``afghan men interior busy`` from the compound.
_DIGIT_BOUNDARY_RE = re.compile(r"(\d+)")
_TRAILING_NUMBER_RE = re.compile(
    r"^(?P<base>.+?)(?:[\s._\-]*(?:take|tk)?[\s._\-]*)?(?P<number>\d{1,4})$",
    re.IGNORECASE,
)
_LEADING_SORT_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-_.\s]+(.+?)\s*$")

# Conservative reviewer-facing search-language enrichment. These become
# `keyword` suggestions, not descriptions, so approved terms can travel through
# metadata writes without polluting human-readable description fields.
_SYNONYM_KEYWORDS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("car", "crash"): ("vehicle impact", "auto collision", "wreck"),
    ("car", "hit"): ("vehicle impact", "auto collision"),
    ("crash",): ("impact", "collision", "wreck"),
    ("explosion",): ("blast", "detonation", "boom"),
    ("fire",): ("flame", "burning", "combustion"),
    ("footstep",): ("footsteps", "walk", "foley step"),
    ("footsteps",): ("footstep", "walk", "foley step"),
    ("glass", "break"): ("glass smash", "shatter", "debris"),
    ("gunshot",): ("gun fire", "shot", "firearm"),
    ("hit",): ("impact", "strike", "thud"),
    ("impact",): ("hit", "strike", "collision"),
    ("rain",): ("rainfall", "shower", "downpour"),
    ("thunder",): ("storm", "rumble", "thunderclap"),
    ("whoosh",): ("swoosh", "pass by", "swish"),
    ("wind",): ("gust", "air", "storm"),
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _confidence_bucket(confidence: float) -> str:
    if confidence < 0.5:
        return "lo"
    if confidence < 0.8:
        return "mid"
    return "hi"


def normalize_filter_values(values: list[str] | None, *, option_name: str) -> list[str]:
    """Normalize repeated CLI/API filter values into stable lowercase tokens."""
    normalized: list[str] = []
    for raw in values or []:
        for value in raw.split(","):
            token = value.strip().lower()
            if not token:
                continue
            if token not in normalized:
                normalized.append(token)
    if any("*" in value for value in normalized):
        raise ValueError(f"{option_name} does not support wildcards")
    return normalized


def filter_suggestions(
    suggestions: list[TagSuggestion],
    *,
    sources: list[str] | None = None,
    fields: list[str] | None = None,
) -> list[TagSuggestion]:
    source_filter = set(sources or [])
    field_filter = set(fields or [])
    return [
        suggestion
        for suggestion in suggestions
        if (not source_filter or suggestion.source.lower() in source_filter)
        and (not field_filter or suggestion.field.lower() in field_filter)
    ]


def _split_compound(token: str) -> list[str]:
    """Recover words from a concatenated compound token.

    SFX naming conventions frequently produce stems like
    ``Afghanmeninteriorbusyc3401`` — descriptive words run together with a
    trailing catalog number. The separator-only split leaves this as one
    token, so the suggestion engine used to propose the entire compound as
    a description.

    Heuristics:
    - Tokens shorter than 8 chars stay intact (``rain`` is one word, not
      ``r ain``; ``AMB`` is an abbreviation handled downstream).
    - Tokens in the abbreviation dictionary are left alone.
    - Digit-boundary split first so ``busyc3401`` → ``busyc`` + ``3401``;
      the number flows through the existing ``_TRAILING_NUMBER_RE`` logic.
    - Lowercase + wordninja for the alphabetic part. ``Afghanmen`` and
      ``afghanmen`` get the same treatment — the leading capital is just
      title case, not a structure signal.
    - Drop sub-tokens shorter than 3 chars (typically noise from
      ambiguous splits, e.g. a stray ``c`` left over from a catalog code).
    """
    if token.upper() in _ABBREVIATIONS:
        return [token]
    digit_parts = [part for part in _DIGIT_BOUNDARY_RE.split(token) if part]
    if len(digit_parts) > 1:
        out: list[str] = []
        for part in digit_parts:
            if part.isdigit():
                out.append(part)
            else:
                out.extend(_split_compound(part))
        return out
    if len(token) < 8 or not token.isalpha():
        return [token]
    import wordninja

    pieces = [piece for piece in wordninja.split(token.lower()) if len(piece) >= 3]
    return pieces or [token]


def _tokenize(text: str) -> list[str]:
    """Split a stem on common separators, then word-split each remaining token.

    ``_split_compound`` is a no-op for short, mixed-case, or abbreviation
    tokens — so well-structured stems like ``AMB_RAIN_01`` pass through as
    ``[AMB, RAIN, 01]`` while concatenated compounds get recovered.
    """
    out: list[str] = []
    for token in _SEPARATOR_RE.split(text):
        if not token:
            continue
        out.extend(_split_compound(token))
    return out


def _normalized_keyword_tokens(text: str) -> set[str]:
    return {token.lower() for token in _tokenize(text)}


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


def suggest_from_ucs_stem(
    stem: str,
    catalog: UcsCatalog | None = None,
    *,
    profile: ConfidenceProfile | None = None,
) -> list[TagSuggestion]:
    """Emit UCS provenance fields plus description/take candidates from a UCS-named stem.

    When a UCS catalog is supplied and the filename's ``CatShort_SubCategory``
    pair matches, ``ucs_category``/``ucs_subcategory``/description suggestions
    are upgraded to catalog-backed evidence. UCS category fields are provenance:
    they record what the filename claims, not a final semantic search tag.
    """
    p = profile or _DEFAULT_CONFIDENCE
    parsed = parse_ucs_stem(stem)
    if not parsed.is_ucs:
        return []

    catalog_entry = lookup_entry(catalog, parsed.category, parsed.subcategory) if catalog is not None else None
    has_catalog_match = catalog_entry is not None
    source = "ucs_catalog" if has_catalog_match else "ucs_stem"
    method = "ucs_catalog_match" if has_catalog_match else "ucs_heuristic"
    confidence = p.ucs_catalog if has_catalog_match else p.ucs_heuristic
    suggestions: list[TagSuggestion] = []
    evidence = [stem]
    if catalog is not None and not has_catalog_match:
        evidence.append(f"catalog_miss:{parsed.category}_{parsed.subcategory}")
    if catalog_entry is not None:
        evidence.extend([f"cat_short:{catalog_entry.cat_short}", f"cat_id:{catalog_entry.cat_id}"])

    if parsed.category:
        suggestions.append(
            TagSuggestion(
                field="ucs_category",
                value=catalog_entry.category if catalog_entry is not None else parsed.category,
                source=source,
                method=method,
                confidence=confidence,
                evidence=evidence,
            )
        )
    if parsed.subcategory:
        suggestions.append(
            TagSuggestion(
                field="ucs_subcategory",
                value=catalog_entry.subcategory if catalog_entry is not None else parsed.subcategory,
                source=source,
                method=method,
                confidence=confidence,
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
                source=source,
                method=method,
                confidence=confidence,
                evidence=evidence,
            )
        )
    if take is not None:
        suggestions.append(
            TagSuggestion(
                field="take_number",
                value=take,
                source="ucs_stem",
                method="trailing_number",
                confidence=p.ucs_heuristic,
                evidence=evidence,
            )
        )
    return suggestions


def suggest_from_filename(
    stem: str,
    *,
    skip_description: bool = False,
    profile: ConfidenceProfile | None = None,
) -> list[TagSuggestion]:
    """Emit ``description`` and ``take_number`` for non-UCS filenames.

    ``skip_description`` suppresses the description suggestion when a higher
    confidence source (UCS or group) has already produced one — but the take
    number is still useful as corroboration.
    """
    p = profile or _DEFAULT_CONFIDENCE
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
                confidence=p.filename_take,
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
                confidence=(p.filename_abbreviation if has_abbreviation else p.filename_description),
                evidence=[stem],
            )
        )
    return suggestions


def suggest_from_path(file_path: Path, root: Path, *, profile: ConfidenceProfile | None = None) -> list[TagSuggestion]:
    """Emit one ``description`` suggestion per meaningful parent folder."""
    p = profile or _DEFAULT_CONFIDENCE
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
                confidence=p.path,
                evidence=[raw_name],
            )
        )
    return suggestions


def suggest_from_group(
    file_in_group: RelatedSoundFile,
    group: RelatedSoundGroup,
    *,
    profile: ConfidenceProfile | None = None,
) -> list[TagSuggestion]:
    """Emit suggestions for a file that belongs to a related sound group."""
    p = profile or _DEFAULT_CONFIDENCE
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
                confidence=p.group,
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
                confidence=p.group,
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
                confidence=p.group,
                evidence=evidence + [f"marker:{marker}"],
            )
        )
    return suggestions


def suggest_synonym_keywords(
    suggestions: list[TagSuggestion],
    *,
    synonym_limit: int = 0,
    synonym_depth: int = 0,
    profile: ConfidenceProfile | None = None,
) -> list[TagSuggestion]:
    """Suggest reviewer-facing keyword synonyms from existing tag evidence."""
    p = profile or _DEFAULT_CONFIDENCE
    if synonym_limit < 0:
        raise ValueError("--synonym-limit must be 0 or greater")
    if synonym_depth < 0:
        raise ValueError("--synonym-depth must be 0 or greater")
    evidence_sources = [
        suggestion
        for suggestion in suggestions
        if suggestion.field in {"description", "keyword", "keywords", "ucs_category", "ucs_subcategory"}
    ]
    if not evidence_sources:
        return []

    token_set: set[str] = set()
    existing_terms: set[str] = set()
    evidence: list[str] = []
    for suggestion in evidence_sources:
        existing_terms.add(suggestion.value.strip().lower())
        token_set.update(_normalized_keyword_tokens(suggestion.value))
        evidence.append(f"{suggestion.source}:{suggestion.field}:{suggestion.value}")

    synonym_suggestions: list[TagSuggestion] = []
    emitted: set[str] = set()
    for trigger_tokens, keywords in _SYNONYM_KEYWORDS.items():
        if not set(trigger_tokens).issubset(token_set):
            continue
        trigger = " ".join(trigger_tokens)
        candidate_keywords = keywords[:synonym_depth] if synonym_depth else keywords
        for keyword in candidate_keywords:
            normalized = keyword.lower()
            if normalized in emitted or normalized in existing_terms:
                continue
            emitted.add(normalized)
            synonym_suggestions.append(
                TagSuggestion(
                    field="keyword",
                    value=keyword,
                    source="synonym",
                    method="controlled_synonym_map",
                    confidence=p.synonym,
                    evidence=[f"matched:{trigger}", *evidence],
                )
            )
            if synonym_limit and len(synonym_suggestions) >= synonym_limit:
                return synonym_suggestions
    return synonym_suggestions


# ---------------------------------------------------------------------------
# Suggestor protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuggestContext:
    """Per-file inputs that every :class:`Suggestor` may consult.

    Built once per file by the orchestrator and threaded through each suggestor
    in :data:`DEFAULT_SUGGESTORS`. Pure data — no DB handles or I/O — so
    suggestors stay easy to test in isolation.

    The ``profile`` field carries the active :class:`ConfidenceProfile` (from
    the user's :class:`sfxworkbench.config.Config`), letting users override
    confidence anchors via the TOML config without code changes. ``None``
    means "use the module's ``_DEFAULT_CONFIDENCE``".
    """

    file_id: int
    path: Path
    filename: str
    stem: str
    root: Path
    catalog: UcsCatalog | None = None
    group_match: tuple[RelatedSoundGroup, RelatedSoundFile] | None = None
    include_synonyms: bool = False
    synonym_limit: int = 0
    synonym_depth: int = 0
    profile: ConfidenceProfile | None = None


class Suggestor(Protocol):
    """A single source of tag suggestions for one indexed file.

    Implementations are typically tiny ``@dataclass(frozen=True)`` wrappers
    around the module-level ``suggest_from_*`` functions. The orchestrator runs
    them in order and feeds each the accumulated ``prior`` suggestions so that
    later stages (e.g. filename description gating, synonym expansion) can
    react to earlier evidence without breaking the uniform call surface.

    Adding a new suggestor (LLM-backed, catalog-backed, user-rule-backed) is a
    matter of writing one more wrapper and appending to
    :data:`DEFAULT_SUGGESTORS`; ``build_tag_suggestion_report`` does not need
    to change.
    """

    @property
    def name(self) -> str:
        """A short identifier (lowercase snake_case) for this suggestor."""
        ...

    def propose(self, ctx: SuggestContext, prior: list[TagSuggestion]) -> Iterable[TagSuggestion]:
        """Return zero or more suggestions for *ctx*, given the *prior* accumulator."""
        ...


# Sources whose ``description`` suggestion is strong enough that the filename
# suggestor should not repeat its own (lower-confidence) description guess.
_FILENAME_DESCRIPTION_GATING_SOURCES = frozenset({"ucs_stem", "ucs_catalog", "group"})


@dataclass(frozen=True)
class UcsStemSuggestor:
    name: str = "ucs_stem"

    def propose(self, ctx: SuggestContext, prior: list[TagSuggestion]) -> Iterable[TagSuggestion]:
        return suggest_from_ucs_stem(ctx.stem, catalog=ctx.catalog, profile=ctx.profile)


@dataclass(frozen=True)
class GroupSuggestor:
    name: str = "group"

    def propose(self, ctx: SuggestContext, prior: list[TagSuggestion]) -> Iterable[TagSuggestion]:
        if ctx.group_match is None:
            return []
        group, member = ctx.group_match
        return suggest_from_group(member, group, profile=ctx.profile)


@dataclass(frozen=True)
class FilenameSuggestor:
    name: str = "filename"

    def propose(self, ctx: SuggestContext, prior: list[TagSuggestion]) -> Iterable[TagSuggestion]:
        skip_description = any(
            s.field == "description" and s.source in _FILENAME_DESCRIPTION_GATING_SOURCES for s in prior
        )
        return suggest_from_filename(ctx.stem, skip_description=skip_description, profile=ctx.profile)


@dataclass(frozen=True)
class PathSuggestor:
    name: str = "path"

    def propose(self, ctx: SuggestContext, prior: list[TagSuggestion]) -> Iterable[TagSuggestion]:
        return suggest_from_path(ctx.path, ctx.root, profile=ctx.profile)


@dataclass(frozen=True)
class SynonymSuggestor:
    """Meta-suggestor: expands existing high-confidence evidence into review-only synonyms.

    Always runs last because it consumes the prior accumulator as its input.
    """

    name: str = "synonym"

    def propose(self, ctx: SuggestContext, prior: list[TagSuggestion]) -> Iterable[TagSuggestion]:
        if not ctx.include_synonyms:
            return []
        return suggest_synonym_keywords(
            list(prior),
            synonym_limit=ctx.synonym_limit,
            synonym_depth=ctx.synonym_depth,
            profile=ctx.profile,
        )


# The intermediate ``list[Suggestor]`` is purely for type-checking: it forces
# each concrete instance to be widened to the Protocol type, so the resulting
# tuple is correctly inferred as ``tuple[Suggestor, ...]`` rather than the
# concrete heterogenous tuple type mypy would otherwise pick.
_DEFAULT_SUGGESTOR_LIST: list[Suggestor] = [
    UcsStemSuggestor(),
    GroupSuggestor(),
    FilenameSuggestor(),
    PathSuggestor(),
    SynonymSuggestor(),
]

DEFAULT_SUGGESTORS: tuple[Suggestor, ...] = tuple(_DEFAULT_SUGGESTOR_LIST)
"""Ordered list of suggestors used by :func:`build_tag_suggestion_report`.

Order matters: stages that gate on prior evidence (FilenameSuggestor's
``skip_description``, SynonymSuggestor's meta-expansion) must come after the
sources they consult.
"""


def run_suggestors(ctx: SuggestContext, suggestors: Iterable[Suggestor] = DEFAULT_SUGGESTORS) -> list[TagSuggestion]:
    """Run *suggestors* in order against *ctx*, feeding each the accumulated prior list.

    Returns the concatenated list of all suggestions. Filtering by source,
    field, and confidence happens in :func:`build_tag_suggestion_report` after
    this collection step.
    """
    accumulated: list[TagSuggestion] = []
    for suggestor in suggestors:
        accumulated.extend(suggestor.propose(ctx, accumulated))
    return accumulated


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
        f"""
        SELECT id, path, filename, stem, size_bytes, mtime, md5
        FROM files
        WHERE {path_scope_filter()}
          AND scan_error IS NULL
        ORDER BY path
        """,
        path_scope_params(root),
    ).fetchall()
    conn.close()
    return rows


def build_tag_suggestion_report(
    root: Path,
    db_path: Path,
    min_confidence: float = 0.0,
    limit: int = 200,
    ucs_catalog_path: Path | None = None,
    use_ucs_catalog: bool = False,
    include_synonyms: bool = False,
    synonym_limit: int = 0,
    synonym_depth: int = 0,
    sources: list[str] | None = None,
    fields: list[str] | None = None,
    confidence_profile: ConfidenceProfile | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
) -> TagSuggestionReport:
    """Walk the index for files under ``root`` and produce per-file suggestions."""
    if min_confidence < 0 or min_confidence > 1:
        raise ValueError("--min-confidence must be between 0 and 1")
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    if synonym_limit < 0:
        raise ValueError("--synonym-limit must be 0 or greater")
    if synonym_depth < 0:
        raise ValueError("--synonym-depth must be 0 or greater")
    source_filters = normalize_filter_values(sources, option_name="--source")
    field_filters = normalize_filter_values(fields, option_name="--field")

    root = root.resolve()
    # Surface the prep phase explicitly — these two queries each pull every
    # in-scope file from the DB (and ``_build_group_index`` runs the audit
    # itself). On a 50k-file library they're several seconds combined and
    # the UI used to show nothing.
    if progress_callback is not None:
        progress_callback("loading", 0, None, "Loading indexed files...")
    rows = _load_files(root, db_path)
    if progress_callback is not None:
        progress_callback("loading", len(rows), len(rows), f"Loaded {len(rows):,} file(s); building group index...")
    group_index = _build_group_index(root, db_path)
    if progress_callback is not None:
        progress_callback("loading", len(rows), len(rows), "Loaded group index. Loading UCS catalog...")
    catalog: UcsCatalog | None = None
    resolved_catalog_path: Path | None = None
    if use_ucs_catalog or ucs_catalog_path is not None:
        resolved_catalog_path = resolve_catalog_path(ucs_catalog_path)
        catalog = load_catalog(ucs_catalog_path)
        if catalog is None:
            raise ValueError("No UCS catalog loaded. Run `sfx ucs import SOURCE` first or pass --ucs-catalog.")

    entries: list[TagSuggestionEntry] = []
    by_source: dict[str, int] = {}
    by_field: dict[str, int] = {}
    by_bucket: dict[str, int] = {}
    files_with_suggestions = 0
    total_suggestions = 0

    from sfxworkbench.utils import progress_interval

    total_rows = len(rows)
    report_every = progress_interval(total_rows)
    if progress_callback is not None:
        progress_callback("suggesting", 0, total_rows, f"Processing {total_rows:,} indexed file(s)...")

    for row_index, row in enumerate(rows):
        path = Path(row["path"])
        stem_raw = row["stem"] or path.stem
        stem = normalize_stem(stem_raw)
        ctx = SuggestContext(
            file_id=int(row["id"]),
            path=path,
            filename=row["filename"],
            stem=stem,
            root=root,
            catalog=catalog,
            group_match=group_index.by_path.get(str(path)),
            include_synonyms=include_synonyms,
            synonym_limit=synonym_limit,
            synonym_depth=synonym_depth,
            profile=confidence_profile,
        )
        # Filename description gating + synonym expansion happen inside the
        # individual suggestors via the ``prior`` accumulator.
        all_suggestions = run_suggestors(ctx)
        if min_confidence > 0:
            all_suggestions = [s for s in all_suggestions if s.confidence >= min_confidence]
        all_suggestions = filter_suggestions(all_suggestions, sources=source_filters, fields=field_filters)
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
        # Report at the log-scaled interval so a 1M-file suggestion run
        # doesn't fire 20k status updates. Always report the final row so
        # the bar lands at 100%.
        if progress_callback is not None and ((row_index + 1) % report_every == 0 or row_index + 1 == total_rows):
            progress_callback(
                "suggesting",
                row_index + 1,
                total_rows,
                f"{row['filename']}",
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
        ucs_catalog_path=str(resolved_catalog_path.resolve()) if resolved_catalog_path is not None else None,
        ucs_catalog_release_version=catalog.provenance.release_version if catalog is not None else None,
        min_confidence=min_confidence,
        synonym_limit=synonym_limit,
        synonym_depth=synonym_depth,
        sources=source_filters,
        fields=field_filters,
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
