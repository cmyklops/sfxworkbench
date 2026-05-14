"""Evidence-fusion UCS tag proposals.

This is intentionally report-only. It treats UCS as the target vocabulary, not
as something filenames can prove on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.db import (
    DEFAULT_DB_PATH,
    get_connection,
    path_scope_filter,
    path_scope_params,
    resolve_scope_root,
    scoped_relative_parts,
)
from sfxworkbench.metadata_write import read_bwfmetaedit_fields
from sfxworkbench.models import (
    TagProposal,
    TagProposalEntry,
    TagProposalEvidence,
    TagProposalReport,
    TagProposalSummary,
    UcsCatalog,
    UcsEntry,
)
from sfxworkbench.ucs import parse_ucs_stem
from sfxworkbench.ucs_catalog import load_catalog, lookup_entry, resolve_catalog_path

console = Console()

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LOW_VALUE_TOKENS = {
    "audio",
    "addition",
    "anniversary",
    "big",
    "by",
    "content",
    "contents",
    "complete",
    "edition",
    "file",
    "files",
    "free",
    "general",
    "high",
    "library",
    "large",
    "low",
    "massive",
    "medium",
    "mid",
    "mini",
    "misc",
    "other",
    "of",
    "pack",
    "sample",
    "samples",
    "series",
    "small",
    "sound",
    "sounds",
    "source",
    "version",
    "vol",
    "volume",
    "various",
    "wav",
    "wave",
    "waves",
    "year",
    "years",
}
_BROAD_OPENING_TOKENS = {
    "cloth",
    "fabric",
    "glass",
    "leather",
    "loop",
    "metal",
    "paper",
    "plastic",
    "room",
    "rubber",
    "sea",
    "stone",
    "tone",
    "tonal",
    "walla",
    "wood",
}


@dataclass
class _CandidateEvidence:
    filename_tokens: set[str] = field(default_factory=set)
    path_tokens: set[str] = field(default_factory=set)
    embedded_metadata: set[str] = field(default_factory=set)
    accepted_ucs: set[str] = field(default_factory=set)
    accepted_category: set[str] = field(default_factory=set)
    accepted_semantic: set[str] = field(default_factory=set)
    accepted_category_conflict: bool = False


@dataclass
class _OpeningDiagnostic:
    source: str
    token: str
    catalog_matches: int = 0
    opened_candidates: int = 0
    blocked_candidates: int = 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 1 and not token.isdigit() and token not in _LOW_VALUE_TOKENS
    }


def _entry_terms(entry: UcsEntry, *, include_synonyms: bool = True) -> set[str]:
    terms = _tokens(entry.cat_short) | _tokens(entry.category) | _tokens(entry.subcategory)
    if include_synonyms:
        for synonym in entry.synonyms:
            terms.update(_tokens(synonym))
    return terms


def _build_term_index(catalog: UcsCatalog) -> tuple[dict[str, list[UcsEntry]], dict[str, set[str]]]:
    index: dict[str, list[UcsEntry]] = {}
    terms_by_cat_id: dict[str, set[str]] = {}
    for entry in catalog.entries:
        terms = _entry_terms(entry)
        terms_by_cat_id[entry.cat_id] = terms
        for term in _tokens(entry.subcategory):
            index.setdefault(term, []).append(entry)
    return index, terms_by_cat_id


def _load_rows(db_path: Path, root: Path):
    conn = get_connection(db_path)
    rows = conn.execute(
        f"""
        SELECT id, path, filename, stem, extension, size_bytes, mtime, md5,
               has_bext, has_riff_info
        FROM files
        WHERE {path_scope_filter()}
          AND scan_error IS NULL
        ORDER BY path
        """,
        path_scope_params(root),
    ).fetchall()
    tags = conn.execute(
        f"""
        SELECT t.file_id, t.field, t.value, t.source
        FROM accepted_tags t
        JOIN files f ON f.id = t.file_id
        WHERE {path_scope_filter("f.path")}
        ORDER BY t.field, t.value
        """,
        path_scope_params(root),
    ).fetchall()
    fields = conn.execute(
        f"""
        SELECT mf.file_id, mf.namespace, mf.key, mf.value, mf.source
        FROM metadata_fields mf
        JOIN files f ON f.id = mf.file_id
        WHERE {path_scope_filter("f.path")}
        ORDER BY mf.namespace, mf.key, mf.value
        """,
        path_scope_params(root),
    ).fetchall()
    descriptors = conn.execute(
        f"""
        SELECT d.file_id, d.backend, d.backend_version, d.parameters_hash,
               d.duration_bucket, d.segment_count, d.spectral_centroid,
               d.spectral_rolloff, d.transient_density, d.error
        FROM audio_descriptors d
        JOIN files f ON f.id = d.file_id
        WHERE {path_scope_filter("f.path")}
          AND d.error IS NULL
        ORDER BY d.generated_at DESC
        """,
        path_scope_params(root),
    ).fetchall()
    conn.close()

    tags_by_file: dict[int, list[dict]] = {}
    for tag in tags:
        tags_by_file.setdefault(tag["file_id"], []).append(dict(tag))
    fields_by_file: dict[int, list[dict]] = {}
    for metadata_field in fields:
        fields_by_file.setdefault(metadata_field["file_id"], []).append(dict(metadata_field))
    descriptors_by_file: dict[int, list[dict]] = {}
    for descriptor in descriptors:
        descriptors_by_file.setdefault(descriptor["file_id"], []).append(dict(descriptor))
    return rows, tags_by_file, fields_by_file, descriptors_by_file


def _path_tokens(path: Path, root: Path) -> set[str]:
    relative_parts = scoped_relative_parts(path, root)
    parts = relative_parts[:-1] if relative_parts is not None else path.parts[:-1]
    tokens: set[str] = set()
    for part in parts:
        tokens.update(_tokens(part))
    return tokens


def _embedded_metadata_tokens(row, indexed_fields: list[dict] | None = None) -> set[str]:
    if indexed_fields:
        tokens: set[str] = set()
        for field in indexed_fields:
            tokens.update(_tokens(field.get("value")))
        return tokens
    extension = (row["extension"] or "").lower()
    if extension not in {".wav", ".rf64"}:
        return set()
    fields: list[str] = []
    if row["has_bext"]:
        fields.append("Description")
    if row["has_riff_info"]:
        fields.append("IKEY")
    if not fields:
        return set()
    try:
        values = read_bwfmetaedit_fields(Path(row["path"]), fields)
    except Exception:
        return set()

    tokens: set[str] = set()
    for value in values.values():
        if isinstance(value, list):
            for item in value:
                tokens.update(_tokens(item))
        else:
            tokens.update(_tokens(value))
    return tokens


def _lookup_entry_by_category_or_short(
    catalog: UcsCatalog, category_or_short: str | None, subcategory: str | None
) -> UcsEntry | None:
    if not category_or_short or not subcategory:
        return None
    wanted_category = category_or_short.strip().upper()
    wanted_subcategory = subcategory.strip().upper()
    for entry in catalog.entries:
        if entry.subcategory != wanted_subcategory:
            continue
        if entry.cat_short == wanted_category or entry.category.upper() == wanted_category:
            return entry
    return None


def _token_can_open_entry(entry: UcsEntry, source_tokens: set[str], matches: list[UcsEntry], *, token: str) -> bool:
    category_terms = _tokens(entry.cat_short) | _tokens(entry.category)
    if token in _BROAD_OPENING_TOKENS:
        return bool(source_tokens & category_terms)
    if len(matches) <= 3:
        return True
    return bool(source_tokens & category_terms)


def _candidate_entries(
    tokens_by_source: dict[str, set[str]],
    index: dict[str, list[UcsEntry]],
    exact_entries: list[UcsEntry],
    opening_diagnostics: dict[tuple[str, str], _OpeningDiagnostic],
) -> list[UcsEntry]:
    by_cat_id: dict[str, UcsEntry] = {}
    for entry in exact_entries:
        by_cat_id[entry.cat_id] = entry

    context_sources = ("path", "accepted_category", "accepted_semantic")
    for source in context_sources:
        for token in tokens_by_source[source]:
            matches = index.get(token, [])
            diagnostic = opening_diagnostics.setdefault((source, token), _OpeningDiagnostic(source=source, token=token))
            diagnostic.catalog_matches = max(diagnostic.catalog_matches, len(matches))
            for entry in matches:
                can_open = source == "accepted_category" or _token_can_open_entry(
                    entry, tokens_by_source[source], matches, token=token
                )
                if not can_open:
                    diagnostic.blocked_candidates += 1
                    continue
                diagnostic.opened_candidates += 1
                by_cat_id[entry.cat_id] = entry

    embedded_tokens = tokens_by_source["embedded_metadata"]
    for token in embedded_tokens:
        matches = index.get(token, [])
        diagnostic = opening_diagnostics.setdefault(
            ("embedded_metadata", token), _OpeningDiagnostic(source="embedded_metadata", token=token)
        )
        diagnostic.catalog_matches = max(diagnostic.catalog_matches, len(matches))
        for entry in matches:
            if not _token_can_open_entry(entry, embedded_tokens, matches, token=token):
                diagnostic.blocked_candidates += 1
                continue
            category_terms = _tokens(entry.cat_short) | _tokens(entry.category)
            if embedded_tokens & category_terms:
                diagnostic.opened_candidates += 1
                by_cat_id[entry.cat_id] = entry
            else:
                diagnostic.blocked_candidates += 1

    has_context = any(tokens_by_source[source] for source in context_sources)
    if has_context:
        for token in tokens_by_source["filename"]:
            matches = index.get(token, [])
            diagnostic = opening_diagnostics.setdefault(
                ("filename", token), _OpeningDiagnostic(source="filename", token=token)
            )
            diagnostic.catalog_matches = max(diagnostic.catalog_matches, len(matches))
            for entry in matches:
                if not _token_can_open_entry(entry, tokens_by_source["filename"], matches, token=token):
                    diagnostic.blocked_candidates += 1
                    continue
                diagnostic.opened_candidates += 1
                by_cat_id[entry.cat_id] = entry
    return sorted(by_cat_id.values(), key=lambda entry: (entry.category, entry.subcategory, entry.cat_id))


def _top_opening_diagnostics(
    opening_diagnostics: dict[tuple[str, str], _OpeningDiagnostic],
) -> tuple[list[dict], list[dict]]:
    diagnostics = list(opening_diagnostics.values())

    def as_row(item: _OpeningDiagnostic) -> dict:
        return {
            "source": item.source,
            "token": item.token,
            "catalog_matches": item.catalog_matches,
            "opened_candidates": item.opened_candidates,
            "blocked_candidates": item.blocked_candidates,
        }

    opened = sorted(
        (item for item in diagnostics if item.opened_candidates),
        key=lambda item: (-item.opened_candidates, -item.catalog_matches, item.source, item.token),
    )
    blocked = sorted(
        (item for item in diagnostics if item.blocked_candidates),
        key=lambda item: (-item.blocked_candidates, -item.catalog_matches, item.source, item.token),
    )
    return [as_row(item) for item in opened[:25]], [as_row(item) for item in blocked[:25]]


def _collect_evidence(entry: UcsEntry, terms: set[str], tokens_by_source: dict[str, set[str]]) -> _CandidateEvidence:
    evidence = _CandidateEvidence()
    evidence.filename_tokens = terms & tokens_by_source["filename"]
    evidence.path_tokens = terms & tokens_by_source["path"]
    evidence.embedded_metadata = terms & tokens_by_source["embedded_metadata"]
    evidence.accepted_ucs = terms & tokens_by_source["accepted_ucs"]
    evidence.accepted_category = terms & tokens_by_source["accepted_category"]
    evidence.accepted_semantic = terms & tokens_by_source["accepted_semantic"]
    evidence.accepted_category_conflict = bool(tokens_by_source["accepted_category"] and not evidence.accepted_category)
    return evidence


def _proposal_from_evidence(entry: UcsEntry, evidence: _CandidateEvidence) -> TagProposal | None:
    tokens_by_source = {
        "filename": evidence.filename_tokens,
        "path": evidence.path_tokens,
        "embedded_metadata": evidence.embedded_metadata,
        "accepted_ucs": evidence.accepted_ucs,
        "accepted_category": evidence.accepted_category,
        "accepted_semantic": evidence.accepted_semantic,
    }
    sources = {source for source, tokens in tokens_by_source.items() if tokens}
    if not sources:
        return None

    category_terms = _tokens(entry.cat_short) | _tokens(entry.category)
    subcategory_terms = _tokens(entry.subcategory)
    category_sources = {
        source
        for source, tokens in tokens_by_source.items()
        if tokens & category_terms and source not in {"accepted_semantic"}
    }
    subcategory_sources = {
        source
        for source, tokens in tokens_by_source.items()
        if tokens & subcategory_terms and source not in {"accepted_semantic"}
    }

    notes: list[str] = []
    action = "review"
    if evidence.accepted_category_conflict:
        strength = "blocked"
        confidence = 0.2
        action = "blocked"
        notes.append("existing accepted category/subcategory does not corroborate this UCS candidate")
    elif "accepted_category" in sources or "accepted_semantic" in sources:
        strength = "strong"
        confidence = 0.9
        action = "review"
        notes.append("existing accepted semantic metadata corroborates this UCS candidate")
    elif category_sources and subcategory_sources and "path" in sources:
        strength = "strong"
        confidence = 0.82
    elif category_sources and subcategory_sources and sources == {"embedded_metadata"}:
        strength = "review"
        confidence = 0.62
        notes.append("embedded metadata includes both category and subcategory context")
    elif subcategory_sources and len(sources) >= 2:
        strength = "review"
        confidence = 0.68
        notes.append("subcategory evidence is present, but category context is incomplete")
    elif len(sources) >= 2:
        strength = "weak"
        confidence = 0.5
        action = "hold"
        notes.append("multiple weak evidence sources agree, but no subcategory corroboration")
    else:
        strength = "weak"
        confidence = 0.45
        action = "hold"
        notes.append("single evidence source; do not apply without more context")

    evidence_rows: list[TagProposalEvidence] = []
    for source, tokens in [
        ("filename", evidence.filename_tokens),
        ("path", evidence.path_tokens),
        ("embedded_metadata", evidence.embedded_metadata),
        ("accepted_ucs", evidence.accepted_ucs),
        ("accepted_category", evidence.accepted_category),
        ("accepted_semantic", evidence.accepted_semantic),
    ]:
        if tokens:
            evidence_rows.append(
                TagProposalEvidence(
                    source=source,
                    value=", ".join(sorted(tokens)),
                    detail=f"matched UCS terms for {entry.category}/{entry.subcategory}",
                )
            )

    return TagProposal(
        category=entry.category,
        subcategory=entry.subcategory,
        cat_short=entry.cat_short,
        cat_id=entry.cat_id,
        confidence=confidence,
        strength=strength,
        action=action,
        evidence=evidence_rows,
        notes=notes,
    )


def _similarity_evidence_rows(descriptors: list[dict] | None) -> list[TagProposalEvidence]:
    if not descriptors:
        return []
    descriptor = descriptors[0]
    bits = [
        f"backend={descriptor.get('backend')}",
        f"version={descriptor.get('backend_version') or 'unknown'}",
    ]
    if descriptor.get("duration_bucket"):
        bits.append(f"duration_bucket={descriptor['duration_bucket']}")
    if descriptor.get("segment_count") is not None:
        bits.append(f"segments={descriptor['segment_count']}")
    if descriptor.get("spectral_centroid") is not None:
        bits.append(f"spectral_centroid={float(descriptor['spectral_centroid']):.1f}")
    if descriptor.get("transient_density") is not None:
        bits.append(f"transient_density={float(descriptor['transient_density']):.3f}")
    return [
        TagProposalEvidence(
            source="similarity_descriptor",
            value=", ".join(bits),
            detail="cached deterministic audio descriptor; review-only support, not semantic proof",
        )
    ]


def build_tag_proposal_report(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    catalog_path: Path | None = None,
    limit: int = 200,
    min_confidence: float = 0.0,
) -> TagProposalReport:
    """Propose candidate UCS tags from corroborated evidence. No writes."""
    if limit < 0:
        raise ValueError("--limit must be 0 or greater")
    if min_confidence < 0 or min_confidence > 1:
        raise ValueError("--min-confidence must be between 0 and 1")
    root = resolve_scope_root(root)
    resolved_catalog_path = resolve_catalog_path(catalog_path)
    catalog = load_catalog(catalog_path)
    if catalog is None:
        raise ValueError("No UCS catalog loaded. Run `sfx ucs import SOURCE` first or pass --catalog.")

    index, terms_by_cat_id = _build_term_index(catalog)
    rows, tags_by_file, fields_by_file, descriptors_by_file = _load_rows(db_path, root)
    entries: list[TagProposalEntry] = []
    by_strength: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_category: dict[str, int] = {}
    opening_diagnostics: dict[tuple[str, str], _OpeningDiagnostic] = {}
    total_proposals = 0

    for row in rows:
        path = Path(row["path"])
        accepted_ucs_tokens: set[str] = set()
        accepted_ucs_category: str | None = None
        accepted_ucs_subcategory: str | None = None
        accepted_category_tokens: set[str] = set()
        accepted_semantic_tokens: set[str] = set()
        for tag in tags_by_file.get(row["id"], []):
            if tag["field"] in {"ucs_category", "ucs_subcategory"}:
                accepted_ucs_tokens.update(_tokens(tag["value"]))
                if tag["field"] == "ucs_category":
                    accepted_ucs_category = tag["value"]
                if tag["field"] == "ucs_subcategory":
                    accepted_ucs_subcategory = tag["value"]
            elif tag["field"] in {"category", "subcategory"}:
                accepted_category_tokens.update(_tokens(tag["value"]))
            elif tag["field"] in {"description", "keyword", "keywords"}:
                accepted_semantic_tokens.update(_tokens(tag["value"]))

        exact_entries: list[UcsEntry] = []
        parsed = parse_ucs_stem(row["stem"] or path.stem)
        filename_entry = lookup_entry(catalog, parsed.category, parsed.subcategory) if parsed.is_ucs else None
        if filename_entry is not None:
            exact_entries.append(filename_entry)
        accepted_ucs_entry = _lookup_entry_by_category_or_short(
            catalog, accepted_ucs_category, accepted_ucs_subcategory
        )
        if accepted_ucs_entry is not None:
            exact_entries.append(accepted_ucs_entry)

        tokens_by_source = {
            "filename": _tokens(row["stem"] or path.stem),
            "path": _path_tokens(path, root),
            "embedded_metadata": _embedded_metadata_tokens(row, fields_by_file.get(row["id"])),
            "accepted_ucs": accepted_ucs_tokens,
            "accepted_category": accepted_category_tokens,
            "accepted_semantic": accepted_semantic_tokens,
        }

        proposals: list[TagProposal] = []
        for candidate in _candidate_entries(tokens_by_source, index, exact_entries, opening_diagnostics):
            evidence = _collect_evidence(candidate, terms_by_cat_id[candidate.cat_id], tokens_by_source)
            proposal = _proposal_from_evidence(candidate, evidence)
            if proposal is None or proposal.confidence < min_confidence:
                continue
            proposal.evidence.extend(_similarity_evidence_rows(descriptors_by_file.get(row["id"])))
            proposals.append(proposal)

        if not proposals:
            continue
        proposals.sort(key=lambda item: (-item.confidence, item.category, item.subcategory))
        total_proposals += len(proposals)
        for proposal in proposals:
            by_strength[proposal.strength] = by_strength.get(proposal.strength, 0) + 1
            by_action[proposal.action] = by_action.get(proposal.action, 0) + 1
            by_category[proposal.category] = by_category.get(proposal.category, 0) + 1
        entries.append(
            TagProposalEntry(
                file_id=row["id"],
                path=str(path),
                filename=row["filename"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                md5=row["md5"],
                proposals=proposals,
            )
        )

    selected = entries if limit == 0 else entries[:limit]
    top_opening_tokens, top_blocked_tokens = _top_opening_diagnostics(opening_diagnostics)
    return TagProposalReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        db_path=str(db_path),
        catalog_path=str(resolved_catalog_path.resolve()) if resolved_catalog_path is not None else None,
        catalog_release_version=catalog.provenance.release_version,
        limit=limit,
        min_confidence=min_confidence,
        summary=TagProposalSummary(
            files_considered=len(rows),
            files_with_proposals=len(entries),
            total_proposals=total_proposals,
            by_strength=dict(sorted(by_strength.items())),
            by_action=dict(sorted(by_action.items())),
            by_category=dict(sorted(by_category.items())),
            top_opening_tokens=top_opening_tokens,
            top_blocked_tokens=top_blocked_tokens,
        ),
        entries=selected,
    )


def show_tag_proposal_report(report: TagProposalReport) -> None:
    summary = report.summary
    console.print(
        f"Considered [yellow]{summary.files_considered:,}[/yellow] file(s); "
        f"found [yellow]{summary.total_proposals:,}[/yellow] UCS proposal(s) "
        f"across [yellow]{summary.files_with_proposals:,}[/yellow] file(s)."
    )
    table = Table(title="Proposal summary", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")
    for strength, count in summary.by_strength.items():
        table.add_row(f"strength:{strength}", f"{count:,}")
    for action, count in summary.by_action.items():
        table.add_row(f"action:{action}", f"{count:,}")
    console.print(table)

    if summary.top_opening_tokens:
        opening = Table(title="Top opening tokens", show_lines=False)
        opening.add_column("Source")
        opening.add_column("Token")
        opening.add_column("Catalog matches", justify="right")
        opening.add_column("Opened", justify="right")
        opening.add_column("Blocked", justify="right")
        for item in summary.top_opening_tokens[:10]:
            opening.add_row(
                str(item["source"]),
                str(item["token"]),
                f"{item['catalog_matches']:,}",
                f"{item['opened_candidates']:,}",
                f"{item['blocked_candidates']:,}",
            )
        console.print(opening)

    if not report.entries:
        return
    sample = Table(title="Sample proposals", show_lines=False)
    sample.add_column("File")
    sample.add_column("UCS")
    sample.add_column("Strength")
    sample.add_column("Conf", justify="right")
    sample.add_column("Evidence")
    for entry in report.entries[:20]:
        for proposal in entry.proposals[:3]:
            evidence = "; ".join(f"{item.source}:{item.value}" for item in proposal.evidence)
            sample.add_row(
                entry.filename,
                f"{proposal.category}/{proposal.subcategory}",
                proposal.strength,
                f"{proposal.confidence:.2f}",
                evidence,
            )
    console.print(sample)
