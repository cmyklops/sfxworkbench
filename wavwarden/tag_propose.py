"""Evidence-fusion UCS tag proposals.

This is intentionally report-only. It treats UCS as the target vocabulary, not
as something filenames can prove on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.db import DEFAULT_DB_PATH, get_connection
from wavwarden.metadata_write import read_bwfmetaedit_fields
from wavwarden.models import (
    TagProposal,
    TagProposalEntry,
    TagProposalEvidence,
    TagProposalReport,
    TagProposalSummary,
    UcsCatalog,
    UcsEntry,
)
from wavwarden.ucs import parse_ucs_stem
from wavwarden.ucs_catalog import load_catalog, lookup_entry, resolve_catalog_path

console = Console()

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LOW_VALUE_TOKENS = {
    "audio",
    "addition",
    "anniversary",
    "big",
    "content",
    "contents",
    "complete",
    "edition",
    "file",
    "files",
    "free",
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
    "pack",
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


@dataclass
class _CandidateEvidence:
    filename_tokens: set[str] = field(default_factory=set)
    path_tokens: set[str] = field(default_factory=set)
    embedded_metadata: set[str] = field(default_factory=set)
    accepted_ucs: set[str] = field(default_factory=set)
    accepted_category: set[str] = field(default_factory=set)
    accepted_semantic: set[str] = field(default_factory=set)
    accepted_category_conflict: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        """
        SELECT id, path, filename, stem, extension, size_bytes, mtime, md5,
               has_bext, has_riff_info
        FROM files
        WHERE (path = ? OR path LIKE ?)
          AND scan_error IS NULL
        ORDER BY path
        """,
        (str(root), str(root) + "/%"),
    ).fetchall()
    tags = conn.execute(
        """
        SELECT t.file_id, t.field, t.value, t.source
        FROM accepted_tags t
        JOIN files f ON f.id = t.file_id
        WHERE (f.path = ? OR f.path LIKE ?)
        ORDER BY t.field, t.value
        """,
        (str(root), str(root) + "/%"),
    ).fetchall()
    conn.close()

    tags_by_file: dict[int, list[dict]] = {}
    for tag in tags:
        tags_by_file.setdefault(tag["file_id"], []).append(dict(tag))
    return rows, tags_by_file


def _path_tokens(path: Path, root: Path) -> set[str]:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = path
    tokens: set[str] = set()
    for part in relative.parts[:-1]:
        tokens.update(_tokens(part))
    return tokens


def _embedded_metadata_tokens(row) -> set[str]:
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


def _candidate_entries(
    tokens_by_source: dict[str, set[str]], index: dict[str, list[UcsEntry]], exact_entries: list[UcsEntry]
) -> list[UcsEntry]:
    by_cat_id: dict[str, UcsEntry] = {}
    for entry in exact_entries:
        by_cat_id[entry.cat_id] = entry

    context_sources = ("path", "embedded_metadata", "accepted_category", "accepted_semantic")
    for source in context_sources:
        for token in tokens_by_source[source]:
            for entry in index.get(token, []):
                by_cat_id[entry.cat_id] = entry

    has_context = any(tokens_by_source[source] for source in context_sources)
    if has_context:
        for token in tokens_by_source["filename"]:
            for entry in index.get(token, []):
                by_cat_id[entry.cat_id] = entry
    return sorted(by_cat_id.values(), key=lambda entry: (entry.category, entry.subcategory, entry.cat_id))


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
    root = root.resolve()
    resolved_catalog_path = resolve_catalog_path(catalog_path)
    catalog = load_catalog(catalog_path)
    if catalog is None:
        raise ValueError("No UCS catalog loaded. Run `sfx ucs import SOURCE` first or pass --catalog.")

    index, terms_by_cat_id = _build_term_index(catalog)
    rows, tags_by_file = _load_rows(db_path, root)
    entries: list[TagProposalEntry] = []
    by_strength: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_category: dict[str, int] = {}
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
            "embedded_metadata": _embedded_metadata_tokens(row),
            "accepted_ucs": accepted_ucs_tokens,
            "accepted_category": accepted_category_tokens,
            "accepted_semantic": accepted_semantic_tokens,
        }

        proposals: list[TagProposal] = []
        for candidate in _candidate_entries(tokens_by_source, index, exact_entries):
            evidence = _collect_evidence(candidate, terms_by_cat_id[candidate.cat_id], tokens_by_source)
            proposal = _proposal_from_evidence(candidate, evidence)
            if proposal is None or proposal.confidence < min_confidence:
                continue
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
