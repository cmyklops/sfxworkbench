"""Tiny beets-style query DSL over the SQLite ``files`` index.

Examples (each produces a parameterized SQL ``WHERE`` clause):

    ext:wav                       extension = 'wav'
    ext:wav,flac                  extension IN ('wav', 'flac')
    sample_rate:>=48000           sample_rate >= 48000
    sample_rate:44100..96000      sample_rate BETWEEN 44100 AND 96000
    channels:1                    channels = 1
    -ext:mp3                      NOT (extension = 'mp3')
    missing:bext                  has_bext IS NULL OR has_bext = 0
    has:bext                      has_bext = 1
    rain                          path/filename/stem LIKE '%rain%'

Multiple terms are ANDed. The DSL is intentionally narrow: no precedence, no
OR, no parentheses. Power users who want richer queries should drop down to
SQL directly. Adding new field aliases is a one-line change in
:data:`FIELD_ALIASES`; adding new boolean flags is a one-line change in
:data:`BOOLEAN_FLAGS`.

Used by the ``sfx ls QUERY`` CLI command.

Note on typing: ``Term.value`` is intentionally typed as ``object`` because the
allowed value types are op-dependent (string for ``=``, int/float for
comparison ops, ``tuple`` for ``between``, ``list`` for ``in``). The compiler
narrows via ``cast()`` at each branch rather than carrying a tagged-union
class hierarchy through every helper.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast


class QueryError(ValueError):
    """Raised when a query string can't be parsed or doesn't make sense for the schema."""


# Map user-visible field names → SQL column names. Keys are normalized by
# lowercasing the user input.
FIELD_ALIASES: dict[str, str] = {
    "ext": "extension",
    "extension": "extension",
    "path": "path",
    "stem": "stem",
    "name": "filename",
    "filename": "filename",
    "size": "size_bytes",
    "size_bytes": "size_bytes",
    "duration": "duration_s",
    "duration_s": "duration_s",
    "channels": "channels",
    "sample_rate": "sample_rate",
    "rate": "sample_rate",
    "sr": "sample_rate",
    "bit_depth": "bit_depth",
    "depth": "bit_depth",
    "md5": "md5",
    "is_ucs": "is_ucs",
}

# Numeric columns get ``>``, ``>=``, ``<``, ``<=``, and range (``a..b``) support.
NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {"size_bytes", "duration_s", "channels", "sample_rate", "bit_depth", "is_ucs"}
)

# Boolean ``has:X`` / ``missing:X`` flags backed by integer columns.
BOOLEAN_FLAGS: dict[str, str] = {
    "bext": "has_bext",
    "ixml": "has_ixml",
    "riff_info": "has_riff_info",
    "adm": "has_adm",
    "cue_markers": "has_cue_markers",
    "sampler": "has_sampler",
}


@dataclass(frozen=True)
class Term:
    """One parsed query term.

    Attributes
    ----------
    field:
        Canonical column or special token. ``"_text"`` is the synthetic field
        used for unprefixed free-text terms; ``"_flag"`` is the synthetic
        field used for ``has:X`` / ``missing:X``.
    op:
        Operator. One of ``"="``, ``">"``, ``">="``, ``"<"``, ``"<="``,
        ``"between"``, ``"in"``, ``"like"``, ``"has"``, ``"missing"``.
    value:
        Right-hand side of the comparison; ``None`` for ``has``/``missing``.
        ``tuple`` for ``between``; ``list`` for ``in``; ``str``/``int``/``float``
        otherwise.
    negated:
        ``True`` if the term was prefixed with ``-``.
    """

    field: str
    op: str
    value: object
    negated: bool = False


_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _normalize_extension(value: str) -> str:
    """Normalize a user-typed extension to the ``.wav``-with-dot form stored in DB."""
    stripped = value.strip().lower()
    return stripped if stripped.startswith(".") else f".{stripped}"


def _coerce_numeric(raw: str, *, term_text: str) -> int | float:
    if not _NUMERIC_RE.match(raw):
        raise QueryError(f"expected a number in {term_text!r}, got {raw!r}")
    return int(raw) if "." not in raw else float(raw)


def _split_top_level(query: str) -> list[str]:
    """Split *query* on unquoted whitespace, preserving ``"quoted phrases"``."""
    tokens: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in query:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch.isspace() and not in_quote:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(ch)
    if in_quote:
        raise QueryError("unmatched double quote in query")
    if current:
        tokens.append("".join(current))
    return tokens


def parse_query(query: str) -> list[Term]:
    """Parse *query* into a list of :class:`Term`s. Empty input returns ``[]``."""
    terms: list[Term] = []
    for raw_token in _split_top_level(query.strip()):
        negated = False
        token = raw_token
        if token.startswith("-") and len(token) > 1 and ":" in token[1:]:
            negated = True
            token = token[1:]
        if ":" not in token:
            terms.append(Term(field="_text", op="like", value=token, negated=negated))
            continue
        key, _, value = token.partition(":")
        key_lower = key.lower()
        if key_lower in {"has", "missing"}:
            if value not in BOOLEAN_FLAGS:
                allowed = ", ".join(sorted(BOOLEAN_FLAGS))
                raise QueryError(f"unknown flag {value!r} in {raw_token!r}; allowed: {allowed}")
            terms.append(
                Term(
                    field=BOOLEAN_FLAGS[value],
                    op="has" if key_lower == "has" else "missing",
                    value=None,
                    negated=negated,
                )
            )
            continue
        if key_lower not in FIELD_ALIASES:
            allowed = ", ".join(sorted(set(FIELD_ALIASES) | {"has", "missing"}))
            raise QueryError(f"unknown query field {key!r}; allowed: {allowed}")
        column = FIELD_ALIASES[key_lower]
        terms.append(_parse_op_and_value(column, value, term_text=raw_token, negated=negated))
    return terms


def _parse_op_and_value(column: str, value: str, *, term_text: str, negated: bool) -> Term:
    op = "="
    raw = value
    for prefix, prefix_op in ((">=", ">="), ("<=", "<="), (">", ">"), ("<", "<")):
        if raw.startswith(prefix):
            op = prefix_op
            raw = raw[len(prefix) :]
            break
    if ".." in raw and op == "=":
        lo_raw, _, hi_raw = raw.partition("..")
        if column not in NUMERIC_COLUMNS:
            raise QueryError(f"range queries (`..`) are only valid for numeric fields, not {column}")
        lo = _coerce_numeric(lo_raw, term_text=term_text)
        hi = _coerce_numeric(hi_raw, term_text=term_text)
        return Term(field=column, op="between", value=(lo, hi), negated=negated)
    if "," in raw and op == "=":
        items = [item.strip() for item in raw.split(",") if item.strip()]
        if not items:
            raise QueryError(f"empty value list in {term_text!r}")
        if column in NUMERIC_COLUMNS:
            items = [_coerce_numeric(item, term_text=term_text) for item in items]  # type: ignore[misc]
        return Term(field=column, op="in", value=items, negated=negated)
    if op != "=" and column not in NUMERIC_COLUMNS:
        raise QueryError(f"comparison operator {op!r} is only valid for numeric fields, not {column}")
    if column in NUMERIC_COLUMNS:
        coerced = _coerce_numeric(raw, term_text=term_text)
        return Term(field=column, op=op, value=coerced, negated=negated)
    return Term(field=column, op="=", value=raw, negated=negated)


def compile_query(terms: list[Term]) -> tuple[str, list[object]]:
    """Compile *terms* into a SQL ``WHERE`` body and parameter list.

    Returns ``("1=1", [])`` for an empty term list so callers can always splice
    the result into ``"WHERE {body}"`` without conditional logic.
    """
    if not terms:
        return "1=1", []
    fragments: list[str] = []
    params: list[object] = []
    for term in terms:
        fragment, term_params = _compile_term(term)
        if term.negated:
            fragment = f"NOT ({fragment})"
        fragments.append(fragment)
        params.extend(term_params)
    return " AND ".join(fragments), params


def _compile_term(term: Term) -> tuple[str, list[object]]:
    if term.field == "_text":
        like = f"%{term.value}%"
        return (
            "(LOWER(path) LIKE LOWER(?) OR LOWER(filename) LIKE LOWER(?) OR LOWER(stem) LIKE LOWER(?))",
            [like, like, like],
        )
    if term.op == "has":
        return f"({term.field} = 1)", []
    if term.op == "missing":
        return f"({term.field} IS NULL OR {term.field} = 0)", []
    if term.op == "between":
        # parse_query guarantees the tuple shape for between terms.
        bounds = cast(tuple[int | float, int | float], term.value)
        lo, hi = bounds
        return f"({term.field} BETWEEN ? AND ?)", [lo, hi]
    if term.op == "in":
        # parse_query guarantees value is a list of str/int/float for "in".
        raw_values = cast(Sequence[object], term.value)
        values: list[object] = list(raw_values)
        if term.field == "extension":
            # Stored as ".wav" etc.; user types "wav,flac".
            values = [_normalize_extension(str(v)) for v in values]
        placeholders = ",".join("?" for _ in values)
        return f"({term.field} IN ({placeholders}))", values
    if term.field == "extension":
        # Extensions are stored as ``.wav`` (with leading dot, lowercased).
        # Accept user input both with and without the dot.
        return "(LOWER(extension) = LOWER(?))", [_normalize_extension(str(term.value))]
    if term.op in {">", ">=", "<", "<=", "="}:
        return f"({term.field} {term.op} ?)", [term.value]
    raise QueryError(f"unhandled term: {term}")  # pragma: no cover (defensive)
