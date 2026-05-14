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
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.config import ConfidenceProfile
from sfxworkbench.db import get_connection, path_scope_filter, path_scope_params, resolve_scope_root
from sfxworkbench.groups import audit_related_groups
from sfxworkbench.metadata_fields import canonicalize, is_multivalue, normalize_value_for_dedup
from sfxworkbench.models import (
    RelatedSoundFile,
    RelatedSoundGroup,
    TagSuggestion,
    TagSuggestionEntry,
    TagSuggestionReport,
    TagSuggestionSummary,
    UcsCatalog,
    UcsEntry,
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

_SEPARATOR_RE = re.compile(r"[\s._\-()\[\]{}<>;,!?\"'`/\\|&+%@#~]+")
# Tier post-feedback: SFX libraries often ship lowercase concatenated
# compounds with a trailing catalog number (e.g. ``Afghanmeninteriorbusyc3401``).
# Splitting on the digit boundary first surfaces the catalog number as its own
# token, and ``wordninja`` (Viterbi dynamic-programming splitter over a built-in
# word-frequency list) recovers ``afghan men interior busy`` from the compound.
_DIGIT_BOUNDARY_RE = re.compile(r"(\d+)")
_LEADING_SORT_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-_.\s]+(.+?)\s*$")
_TIMESTAMP_TOKEN_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?$")
_MONTH_NAME_RE = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_SEQUENCE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)(?:19|20)\d{2}[-_./ ](?:0?[1-9]|1[0-2])[-_./ ](?:0?[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)(?:0?[1-9]|1[0-2])[-_./](?:0?[1-9]|[12]\d|3[01])[-_./](?:(?:19|20)?\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(rf"\b{_MONTH_NAME_RE}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+(?:19|20)\d{{2}}\b", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_NAME_RE}\.?\s+(?:19|20)\d{{2}}\b", re.IGNORECASE),
)
_AUDIO_FORMAT_SEQUENCE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:8|12|16|20|24|32|64)[-_ ]?(?:bit|bits)\b", re.IGNORECASE),
    re.compile(r"\b\d{2,6}(?:[.,]\d+)?[-_ ]?(?:hz|khz|k)\b", re.IGNORECASE),
    re.compile(r"\b(?:44k1|88k2|176k4)\b", re.IGNORECASE),
)
_TECHNICAL_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "stake",
        "sswver",
        "sproject",
        "sscene",
        "sfilename",
        "stape",
        "snote",
    }
)
_TECHNICAL_METADATA_KEY_RE = re.compile(r"^s(?:TRK\d+)$", re.IGNORECASE)
_GENERIC_AMBIENCE_KEYWORDS = frozenset({"ambience", "background", "atmosphere", "room tone"})

# Conservative reviewer-facing search-language enrichment. These become
# `keyword` suggestions, not descriptions, so approved terms can travel through
# metadata writes without polluting human-readable description fields.
_SYNONYM_KEYWORDS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("alarm",): ("alert", "siren", "warning"),
    ("ambience",): ("background", "atmosphere", "room tone"),
    ("applause",): ("clapping", "crowd", "audience"),
    ("background",): ("ambience", "atmosphere", "room tone"),
    ("bang",): ("impact", "slam", "hit"),
    ("bird",): ("birds", "chirp", "tweet"),
    ("body", "fall"): ("body hit", "thud", "impact"),
    ("boom",): ("impact", "explosion", "slam"),
    ("car", "crash"): ("vehicle impact", "auto collision", "wreck"),
    ("car", "hit"): ("vehicle impact", "auto collision"),
    ("cheer",): ("crowd", "applause", "audience"),
    ("cloth",): ("fabric", "rustle", "foley"),
    ("concrete",): ("cement", "pavement", "stone"),
    ("crash",): ("impact", "collision", "wreck"),
    ("crowd",): ("people", "audience", "walla"),
    ("debris",): ("rubble", "fragments", "wreckage"),
    ("door",): ("open close", "hinge", "slam"),
    ("drum",): ("percussion", "beat", "rhythm"),
    ("engine",): ("motor", "vehicle", "idle"),
    ("equipment",): ("gear", "apparatus", "machine"),
    ("explosion",): ("blast", "detonation", "boom"),
    ("farm",): ("rural", "field", "countryside"),
    ("forest",): ("woods", "nature", "ambience"),
    ("fire",): ("flame", "burning", "combustion"),
    ("flutter",): ("flapping", "waver", "tremble"),
    ("footstep",): ("footsteps", "walk", "foley step"),
    ("footsteps",): ("footstep", "walk", "foley step"),
    ("gore",): ("blood", "viscera", "flesh"),
    ("glass", "break"): ("glass smash", "shatter", "debris"),
    ("gravel",): ("rocks", "stones", "dirt"),
    ("gun",): ("firearm", "weapon", "shot"),
    ("gunshot",): ("gun fire", "shot", "firearm"),
    ("heartbeat",): ("heart beat", "pulse", "cardio"),
    ("hit",): ("impact", "strike", "thud"),
    ("impact",): ("hit", "strike", "collision"),
    ("jet",): ("aircraft", "engine", "flyby"),
    ("logo",): ("ident", "brand", "sting"),
    ("magic",): ("spell", "fantasy", "shimmer"),
    ("metal",): ("steel", "iron", "clang"),
    ("movement",): ("motion", "move", "gesture"),
    ("pistol",): ("handgun", "firearm", "gun"),
    ("pulse",): ("beat", "throb", "rhythm"),
    ("punch",): ("hit", "impact", "strike"),
    ("rain",): ("rainfall", "shower", "downpour"),
    ("rifle",): ("firearm", "gun", "weapon"),
    ("rock",): ("stone", "boulder", "gravel"),
    ("room", "tone"): ("ambience", "background", "interior"),
    ("safe",): ("vault", "lock", "secure"),
    ("servo",): ("motor", "mechanical", "robotic"),
    ("slam",): ("impact", "bang", "hit"),
    ("splash",): ("water", "wet", "pour"),
    ("stinger",): ("sting", "accent", "transition"),
    ("strike",): ("hit", "impact", "tap"),
    ("thunder",): ("storm", "rumble", "thunderclap"),
    ("tractor",): ("farm vehicle", "engine", "machinery"),
    ("tumbler",): ("lock", "click", "mechanism"),
    ("ufo",): ("alien", "spaceship", "sci fi"),
    ("vault",): ("safe", "lock", "secure"),
    ("water",): ("liquid", "splash", "stream"),
    ("weight",): ("heavy", "mass", "impact"),
    ("whoosh",): ("swoosh", "pass by", "swish"),
    ("wind",): ("gust", "air", "storm"),
    ("wood",): ("timber", "creak", "plank"),
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
    - Preserve uppercase alphanumeric codes such as ``MKH8040``, ``D100``,
      and ``WW2`` as meaningful model/acronym tokens.
    - Digit-boundary split first so ``busyc3401`` → ``busyc`` + ``3401``;
      later formatting drops the catalog number unless it was an explicit or
      short take suffix.
    - Lowercase + wordninja for the alphabetic part. ``Afghanmen`` and
      ``afghanmen`` get the same treatment — the leading capital is just
      title case, not a structure signal.
    - Drop sub-tokens shorter than 3 chars (typically noise from
      ambiguous splits, e.g. a stray ``c`` left over from a catalog code).
    """
    if token.upper() in _ABBREVIATIONS:
        return [token]
    if _is_meaningful_alphanumeric_code(token):
        return [token.upper()]
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


def _is_meaningful_alphanumeric_code(token: str) -> bool:
    """Return whether a token looks like a model number or acronym code.

    This intentionally preserves uppercase letter+digit tokens (``MKH8040``,
    ``D100``, ``WW2``) while allowing lowercase catalog suffixes like
    ``sh2301`` or ``busyc3401`` to split so their random numeric tail can be
    dropped from tag suggestions.
    """
    if len(token) < 2 or not token.isalnum():
        return False
    if not any(char.isalpha() for char in token) or not any(char.isdigit() for char in token):
        return False
    letters = "".join(char for char in token if char.isalpha())
    return bool(letters) and letters.upper() == letters


def _is_technical_metadata_key(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in _TECHNICAL_METADATA_KEYS or bool(_TECHNICAL_METADATA_KEY_RE.fullmatch(key.strip()))


def _is_technical_metadata_assignment(token: str) -> bool:
    if "=" not in token:
        return False
    key, _value = token.split("=", 1)
    return _is_technical_metadata_key(key)


def clean_tag_suggestion_text(text: str) -> str:
    """Clean recorder/project noise before tag suggestion tokenization.

    Some libraries expose raw iXML-like chunks in filename/group evidence, e.g.
    ``sTAKE=48 sSWVER=2.63 sFILENAME=SFX_T48.WAV sTRK1=Track A``. Those are
    technical provenance fields, not useful search tags. Multi-word values are
    skipped until the next key-value assignment so ``sTRK1=Track A`` does not
    leave ``A`` behind as a tag.
    """
    parts = text.split()
    kept: list[str] = []
    skipping_value = False
    for part in parts:
        if "=" in part:
            skipping_value = False
            if _is_technical_metadata_assignment(part):
                key, value = part.split("=", 1)
                skipping_value = bool(value) and bool(_TECHNICAL_METADATA_KEY_RE.fullmatch(key.strip()))
                continue
        elif skipping_value:
            skipping_value = False
            continue
        kept.append(part)
    return _strip_audio_format_sequences(_strip_date_sequences(" ".join(kept)))


def _has_technical_metadata_assignment(text: str) -> bool:
    return any(_is_technical_metadata_assignment(part) for part in text.split())


def is_technical_metadata_blob(text: str) -> bool:
    """Return True when a metadata value is only recorder/iXML assignment noise."""
    return _has_technical_metadata_assignment(text) and not _tokenize(text)


def _is_timestamp_token(token: str) -> bool:
    cleaned = token.strip().strip("()[]{}<>;,")
    return bool(_TIMESTAMP_TOKEN_RE.fullmatch(cleaned))


def _strip_date_sequences(text: str) -> str:
    for pattern in _DATE_SEQUENCE_RES:
        text = pattern.sub(" ", text)
    return text


def _strip_audio_format_sequences(text: str) -> str:
    for pattern in _AUDIO_FORMAT_SEQUENCE_RES:
        text = pattern.sub(" ", text)
    return text


def _tokenize(text: str) -> list[str]:
    """Split a stem on common separators, then word-split each remaining token.

    ``_split_compound`` is a no-op for short, mixed-case, or abbreviation
    tokens — so well-structured stems like ``AMB_RAIN_01`` pass through as
    ``[AMB, RAIN, 01]`` while concatenated compounds get recovered.
    """
    out: list[str] = []
    cleaned_text = clean_tag_suggestion_text(text)
    for token in _SEPARATOR_RE.split(cleaned_text):
        if not token:
            continue
        if _is_technical_metadata_assignment(token):
            continue
        if _is_timestamp_token(token):
            continue
        for piece in _split_compound(token):
            if not piece:
                continue
            # Drop single-character residue from compound splits or punctuation
            # boundaries (e.g. wordninja can leave a stray "c" from a catalog
            # code). Two-letter acronyms in ``_ABBREVIATIONS`` are preserved.
            if len(piece) == 1 and piece.upper() not in _ABBREVIATIONS:
                continue
            out.append(piece)
    return out


def _keyword_token_variants(token: str) -> set[str]:
    """Return conservative singular/stem variants for keyword matching only."""
    normalized = token.lower()
    variants = {normalized}
    if len(normalized) > 4 and normalized.endswith("ies"):
        variants.add(f"{normalized[:-3]}y")
    if len(normalized) > 4 and normalized.endswith("es"):
        variants.add(normalized[:-2])
    if len(normalized) > 3 and normalized.endswith("s"):
        variants.add(normalized[:-1])
    if len(normalized) > 5 and normalized.endswith("ing"):
        stem = normalized[:-3]
        if len(stem) > 3 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        variants.add(stem)
    if len(normalized) > 4 and normalized.endswith("ed"):
        variants.add(normalized[:-2])
    return variants


def _normalized_keyword_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _tokenize(text):
        tokens.update(_keyword_token_variants(token))
    return tokens


@dataclass(frozen=True)
class _PriorCatalogTrigger:
    tokens: frozenset[str]
    trigger_score: int
    trigger_label: str
    entry: UcsEntry


@dataclass
class PriorCatalogIndex:
    """Pre-tokenized UCS lookup for prior-tag matching."""

    full_by_token: dict[str, list[_PriorCatalogTrigger]] = field(default_factory=dict)
    synonym_token_by_token: dict[str, list[_PriorCatalogTrigger]] = field(default_factory=dict)

    @classmethod
    def build(cls, catalog: UcsCatalog) -> PriorCatalogIndex:
        full_by_token: dict[str, list[_PriorCatalogTrigger]] = defaultdict(list)
        synonym_token_by_token: dict[str, list[_PriorCatalogTrigger]] = defaultdict(list)

        def add_full(trigger: _PriorCatalogTrigger) -> None:
            for token in trigger.tokens:
                full_by_token[token].append(trigger)

        for entry in catalog.entries:
            subcategory_tokens = frozenset(_normalized_keyword_tokens(entry.subcategory))
            if subcategory_tokens:
                add_full(
                    _PriorCatalogTrigger(
                        tokens=subcategory_tokens,
                        trigger_score=2,
                        trigger_label=f"subcategory:{entry.subcategory}",
                        entry=entry,
                    )
                )
            for synonym in entry.synonyms:
                synonym_tokens = frozenset(_normalized_keyword_tokens(synonym))
                if not synonym_tokens:
                    continue
                add_full(
                    _PriorCatalogTrigger(
                        tokens=synonym_tokens,
                        trigger_score=1,
                        trigger_label=f"synonym:{synonym}",
                        entry=entry,
                    )
                )
                for token in synonym_tokens:
                    if len(token) < 3:
                        continue
                    synonym_token_by_token[token].append(
                        _PriorCatalogTrigger(
                            tokens=frozenset({token}),
                            trigger_score=0,
                            trigger_label=f"synonym_token:{token}",
                            entry=entry,
                        )
                    )
        return cls(full_by_token=dict(full_by_token), synonym_token_by_token=dict(synonym_token_by_token))

    def candidates_for(self, token_set: set[str]) -> list[tuple[int, int, bool, str, UcsEntry]]:
        best_by_entry: dict[str, tuple[int, str, UcsEntry]] = {}

        def consider(trigger: _PriorCatalogTrigger) -> None:
            entry_key = trigger.entry.cat_id
            current = best_by_entry.get(entry_key)
            if current is None or trigger.trigger_score > current[0]:
                best_by_entry[entry_key] = (trigger.trigger_score, trigger.trigger_label, trigger.entry)

        for token in token_set:
            for trigger in self.full_by_token.get(token, ()):
                if trigger.tokens.issubset(token_set):
                    consider(trigger)
        for token in token_set:
            if len(token) < 3:
                continue
            for trigger in self.synonym_token_by_token.get(token, ()):
                consider(trigger)

        candidates: list[tuple[int, int, bool, str, UcsEntry]] = []
        for trigger_score, trigger_label, entry in best_by_entry.values():
            category_tokens = _normalized_keyword_tokens(entry.cat_short) | _normalized_keyword_tokens(entry.category)
            has_category_context = bool(token_set & category_tokens)
            score = trigger_score + (1 if has_category_context else 0)
            candidates.append((score, trigger_score, has_category_context, trigger_label, entry))
        return candidates


def _title_case_token(token: str) -> str:
    """Title-case a token while expanding known SFX abbreviations.

    Returns the abbreviation expansion when present, otherwise a normal
    Title-Case form. Uppercase model/acronym tokens with digits are preserved.
    """
    if not token:
        return token
    if token.isdigit():
        return token
    upper = token.upper()
    if upper in _ABBREVIATIONS:
        return _ABBREVIATIONS[upper]
    if _is_meaningful_alphanumeric_code(token):
        return upper
    return token[:1].upper() + token[1:].lower()


def _is_bare_take_number(token: str) -> bool:
    if not token.isdigit():
        return False
    if len(token) <= 2:
        return True
    return len(token) == 3 and token.startswith("0")


def _strip_take_suffix(tokens: list[str]) -> tuple[list[str], str | None]:
    """If the last token is a bare integer or ``take_NN``, return the take.

    Returns ``(tokens_without_take, take_number_str_or_None)``.
    """
    if not tokens:
        return tokens, None
    last = tokens[-1]
    if _is_bare_take_number(last):
        return tokens[:-1], last
    take_match = re.fullmatch(r"(?:take|tk)[-_]?(\d{1,4})", last, re.IGNORECASE)
    if take_match:
        return tokens[:-1], take_match.group(1)
    return tokens, None


def _format_description(tokens: list[str]) -> str:
    return " ".join(_title_case_token(token) for token in tokens if token and not token.isdigit())


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

    description_tokens = _tokenize(group.inferred_stem)
    description_value = _format_description(description_tokens)
    if _has_technical_metadata_assignment(group.inferred_stem) and not description_value:
        return suggestions
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
    generic_ambience_context = _has_generic_ambience_context(token_set)
    for trigger_tokens, keywords in _SYNONYM_KEYWORDS.items():
        if not set(trigger_tokens).issubset(token_set):
            continue
        trigger = " ".join(trigger_tokens)
        candidate_keywords = keywords[:synonym_depth] if synonym_depth else keywords
        for keyword in candidate_keywords:
            normalized = keyword.lower()
            if generic_ambience_context and normalized in _GENERIC_AMBIENCE_KEYWORDS:
                continue
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


def _has_generic_ambience_context(token_set: set[str]) -> bool:
    return bool({"ambience", "background", "atmosphere"} & token_set) or {"room", "tone"}.issubset(token_set)


def _prior_catalog_trigger(entry: UcsEntry, token_set: set[str]) -> tuple[int, str] | None:
    """Score how confidently a catalog entry matches a token set.

    Tier 2: every subcategory token is present (strongest match).
    Tier 1: every token of one synonym is present (full-synonym match).
    Tier 0: a single synonym token of length >= 3 is present (fallback hint).
    """
    subcategory_tokens = _normalized_keyword_tokens(entry.subcategory)
    if subcategory_tokens and subcategory_tokens.issubset(token_set):
        return 2, f"subcategory:{entry.subcategory}"
    for synonym in entry.synonyms:
        synonym_tokens = _normalized_keyword_tokens(synonym)
        if synonym_tokens and synonym_tokens.issubset(token_set):
            return 1, f"synonym:{synonym}"
    for synonym in entry.synonyms:
        synonym_tokens = _normalized_keyword_tokens(synonym)
        meaningful_overlap = {token for token in synonym_tokens & token_set if len(token) >= 3}
        if meaningful_overlap:
            hit = sorted(meaningful_overlap)[0]
            return 0, f"synonym_token:{hit}"
    return None


def _has_catalog_ucs_fields(suggestions: list[TagSuggestion]) -> bool:
    return any(
        suggestion.field in {"ucs_category", "ucs_subcategory"} and suggestion.source == "ucs_catalog"
        for suggestion in suggestions
    )


def _catalog_sort_key(candidate: tuple[int, int, bool, str, UcsEntry]) -> tuple[str, str, str]:
    _score, _trigger_score, _has_category_context, _trigger_label, entry = candidate
    return (entry.cat_short, entry.subcategory, entry.cat_id)


def suggest_ucs_from_prior_tags(
    suggestions: list[TagSuggestion],
    catalog: UcsCatalog | None,
    *,
    catalog_index: PriorCatalogIndex | None = None,
    profile: ConfidenceProfile | None = None,
) -> list[TagSuggestion]:
    """Suggest UCS fields from earlier proposed semantic tags.

    This bridges filename/path/group tag suggestions into catalog-backed UCS
    suggestions. It is intentionally conservative: if multiple catalog entries
    tie for the same best match, it emits nothing rather than guessing.
    """
    if catalog is None or _has_catalog_ucs_fields(suggestions):
        return []
    semantic_suggestions = [
        suggestion
        for suggestion in suggestions
        if suggestion.field in {"description", "keyword", "keywords", "category", "subcategory"}
        and suggestion.source.lower() != "synonym"
        and suggestion.value.strip()
    ]
    if not semantic_suggestions:
        return []

    token_set: set[str] = set()
    evidence = []
    for suggestion in semantic_suggestions:
        token_set.update(_normalized_keyword_tokens(suggestion.value))
        evidence.append(f"{suggestion.source}:{suggestion.field}:{suggestion.value}")

    candidates: list[tuple[int, int, bool, str, UcsEntry]]
    if catalog_index is not None:
        candidates = catalog_index.candidates_for(token_set)
    else:
        candidates = []
        for entry in catalog.entries:
            trigger = _prior_catalog_trigger(entry, token_set)
            if trigger is None:
                continue
            trigger_score, trigger_label = trigger
            category_tokens = _normalized_keyword_tokens(entry.cat_short) | _normalized_keyword_tokens(entry.category)
            has_category_context = bool(token_set & category_tokens)
            score = trigger_score + (1 if has_category_context else 0)
            candidates.append((score, trigger_score, has_category_context, trigger_label, entry))
    if not candidates:
        return []

    best_score = max(candidate[0] for candidate in candidates)
    best = sorted((candidate for candidate in candidates if candidate[0] == best_score), key=_catalog_sort_key)
    ambiguous_alternatives = best[1:]

    _score, trigger_score, has_category_context, trigger_label, entry = best[0]
    p = profile or _DEFAULT_CONFIDENCE
    if ambiguous_alternatives:
        # UCS is valuable enough to review even when catalog evidence ties.
        # Keep it below exact/full-token matches and record alternatives so
        # reviewers can reject or correct the deterministic first pick.
        confidence = min(p.ucs_catalog, 0.62)
    elif trigger_score == 0:
        # Tier-0 single-token synonym hit: useful as a starting point for
        # review. It should survive the TUI's synonym confidence floor.
        confidence = min(p.ucs_catalog, 0.62)
    else:
        confidence = min(p.ucs_catalog, 0.86 if has_category_context else 0.82)
    catalog_evidence = [
        f"matched:{trigger_label}",
        f"cat_short:{entry.cat_short}",
        f"cat_id:{entry.cat_id}",
        *(
            f"ambiguous_alternative:{alt_entry.cat_short}_{alt_entry.subcategory}:{alt_entry.cat_id}"
            for _alt_score, _alt_trigger_score, _alt_has_category_context, _alt_trigger_label, alt_entry in ambiguous_alternatives[
                :8
            ]
        ),
        *evidence,
    ]
    return [
        TagSuggestion(
            field="ucs_category",
            value=entry.category,
            source="ucs_catalog",
            method="prior_tag_catalog_match",
            confidence=confidence,
            evidence=catalog_evidence,
        ),
        TagSuggestion(
            field="ucs_subcategory",
            value=entry.subcategory,
            source="ucs_catalog",
            method="prior_tag_catalog_match",
            confidence=confidence,
            evidence=catalog_evidence,
        ),
    ]


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
    catalog_prior_index: PriorCatalogIndex | None = None
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
class UcsPriorTagSuggestor:
    """Meta-suggestor: maps accumulated semantic tag proposals back to UCS."""

    name: str = "ucs_prior_tags"

    def propose(self, ctx: SuggestContext, prior: list[TagSuggestion]) -> Iterable[TagSuggestion]:
        return suggest_ucs_from_prior_tags(
            prior,
            ctx.catalog,
            catalog_index=ctx.catalog_prior_index,
            profile=ctx.profile,
        )


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


# ---------------------------------------------------------------------------
# Normalization / cross-source dedup
# ---------------------------------------------------------------------------


# Recognized sources emitted by the built-in suggestors. Kept as a tuple so it
# documents the expected set without breaking forward-compatibility for plans
# that carry extra sources (e.g. ``csv``); ``TagSuggestion.source`` stays a
# plain ``str`` so older plans still load.
SUGGESTOR_SOURCES: tuple[str, ...] = (
    "filename",
    "path",
    "group",
    "ucs_stem",
    "ucs_catalog",
    "synonym",
    "csv",
)

# Source priority used when competing suggestions resolve to the same field.
# Confidence remains meaningful for filtering and review, but provenance wins
# conflicts across sources in this order.
_SOURCE_PRIORITY: dict[str, int] = {
    "ucs_stem": 60,
    "ucs_catalog": 50,
    "group": 40,
    "path": 30,
    "filename": 20,
    "synonym": 10,
}

# Internal punctuation that should be split out of a value rather than left
# embedded inside a token. Mirrors ``_SEPARATOR_RE`` for value-level cleanup.
_VALUE_INTERNAL_PUNCT_RE = re.compile(r"[()\[\]{}<>;,!?\"'`/\\|]")
_VALUE_WHITESPACE_RE = re.compile(r"\s+")

# Per-canonical-field case rule. Free-form description-style fields title-case
# each token; UCS fields stay UPPERCASE to match the catalog spec; keywords
# lowercase for search-language style; structural fields pass through.
_FIELD_PASSTHROUGH = frozenset({"take_number", "channel_position"})
_FIELD_UPPERCASE = frozenset({"ucs_category", "ucs_subcategory"})
_FIELD_LOWERCASE = frozenset({"keyword"})


def _clean_suggestion_value(field: str, value: str) -> str:
    """Return a normalized value for *field*, or empty string to drop the suggestion.

    Rules:
    - UCS fields → uppercase, punctuation flattened, single-space collapsed.
    - ``take_number`` / ``channel_position`` → whitespace-collapsed passthrough.
    - ``keyword`` → token-level lowercase.
    - Everything else (description/title/comment/category/subcategory) →
      title-case each token via :func:`_title_case_token`.
    - Drops pure-digit tokens, single-character tokens (except known
      abbreviations), and tokens that become empty after stripping punctuation.
    """
    canonical = canonicalize(field)
    stripped = value.strip()
    if not stripped:
        return ""
    if canonical not in _FIELD_PASSTHROUGH:
        stripped = clean_tag_suggestion_text(stripped).strip()
        if not stripped:
            return ""
    if canonical in _FIELD_UPPERCASE:
        flattened = _VALUE_INTERNAL_PUNCT_RE.sub(" ", stripped)
        return _VALUE_WHITESPACE_RE.sub(" ", flattened).strip().upper()
    if canonical in _FIELD_PASSTHROUGH:
        return _VALUE_WHITESPACE_RE.sub(" ", stripped)

    flattened = _VALUE_INTERNAL_PUNCT_RE.sub(" ", stripped)
    out: list[str] = []
    for raw in flattened.split():
        if not raw:
            continue
        if raw.isdigit():
            continue
        if len(raw) == 1 and raw.upper() not in _ABBREVIATIONS:
            continue
        if canonical in _FIELD_LOWERCASE:
            out.append(raw.lower())
        else:
            out.append(_title_case_token(raw))
    return " ".join(out)


def _merge_evidence(winner_evidence: list[str], extras: list[str]) -> list[str]:
    """Append evidence lines that aren't already in *winner_evidence*."""
    merged = list(winner_evidence)
    for line in extras:
        if line not in merged:
            merged.append(line)
    return merged


def _source_rank(suggestion: TagSuggestion) -> tuple[int, float]:
    """Rank suggestions by source priority first, confidence second."""
    return (_SOURCE_PRIORITY.get(suggestion.source.lower(), 0), suggestion.confidence)


def normalize_and_dedupe(suggestions: list[TagSuggestion]) -> list[TagSuggestion]:
    """Clean, dedupe, and resolve single-value contention across suggestors.

    This is the final stage of :func:`run_suggestors`. It guarantees:
    1. Each suggestion's value is junk-stripped and case-normalized per field.
    2. The same ``(canonical_field, casefolded_value)`` only appears once;
       the highest-priority source wins, then confidence breaks ties within
       the same priority. Loser sources fold into ``evidence`` as
       ``also_from:<source>:<method>`` entries.
    3. For single-value fields with distinct values across sources, only the
       highest-priority source survives; alternates are recorded as
       ``alternative:<value>:<source>:<confidence>`` evidence on the winner.
    """
    # Step 1: clean each value; drop suggestions that no longer carry content.
    cleaned: list[TagSuggestion] = []
    for suggestion in suggestions:
        new_value = _clean_suggestion_value(suggestion.field, suggestion.value)
        if not new_value:
            continue
        if new_value == suggestion.value:
            cleaned.append(suggestion)
        else:
            cleaned.append(suggestion.model_copy(update={"value": new_value}))

    # Step 2: merge identical (canonical_field, value) suggestions across sources.
    by_value: dict[tuple[str, str], TagSuggestion] = {}
    insertion_order: list[tuple[str, str]] = []
    for suggestion in cleaned:
        canonical = canonicalize(suggestion.field)
        key = (canonical, normalize_value_for_dedup(suggestion.value))
        existing = by_value.get(key)
        if existing is None:
            by_value[key] = suggestion
            insertion_order.append(key)
            continue
        if _source_rank(suggestion) > _source_rank(existing):
            winner, loser = suggestion, existing
        else:
            winner, loser = existing, suggestion
        merged = _merge_evidence(
            list(winner.evidence),
            [f"also_from:{loser.source}:{loser.method}", *loser.evidence],
        )
        by_value[key] = winner.model_copy(update={"evidence": merged})

    # Step 3: resolve single-value contention; multivalue fields keep everything.
    by_field: dict[str, list[tuple[str, str]]] = {}
    for key in insertion_order:
        canonical = key[0]
        by_field.setdefault(canonical, []).append(key)

    keep: set[tuple[str, str]] = set()
    for canonical, keys in by_field.items():
        if len(keys) == 1 or is_multivalue(canonical):
            keep.update(keys)
            continue
        # Single-value field with multiple distinct values: source priority
        # wins, with confidence as the tie-breaker. The other values become
        # ``alternative:...`` evidence so the reviewer can see the runners-up
        # without a separate plan row.
        keys_sorted = sorted(keys, key=lambda k: _source_rank(by_value[k]), reverse=True)
        winner_key = keys_sorted[0]
        loser_keys = keys_sorted[1:]
        if loser_keys:
            winner = by_value[winner_key]
            extras = [
                f"alternative:{by_value[k].value}:{by_value[k].source}:{by_value[k].confidence:.2f}" for k in loser_keys
            ]
            by_value[winner_key] = winner.model_copy(
                update={"evidence": _merge_evidence(list(winner.evidence), extras)}
            )
        keep.add(winner_key)

    return [by_value[key] for key in insertion_order if key in keep]


# The intermediate ``list[Suggestor]`` is purely for type-checking: it forces
# each concrete instance to be widened to the Protocol type, so the resulting
# tuple is correctly inferred as ``tuple[Suggestor, ...]`` rather than the
# concrete heterogenous tuple type mypy would otherwise pick.
_DEFAULT_SUGGESTOR_LIST: list[Suggestor] = [
    UcsStemSuggestor(),
    GroupSuggestor(),
    FilenameSuggestor(),
    PathSuggestor(),
    UcsPriorTagSuggestor(),
    SynonymSuggestor(),
]

DEFAULT_SUGGESTORS: tuple[Suggestor, ...] = tuple(_DEFAULT_SUGGESTOR_LIST)
"""Ordered list of suggestors used by :func:`build_tag_suggestion_report`.

Order matters: stages that gate on prior evidence (FilenameSuggestor's
``skip_description`` and UcsPriorTagSuggestor's catalog remap) must come after
the sources they consult. SynonymSuggestor runs last so it enriches the chosen
UCS/semantic evidence instead of driving UCS classification.
"""


def run_suggestors(ctx: SuggestContext, suggestors: Iterable[Suggestor] = DEFAULT_SUGGESTORS) -> list[TagSuggestion]:
    """Run *suggestors* in order against *ctx*, feeding each the accumulated prior list.

    Returns the concatenated list of all suggestions after a final
    :func:`normalize_and_dedupe` pass that cleans values, enforces per-field
    case, and resolves cross-source duplicates. Confidence- and
    source/field-filtering still happens in :func:`build_tag_suggestion_report`
    on the cleaned output.
    """
    accumulated: list[TagSuggestion] = []
    for suggestor in suggestors:
        accumulated.extend(suggestor.propose(ctx, accumulated))
    return normalize_and_dedupe(accumulated)


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
    cancel_requested: Callable[[], bool] | None = None,
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

    root = resolve_scope_root(root)
    # Surface the prep phase explicitly — these two queries each pull every
    # in-scope file from the DB (and ``_build_group_index`` runs the audit
    # itself). On a 50k-file library they're several seconds combined and
    # the UI used to show nothing.
    if progress_callback is not None:
        progress_callback("loading", 0, None, "Loading indexed files...")
    rows = _load_files(root, db_path)
    if cancel_requested is not None and cancel_requested():
        raise InterruptedError("Tag suggestion generation cancelled")
    if progress_callback is not None:
        progress_callback("loading", len(rows), len(rows), f"Loaded {len(rows):,} file(s); building group index...")
    group_index = _build_group_index(root, db_path)
    if cancel_requested is not None and cancel_requested():
        raise InterruptedError("Tag suggestion generation cancelled")
    if progress_callback is not None:
        progress_callback("loading", len(rows), len(rows), "Loaded group index; loading UCS catalog...")
    catalog: UcsCatalog | None = None
    resolved_catalog_path: Path | None = None
    if use_ucs_catalog or ucs_catalog_path is not None:
        resolved_catalog_path = resolve_catalog_path(ucs_catalog_path)
        catalog = load_catalog(ucs_catalog_path)
        if catalog is None:
            raise ValueError("No UCS catalog loaded. Run `sfx ucs import SOURCE` first or pass --ucs-catalog.")
    if cancel_requested is not None and cancel_requested():
        raise InterruptedError("Tag suggestion generation cancelled")
    catalog_prior_index = PriorCatalogIndex.build(catalog) if catalog is not None else None

    entries: list[TagSuggestionEntry] = []
    by_source: dict[str, int] = {}
    by_field: dict[str, int] = {}
    by_bucket: dict[str, int] = {}
    files_with_suggestions = 0
    total_suggestions = 0

    from sfxworkbench.utils import progress_interval

    total_rows = len(rows)
    report_every = min(progress_interval(total_rows), 250)
    if progress_callback is not None:
        progress_callback("suggesting", 0, total_rows, f"Processing {total_rows:,} indexed file(s)...")

    for row_index, row in enumerate(rows):
        if cancel_requested is not None and row_index % 100 == 0 and cancel_requested():
            raise InterruptedError("Tag suggestion generation cancelled")
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
            catalog_prior_index=catalog_prior_index,
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
        # Report at the log-scaled interval so a 1M-file suggestion run
        # doesn't fire 20k status updates. Always report the final row so
        # the bar lands at 100%, even when this file yields no suggestions.
        if progress_callback is not None and (
            row_index == 0 or (row_index + 1) % report_every == 0 or row_index + 1 == total_rows
        ):
            progress_callback(
                "suggesting",
                row_index + 1,
                total_rows,
                f"{row['filename']}",
            )
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
