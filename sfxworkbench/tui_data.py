"""Read-only data adapters for the Textual review workbench."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sfxworkbench.apply_logs import APPLY_LOG_DIR_NAME
from sfxworkbench.audit_cmd import _STANDARD_SAMPLE_RATES
from sfxworkbench.db import DEFAULT_DB_PATH, get_connection
from sfxworkbench.metadata_fields import (
    canonicalize as _canonical_tag_field,
)
from sfxworkbench.metadata_fields import (
    is_multivalue,
    values_equal_for_dedup,
)
from sfxworkbench.preservation import build_preservation_rules

_TUI_LIBRARY_PATH_KEY = "tui_library_path"


@dataclass(frozen=True)
class DashboardMetric:
    key: str
    label: str
    value: int | str
    detail: str = ""
    severity: str = "info"


@dataclass(frozen=True)
class QueueSummary:
    key: str
    lane: str
    label: str
    count: int
    description: str
    next_action: str
    severity: str = "info"


@dataclass(frozen=True)
class StartStep:
    order: int
    label: str
    payoff: str
    status: str
    detail: str
    reason: str
    next_action: str
    destination: str
    destination_key: str = ""


@dataclass(frozen=True)
class FileRow:
    path: str
    filename: str
    extension: str | None = None
    size_bytes: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    duration_s: float | None = None
    is_ucs: bool = False
    has_bext: bool = False
    has_ixml: bool = False
    scan_error: str | None = None
    accepted_tag_count: int = 0
    metadata_field_count: int = 0
    issue_count: int = 0


@dataclass(frozen=True)
class QueueItem:
    queue_key: str
    label: str
    path: str
    detail: str = ""
    severity: str = "info"


@dataclass(frozen=True)
class ReviewPreset:
    queue_key: str
    label: str
    filter_text: str
    description: str


@dataclass(frozen=True)
class ReportPreset:
    label: str
    category: str
    query: str
    description: str


@dataclass(frozen=True)
class FileDetailSection:
    title: str
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FileDetail:
    path: str
    filename: str
    facts: tuple[tuple[str, str], ...]
    sections: tuple[FileDetailSection, ...] = ()
    issues: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanSummary:
    path: str
    category: str
    kind: str
    title: str
    entries: int = 0
    errors: int = 0
    protected: int = 0
    conflicts: int = 0
    undoable: bool = False
    description: str = ""


@dataclass(frozen=True)
class PlanDetailRow:
    kind: str
    action: str
    source: str
    target: str = ""
    status: str = ""
    detail: str = ""


@dataclass(frozen=True)
class WorkflowCapability:
    area: str
    workflow: str
    support: str
    signal: str
    next_action: str
    destination: str
    description: str


@dataclass(frozen=True)
class FeaturePage:
    key: str
    label: str
    status: str
    primary_count: int | str
    description: str


@dataclass(frozen=True)
class FeatureFinding:
    feature: str
    label: str
    count: int | str
    status: str = "info"
    detail: str = ""


@dataclass(frozen=True)
class DuplicateGroupRow:
    group_id: int
    hash: str
    copies: int
    extra_copies: int
    size_bytes: int | None
    wasted_bytes: int | None
    keep_path: str
    status: str = "pending"


@dataclass(frozen=True)
class TagDisplayItem:
    source: str
    field: str
    value: str
    status: str = ""
    evidence_source: str = ""


@dataclass(frozen=True)
class TagChangeRow:
    filename: str
    path: str
    status: str
    field: str
    value: str
    source: str = ""


@dataclass(frozen=True)
class MetadataWorkbenchRow:
    path: str
    filename: str
    embedded_fields: int = 0
    accepted_tags: int = 0
    pending_changes: int = 0
    approved_changes: int = 0
    rejected_changes: int = 0
    embedded_summary: str = ""
    accepted_summary: str = ""
    pending_summary: str = ""
    tags_summary: str = ""
    tag_items: tuple[TagDisplayItem, ...] = ()
    sources: str = ""
    status: str = "info"


_SEARCH_METADATA_KEYS: dict[tuple[str, str], int] = {
    ("bext", "description"): 0,
    ("riff_info", "icmt"): 1,
    ("riff_info", "ikey"): 2,
    ("riff_info", "inam"): 3,
    ("riff_info", "ignr"): 4,
    ("riff_info", "isbj"): 5,
    ("id3", "description"): 6,
    ("id3", "comment"): 7,
    ("id3", "title"): 8,
    ("vorbis", "description"): 9,
    ("vorbis", "comment"): 10,
    ("vorbis", "title"): 11,
    ("mp4", "description"): 12,
    ("mp4", "comment"): 13,
    ("mp4", "title"): 14,
}

_SEARCH_TAG_FIELDS: dict[str, int] = {
    "description": 0,
    "keywords": 1,
    "category": 2,
    "subcategory": 3,
    "ucs_category": 4,
    "ucs_subcategory": 5,
    "title": 6,
    "comment": 7,
}


def _clean_tag_value(value: object) -> str:
    text = str(value or "")
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-")
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+-\s+|\s+-|-\s+", " - ", text)
    text = re.sub(r"\s*[,;]\s*", ", ", text)
    text = re.sub(r"\s+([.!?:])", r"\1", text)
    text = re.sub(r"([.!?]){2,}", r"\1", text)
    return text.strip(" ,;")


def _combined_tags_summary(items: tuple[TagDisplayItem, ...]) -> str:
    return " | ".join(item.value for item in items[:8])


def _is_duplicate_tag_item(item: TagDisplayItem, existing_items: tuple[TagDisplayItem, ...]) -> bool:
    field = _canonical_tag_field(item.field)
    if not field:
        return False
    matching_items = [existing for existing in existing_items if _canonical_tag_field(existing.field) == field]
    if not matching_items:
        return False
    if is_multivalue(field):
        return any(values_equal_for_dedup(item.value, existing.value) for existing in matching_items)
    return True


def _pending_value_summary(item: TagDisplayItem) -> str:
    source_suffix = f" [{item.evidence_source}]" if item.evidence_source else ""
    return f"{item.status.upper()} {_tag_label(item.field)}: {item.value}{source_suffix}"


def _metadata_key_rank(namespace: str, key: str) -> int:
    return _SEARCH_METADATA_KEYS.get((namespace.lower(), key.lower()), 50)


def _tag_field_rank(field: str) -> int:
    return _SEARCH_TAG_FIELDS.get(field.lower(), 50)


def _metadata_label(namespace: str, key: str) -> str:
    normalized = key.lower()
    labels = {
        "description": "Description",
        "icmt": "Comment",
        "ikey": "Keywords",
        "inam": "Title",
        "ignr": "Category",
        "isbj": "Subject",
        "title": "Title",
        "comment": "Comment",
        "keywords": "Keywords",
        "category": "Category",
        "subcategory": "Subcategory",
    }
    label = labels.get(normalized, key)
    return f"{label} ({namespace})"


def _tag_label(field: str) -> str:
    labels = {
        "description": "Description",
        "keywords": "Keywords",
        "category": "Category",
        "subcategory": "Subcategory",
        "ucs_category": "UCS Category",
        "ucs_subcategory": "UCS Subcategory",
        "title": "Title",
        "comment": "Comment",
    }
    return labels.get(field.lower(), field)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        expanded = path.expanduser()
        key = str(expanded)
        if key in seen:
            continue
        seen.add(key)
        unique.append(expanded)
    return unique


def _like_filter_clause(
    expressions: tuple[str, ...],
    filter_text: str,
) -> tuple[str, tuple[str, ...]]:
    terms = tuple(term for term in filter_text.split() if term.strip())
    if not terms:
        return "", ()
    clauses: list[str] = []
    params: list[str] = []
    for term in terms:
        like = f"%{term}%"
        clauses.append("(" + " OR ".join(f"{expression} LIKE ?" for expression in expressions) + ")")
        params.extend([like] * len(expressions))
    return " AND " + " AND ".join(clauses), tuple(params)


def _audio_detail(row) -> str:
    parts: list[str] = []
    if row["sample_rate"] is not None:
        parts.append(f"{row['sample_rate']} Hz")
    if row["bit_depth"] is not None:
        parts.append(f"{row['bit_depth']}-bit")
    if row["channels"] is not None:
        parts.append(f"{row['channels']} ch")
    if row["duration_s"] is not None:
        parts.append(f"{float(row['duration_s']):.2f}s")
    return ", ".join(parts)


def _count(conn, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def _duplicate_group_count(conn) -> int:
    return _count(
        conn,
        """
        SELECT COUNT(*) FROM (
            SELECT md5 FROM files
            WHERE md5 IS NOT NULL
            GROUP BY md5
            HAVING COUNT(*) > 1
        )
        """,
    )


def _last_scan_root(conn) -> str:
    row = conn.execute("SELECT value FROM scan_meta WHERE key = 'last_scan_root'").fetchone()
    return str(row["value"]) if row and row["value"] else "PATH"


def library_root(db_path: Path = DEFAULT_DB_PATH) -> str:
    """Return the indexed library root used as the default command path."""
    try:
        conn = get_connection(db_path)
        try:
            return _last_scan_root(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return "PATH"


def saved_library_path(db_path: Path = DEFAULT_DB_PATH) -> str | None:
    """Return the last explicit TUI library path, if one was saved."""
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT value FROM scan_meta WHERE key = ?", (_TUI_LIBRARY_PATH_KEY,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    value = str(row["value"]).strip() if row and row["value"] else ""
    if not value or value == "PATH":
        return None
    return value


def save_library_path(db_path: Path = DEFAULT_DB_PATH, library_path: str | Path | None = None) -> str | None:
    """Persist the explicit TUI library path used for generated commands.

    Returns ``None`` on success, or a short human-readable error message if the
    write failed (e.g. SQLite is locked or the DB file is unwritable). Callers
    can surface the message in the TUI status strip rather than silently
    pretending the save succeeded.
    """
    value = str(library_path).strip() if library_path is not None else ""
    try:
        conn = get_connection(db_path)
        try:
            if not value or value == "PATH":
                conn.execute("DELETE FROM scan_meta WHERE key = ?", (_TUI_LIBRARY_PATH_KEY,))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO scan_meta (key, value) VALUES (?, ?)",
                    (_TUI_LIBRARY_PATH_KEY, value),
                )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"could not save library path: {exc}"
    return None


def preferred_library_path(db_path: Path = DEFAULT_DB_PATH) -> str:
    """Return the saved TUI path, falling back to the indexed scan root."""
    return saved_library_path(db_path) or library_root(db_path)


def _command_root(db_path: Path, library_path: str | Path | None = None) -> str:
    if library_path is not None and str(library_path).strip():
        return str(library_path).strip()
    return library_root(db_path)


def _quote_path(value: str | Path) -> str:
    text = str(value)
    if not text:
        return "PATH"
    if all(char not in text for char in " \t\n'\"()[]{}$&;|<>*?"):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _display_path(value: str | Path) -> str:
    path = str(value)
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1 :]
    return path


def _db_arg(db_path: Path) -> str:
    return f"--db {_quote_path(_display_path(db_path))}"


def report_search_paths(
    db_path: Path = DEFAULT_DB_PATH,
    report_paths: list[Path] | None = None,
    library_path: str | Path | None = None,
) -> list[Path]:
    """Return explicit or likely JSON report locations for the TUI report browser."""
    if report_paths:
        return _dedupe_paths(list(report_paths))

    candidates: list[Path] = []
    db_parent = db_path.expanduser().parent
    candidates.extend([db_parent / "reports", db_parent])

    root = str(library_path).strip() if library_path is not None and str(library_path).strip() else ""
    if not root and db_path.expanduser().exists():
        try:
            conn = get_connection(db_path)
            try:
                root = _last_scan_root(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            root = ""
    if root and root != "PATH":
        root_path = Path(root).expanduser()
        candidates.extend([root_path / "reports", root_path.parent / "reports"])

    candidates.append(Path.home() / "reports")
    return [path for path in _dedupe_paths(candidates) if path.exists()]


def indexed_library_size_gb(db_path: Path = DEFAULT_DB_PATH) -> float:
    """Return indexed file size in decimal GB from SQLite, without walking the library."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COALESCE(SUM(size_bytes), 0) AS total_bytes FROM files").fetchone()
    finally:
        conn.close()
    return float(row["total_bytes"] or 0) / 1_000_000_000


def dashboard_metrics(db_path: Path = DEFAULT_DB_PATH, config_path: Path | None = None) -> list[DashboardMetric]:
    """Return the first dashboard signals for the review workbench."""
    conn = get_connection(db_path)
    try:
        total = _count(conn, "SELECT COUNT(*) FROM files")
        scan_errors = _count(conn, "SELECT COUNT(*) FROM files WHERE scan_error IS NOT NULL")
        fn_issues = _count(conn, "SELECT COUNT(*) FROM fn_issues")
        missing_metadata = _count(conn, "SELECT COUNT(*) FROM files WHERE has_bext = 0 AND has_ixml = 0")
        unusual_rates = _count(
            conn,
            f"""
            SELECT COUNT(*) FROM files
            WHERE sample_rate IS NOT NULL
              AND sample_rate NOT IN ({",".join("?" for _ in _STANDARD_SAMPLE_RATES)})
            """,
            tuple(sorted(_STANDARD_SAMPLE_RATES)),
        )
        ucs_named = _count(conn, "SELECT COUNT(*) FROM files WHERE is_ucs = 1")
        duplicate_groups = _duplicate_group_count(conn)
        accepted_tags = _count(conn, "SELECT COUNT(*) FROM accepted_tags")
        db_only_tagged_files = _count(conn, "SELECT COUNT(DISTINCT file_id) FROM accepted_tags")
        similarity_segments = _count(conn, "SELECT COUNT(*) FROM audio_segments")
    finally:
        conn.close()

    rules = build_preservation_rules(config_path=config_path)
    return [
        DashboardMetric("indexed_files", "Indexed files", total),
        DashboardMetric("duplicate_groups", "Duplicate groups", duplicate_groups, severity="review"),
        DashboardMetric("missing_metadata", "Missing BEXT/iXML", missing_metadata, severity="review"),
        DashboardMetric("filename_issues", "Filename issues", fn_issues, severity="warning"),
        DashboardMetric("scan_errors", "Scan errors", scan_errors, severity="error" if scan_errors else "info"),
        DashboardMetric("ucs_named", "UCS-looking files", ucs_named),
        DashboardMetric("unusual_sample_rates", "Unusual sample-rate files", unusual_rates, severity="review"),
        DashboardMetric(
            "accepted_tags",
            "Accepted DB-only tags",
            accepted_tags,
            detail=f"{db_only_tagged_files:,} tagged file(s)",
        ),
        DashboardMetric("similarity_segments", "Similarity segments", similarity_segments),
        DashboardMetric("safe_folders", "Protected folders", len(rules.safe_folders), severity="safe"),
    ]


def feature_pages(db_path: Path = DEFAULT_DB_PATH, config_path: Path | None = None) -> list[FeaturePage]:
    """Return top-level operation pages and their current signal state."""
    metrics = {metric.key: metric for metric in dashboard_metrics(db_path=db_path, config_path=config_path)}
    queues = {queue.key: queue for queue in review_queues(db_path=db_path)}

    def metric_count(key: str) -> int | str:
        return metrics.get(key, DashboardMetric(key, key, 0)).value

    def queue_count(key: str) -> int:
        return queues.get(key, QueueSummary(key, "", key, 0, "", "")).count

    return [
        FeaturePage("scan", "Scan", "ready", metric_count("indexed_files"), "Refresh the index and run full audits."),
        FeaturePage("files", "Files", "ready", metric_count("indexed_files"), "Browse and audition indexed files."),
        FeaturePage(
            "clean",
            "Declutter",
            "ready",
            queue_count("filename_issues") + queue_count("long_paths") + queue_count("unicode_normalization"),
            "Remove junk, fix risky names, and review folder cleanup.",
        ),
        FeaturePage("dedupe", "Dedupe", "review", queue_count("duplicates"), "Review exact files and pack overlap."),
        FeaturePage(
            "metadata", "Metadata", "review", queue_count("missing_metadata"), "Review metadata gaps and tag changes."
        ),
        FeaturePage("advanced", "Advanced", "safe", metric_count("safe_folders"), "Advanced guarded operations."),
    ]


def scan_findings(db_path: Path = DEFAULT_DB_PATH, config_path: Path | None = None) -> list[FeatureFinding]:
    metrics = dashboard_metrics(db_path=db_path, config_path=config_path)
    return [
        FeatureFinding("scan", metric.label, metric.value, metric.severity, metric.detail)
        for metric in metrics
        if metric.key
        in {
            "indexed_files",
            "scan_errors",
            "filename_issues",
            "missing_metadata",
            "duplicate_groups",
            "unusual_sample_rates",
        }
    ]


def clean_findings(
    root: str | Path,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    scan_junk: bool = True,
) -> list[FeatureFinding]:
    """Return junk/name cleanup signals without mutating files."""
    findings: list[FeatureFinding] = []
    root_path = Path(root).expanduser()
    if scan_junk and root_path.exists() and str(root) != "PATH":
        from sfxworkbench.clean import find_junk

        junk_files, junk_dirs = find_junk(root_path, quiet=True)
        findings.append(
            FeatureFinding(
                "clean",
                "Junk items",
                len(junk_files) + len(junk_dirs),
                "warning" if junk_files or junk_dirs else "clear",
                f"{len(junk_files):,} files, {len(junk_dirs):,} folders",
            )
        )
    elif not scan_junk:
        findings.append(
            FeatureFinding(
                "clean",
                "Junk items",
                "Preview required",
                "info",
                "Run Preview Junk when you want to scan for removable junk.",
            )
        )
    queues = {queue.key: queue for queue in review_queues(db_path=db_path)}
    for key in ("filename_issues", "long_paths", "unicode_normalization"):
        queue = queues[key]
        findings.append(FeatureFinding("clean", queue.label, queue.count, queue.severity, queue.description))
    return findings


def dedupe_group_rows(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    query: str = "",
    limit: int = 100,
) -> list[DuplicateGroupRow]:
    from sfxworkbench.dedupe import find_duplicates

    groups = find_duplicates(db_path)
    # Tier 3.7: post-hoc filter — ``find_duplicates`` already builds the full
    # group set, so we screen each group against the search terms (all must
    # match somewhere in the hash, keep path, or any member file).
    terms = [term.lower() for term in query.split() if term.strip()]
    rows: list[DuplicateGroupRow] = []
    group_index = 0
    for group in groups:
        group_index += 1
        keep = sorted(group.files)[0] if group.files else ""
        if terms:
            haystack = " ".join([str(keep).lower(), (group.hash or "").lower()] + [str(f).lower() for f in group.files])
            if not all(term in haystack for term in terms):
                continue
        extra = max(0, len(group.files) - 1)
        rows.append(
            DuplicateGroupRow(
                group_id=group_index,
                hash=group.hash,
                copies=len(group.files),
                extra_copies=extra,
                size_bytes=group.size_bytes,
                wasted_bytes=(group.size_bytes or 0) * extra,
                keep_path=keep,
                status="pending" if extra else "clear",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def dedupe_findings(db_path: Path = DEFAULT_DB_PATH) -> list[FeatureFinding]:
    from sfxworkbench.dedupe import find_duplicates, summarize_duplicates

    groups = find_duplicates(db_path)
    summary = summarize_duplicates(groups)
    return [
        FeatureFinding("dedupe", "Duplicate groups", summary.duplicate_groups, "review" if groups else "clear"),
        FeatureFinding("dedupe", "Duplicate files", summary.duplicate_files, "review" if groups else "clear"),
        FeatureFinding("dedupe", "Extra copies", summary.extra_copies, "review" if groups else "clear"),
        FeatureFinding("dedupe", "Wasted bytes", summary.wasted_bytes, "review" if groups else "clear"),
    ]


def organize_findings(db_path: Path = DEFAULT_DB_PATH) -> list[FeatureFinding]:
    queues = {queue.key: queue for queue in review_queues(db_path=db_path)}
    keys = ("filename_issues", "long_paths", "unicode_normalization")
    return [
        FeatureFinding("organize", queues[key].label, queues[key].count, queues[key].severity, queues[key].description)
        for key in keys
    ]


def metadata_workbench_rows(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    plan_path: Path | None = None,
    query: str = "",
    limit: int = 100,
) -> list[MetadataWorkbenchRow]:
    """Return current/pending metadata state for the metadata workbench."""
    pending_by_path: dict[str, dict[str, int | set[str] | list[str] | list[TagDisplayItem]]] = {}
    if plan_path is not None and plan_path.exists():
        try:
            payload = json.loads(plan_path.read_text())
        except json.JSONDecodeError:
            payload = {}
        for entry in payload.get("entries", []):
            path = str(entry.get("path", ""))
            if not path:
                continue
            if str(entry.get("action", "add")).strip() != "add":
                continue
            state = pending_by_path.setdefault(
                path,
                {"pending": 0, "approved": 0, "rejected": 0, "sources": set(), "values": [], "items": []},
            )
            status = str(entry.get("review_status", "pending"))
            if status in {"pending", "approved", "rejected"}:
                state[status] = int(state[status]) + 1
            field = str(entry.get("field", "")).strip()
            proposed = _clean_tag_value(entry.get("proposed_value", ""))
            if field and proposed:
                values = state["values"]
                assert isinstance(values, list)
                source = str(entry.get("source", "")).strip()
                source_suffix = f" [{source}]" if source else ""
                values.append(f"{status.upper()} {_tag_label(field)}: {proposed}{source_suffix}")
                items = state["items"]
                assert isinstance(items, list)
                items.append(
                    TagDisplayItem(
                        source="plan",
                        field=field,
                        value=proposed,
                        status=status,
                        evidence_source=source,
                    )
                )
            source = str(entry.get("source", "")).strip()
            if source:
                cast_sources = state["sources"]
                assert isinstance(cast_sources, set)
                cast_sources.add(source)

    like_sql, params = _like_filter_clause(("f.filename", "f.path"), query)
    conn = get_connection(db_path)
    try:
        # Inlining one ``?`` per pending path overflowed SQLite's variable
        # limit (~32k) on real libraries — the user hit 107k pending entries.
        # Bulk-load the pending set into a temp table so the ORDER BY clause
        # can ``IN (SELECT path FROM _pending_paths)`` without binding any
        # placeholders for the path list itself.
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _pending_paths (path TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM _pending_paths")
        if pending_by_path:
            conn.executemany(
                "INSERT OR IGNORE INTO _pending_paths (path) VALUES (?)",
                ((path,) for path in pending_by_path),
            )
        rows = conn.execute(
            f"""
            WITH embedded AS (
                SELECT file_id,
                       COUNT(*) AS embedded_fields,
                       GROUP_CONCAT(
                           CASE
                               WHEN lower(key) = 'description' THEN 'Description'
                               WHEN key = 'ICMT' OR lower(key) = 'comment' THEN 'Comment'
                               WHEN key = 'IKEY' OR lower(key) = 'keywords' THEN 'Keywords'
                               WHEN key = 'INAM' OR lower(key) = 'title' THEN 'Title'
                               WHEN key = 'IGNR' OR lower(key) = 'category' THEN 'Category'
                               WHEN key = 'ISBJ' THEN 'Subject'
                               WHEN lower(key) = 'subcategory' THEN 'Subcategory'
                               ELSE key
                           END || ': ' ||
                           SUBSTR(REPLACE(REPLACE(value, char(10), ' '), char(13), ' '), 1, 80),
                           ' | '
                       ) AS embedded_summary
                FROM (
                    SELECT mf.file_id, mf.namespace, mf.key, mf.value
                    FROM metadata_fields mf
                    WHERE mf.value IS NOT NULL AND TRIM(mf.value) != ''
                      AND (
                          lower(mf.key) IN ('description', 'comment', 'keywords', 'title', 'category', 'subcategory')
                          OR mf.key IN ('ICMT', 'IKEY', 'INAM', 'IGNR', 'ISBJ')
                      )
                    ORDER BY
                        CASE
                            WHEN lower(mf.key) = 'description' THEN 0
                            WHEN mf.key IN ('IKEY', 'ICMT') THEN 1
                            WHEN mf.key IN ('INAM', 'ISBJ', 'IGNR') THEN 2
                            WHEN lower(mf.key) IN ('title', 'comment', 'keywords', 'category', 'subcategory') THEN 3
                            WHEN lower(mf.key) = 'originator' THEN 8
                            WHEN lower(mf.key) = 'originatorreference' THEN 9
                            ELSE 10
                        END,
                        mf.namespace,
                        mf.key
                )
                GROUP BY file_id
            ),
            accepted AS (
                SELECT file_id,
                       COUNT(*) AS accepted_tags,
                       GROUP_CONCAT(
                           CASE lower(field)
                               WHEN 'description' THEN 'Description'
                               WHEN 'keywords' THEN 'Keywords'
                               WHEN 'category' THEN 'Category'
                               WHEN 'subcategory' THEN 'Subcategory'
                               WHEN 'ucs_category' THEN 'UCS Category'
                               WHEN 'ucs_subcategory' THEN 'UCS Subcategory'
                               WHEN 'title' THEN 'Title'
                               WHEN 'comment' THEN 'Comment'
                               ELSE field
                           END || ': ' || SUBSTR(REPLACE(REPLACE(value, char(10), ' '), char(13), ' '), 1, 80),
                           ' | '
                       ) AS accepted_summary
                FROM (
                    SELECT file_id, field, value
                    FROM accepted_tags
                    WHERE value IS NOT NULL AND TRIM(value) != ''
                    ORDER BY
                        CASE lower(field)
                            WHEN 'description' THEN 0
                            WHEN 'keywords' THEN 1
                            WHEN 'category' THEN 2
                            WHEN 'subcategory' THEN 3
                            WHEN 'ucs_category' THEN 4
                            WHEN 'ucs_subcategory' THEN 5
                            WHEN 'title' THEN 6
                            WHEN 'comment' THEN 7
                            ELSE 20
                        END,
                        field,
                        value
                )
                GROUP BY file_id
            )
            SELECT f.id, f.path, f.filename,
                   (SELECT COUNT(*) FROM metadata_fields mf WHERE mf.file_id = f.id) AS embedded_fields,
                   COALESCE(e.embedded_summary, '') AS embedded_summary,
                   (SELECT COUNT(*) FROM accepted_tags t WHERE t.file_id = f.id) AS accepted_tags,
                   COALESCE(a.accepted_summary, '') AS accepted_summary
            FROM files f
            LEFT JOIN embedded e ON e.file_id = f.id
            LEFT JOIN accepted a ON a.file_id = f.id
            WHERE 1 = 1 {like_sql}
            ORDER BY
                CASE
                    WHEN f.path IN (SELECT path FROM _pending_paths) THEN 0
                    WHEN COALESCE(a.accepted_tags, 0) > 0 THEN 1
                    WHEN COALESCE(e.embedded_fields, 0) > 0 THEN 2
                    ELSE 3
                END,
                f.path
            LIMIT ?
            """,
            params + (limit,),
        ).fetchall()
        file_ids = tuple(int(row["id"]) for row in rows)
        embedded_items_by_id: dict[int, list[TagDisplayItem]] = {file_id: [] for file_id in file_ids}
        accepted_items_by_id: dict[int, list[TagDisplayItem]] = {file_id: [] for file_id in file_ids}
        if file_ids:
            placeholders = ",".join("?" for _ in file_ids)
            for item in conn.execute(
                f"""
                SELECT file_id, namespace, key, value
                FROM metadata_fields
                WHERE file_id IN ({placeholders})
                  AND value IS NOT NULL AND TRIM(value) != ''
                  AND (
                      lower(key) IN ('description', 'comment', 'keywords', 'title', 'category', 'subcategory')
                      OR key IN ('ICMT', 'IKEY', 'INAM', 'IGNR', 'ISBJ')
                  )
                ORDER BY
                    CASE
                        WHEN lower(key) = 'description' THEN 0
                        WHEN key IN ('IKEY', 'ICMT') THEN 1
                        WHEN key IN ('INAM', 'ISBJ', 'IGNR') THEN 2
                        WHEN lower(key) IN ('title', 'comment', 'keywords', 'category', 'subcategory') THEN 3
                        ELSE 10
                    END,
                    namespace,
                    key
                """,
                file_ids,
            ):
                embedded_items_by_id.setdefault(int(item["file_id"]), []).append(
                    TagDisplayItem(
                        source="file",
                        field=str(item["key"]),
                        value=_clean_tag_value(item["value"]),
                    )
                )
            for item in conn.execute(
                f"""
                SELECT file_id, field, value, source
                FROM accepted_tags
                WHERE file_id IN ({placeholders})
                  AND value IS NOT NULL AND TRIM(value) != ''
                ORDER BY
                    CASE lower(field)
                        WHEN 'description' THEN 0
                        WHEN 'keywords' THEN 1
                        WHEN 'category' THEN 2
                        WHEN 'subcategory' THEN 3
                        WHEN 'ucs_category' THEN 4
                        WHEN 'ucs_subcategory' THEN 5
                        WHEN 'title' THEN 6
                        WHEN 'comment' THEN 7
                        ELSE 20
                    END,
                    field,
                    value
                """,
                file_ids,
            ):
                accepted_items_by_id.setdefault(int(item["file_id"]), []).append(
                    TagDisplayItem(
                        source="db",
                        field=str(item["field"]),
                        value=_clean_tag_value(item["value"]),
                        evidence_source=str(item["source"] or ""),
                    )
                )
    finally:
        conn.close()

    results: list[MetadataWorkbenchRow] = []
    for row in rows:
        pending = pending_by_path.get(
            row["path"], {"pending": 0, "approved": 0, "rejected": 0, "sources": set(), "values": [], "items": []}
        )
        pending_items = pending["items"]
        assert isinstance(pending_items, list)
        file_id = int(row["id"])
        embedded_items = tuple(embedded_items_by_id.get(file_id, []))
        accepted_items = tuple(accepted_items_by_id.get(file_id, []))
        existing_items = (*embedded_items, *accepted_items)
        visible_pending_items = tuple(
            item for item in pending_items if not _is_duplicate_tag_item(item, existing_items)
        )
        pending_count = sum(1 for item in visible_pending_items if item.status == "pending")
        approved_count = sum(1 for item in visible_pending_items if item.status == "approved")
        rejected_count = sum(1 for item in visible_pending_items if item.status == "rejected")
        status = "pending" if pending_count or approved_count else ("accepted" if row["accepted_tags"] else "info")
        embedded_summary = str(row["embedded_summary"] or "")
        accepted_summary = str(row["accepted_summary"] or "")
        pending_summary = " | ".join(_pending_value_summary(item) for item in visible_pending_items[:4])
        tag_items = tuple(
            item
            for item in (
                *embedded_items[:4],
                *visible_pending_items[:8],
                *accepted_items[:4],
            )
            if item.value
        )
        results.append(
            MetadataWorkbenchRow(
                path=row["path"],
                filename=row["filename"],
                embedded_fields=int(row["embedded_fields"]),
                accepted_tags=int(row["accepted_tags"]),
                pending_changes=pending_count,
                approved_changes=approved_count,
                rejected_changes=rejected_count,
                embedded_summary=embedded_summary,
                accepted_summary=accepted_summary,
                pending_summary=pending_summary,
                tags_summary=_combined_tags_summary(tag_items),
                tag_items=tag_items,
                sources=", ".join(
                    sorted(item.evidence_source for item in visible_pending_items if item.evidence_source)
                ),
                status=status,
            )
        )
    return results


def metadata_findings(db_path: Path = DEFAULT_DB_PATH, *, plan_path: Path | None = None) -> list[FeatureFinding]:
    queues = {queue.key: queue for queue in review_queues(db_path=db_path)}
    rows = metadata_workbench_rows(db_path, plan_path=plan_path, limit=500)
    pending = sum(row.pending_changes for row in rows)
    approved = sum(row.approved_changes for row in rows)
    return [
        FeatureFinding("metadata", queues["missing_metadata"].label, queues["missing_metadata"].count, "review"),
        FeatureFinding("metadata", queues["missing_bext"].label, queues["missing_bext"].count, "review"),
        FeatureFinding("metadata", "Pending tag changes", pending, "pending" if pending else "clear"),
        FeatureFinding("metadata", "Approved tag changes", approved, "accepted" if approved else "clear"),
        FeatureFinding("metadata", queues["db_only_tags"].label, queues["db_only_tags"].count, "accepted"),
    ]


def metadata_tag_change_rows(
    plan_path: Path,
    *,
    db_path: Path | None = None,
    query: str = "",
    limit: int = 500,
) -> list[TagChangeRow]:
    """Return planned DB tag changes from the active metadata plan."""
    if not plan_path.exists():
        return []
    try:
        payload = json.loads(plan_path.read_text())
    except json.JSONDecodeError:
        return []

    entries = list(payload.get("entries", []))
    existing_by_path: dict[str, tuple[TagDisplayItem, ...]] = {}
    if db_path is not None:
        paths = tuple(sorted({str(entry.get("path", "")).strip() for entry in entries if entry.get("path")}))
        if paths:
            conn = get_connection(db_path)
            try:
                placeholders = ",".join("?" for _ in paths)
                file_rows = conn.execute(
                    f"""
                    SELECT id, path
                    FROM files
                    WHERE path IN ({placeholders})
                    """,
                    paths,
                ).fetchall()
                path_by_id = {int(row["id"]): str(row["path"]) for row in file_rows}
                existing_lists: dict[str, list[TagDisplayItem]] = {path: [] for path in path_by_id.values()}
                file_ids = tuple(path_by_id)
                if file_ids:
                    file_placeholders = ",".join("?" for _ in file_ids)
                    for item in conn.execute(
                        f"""
                        SELECT file_id, namespace, key, value
                        FROM metadata_fields
                        WHERE file_id IN ({file_placeholders})
                          AND value IS NOT NULL AND TRIM(value) != ''
                          AND (
                              lower(key) IN ('description', 'comment', 'keywords', 'title', 'category', 'subcategory')
                              OR key IN ('ICMT', 'IKEY', 'INAM', 'IGNR', 'ISBJ')
                          )
                        """,
                        file_ids,
                    ):
                        existing_lists.setdefault(path_by_id[int(item["file_id"])], []).append(
                            TagDisplayItem(
                                source="file",
                                field=str(item["key"]),
                                value=_clean_tag_value(item["value"]),
                            )
                        )
                    for item in conn.execute(
                        f"""
                        SELECT file_id, field, value, source
                        FROM accepted_tags
                        WHERE file_id IN ({file_placeholders})
                          AND value IS NOT NULL AND TRIM(value) != ''
                        """,
                        file_ids,
                    ):
                        existing_lists.setdefault(path_by_id[int(item["file_id"])], []).append(
                            TagDisplayItem(
                                source="db",
                                field=str(item["field"]),
                                value=_clean_tag_value(item["value"]),
                                evidence_source=str(item["source"] or ""),
                            )
                        )
                existing_by_path = {path: tuple(items) for path, items in existing_lists.items()}
            finally:
                conn.close()

    needle = query.casefold().strip()
    rows: list[TagChangeRow] = []
    for entry in entries:
        if str(entry.get("action", "add")).strip() != "add":
            continue
        path = str(entry.get("path", "")).strip()
        filename = str(entry.get("filename", "")).strip() or (Path(path).name if path else "")
        field = str(entry.get("field", "")).strip()
        value = _clean_tag_value(entry.get("proposed_value", ""))
        status = str(entry.get("review_status", "pending")).strip() or "pending"
        source = str(entry.get("source", "")).strip()
        if not field or not value:
            continue
        if _is_duplicate_tag_item(
            TagDisplayItem(source="plan", field=field, value=value, status=status, evidence_source=source),
            existing_by_path.get(path, ()),
        ):
            continue
        haystack = " ".join((filename, path, field, value, status, source)).casefold()
        if needle and needle not in haystack:
            continue
        rows.append(
            TagChangeRow(
                filename=filename,
                path=path,
                status=status,
                field=field,
                value=value,
                source=source,
            )
        )
    rows.sort(
        key=lambda row: (row.status != "pending", row.status, row.filename, _tag_field_rank(row.field), row.value)
    )
    return rows[:limit]


def similarity_findings(db_path: Path = DEFAULT_DB_PATH) -> list[FeatureFinding]:
    conn = get_connection(db_path)
    try:
        descriptors = _count(conn, "SELECT COUNT(*) FROM audio_descriptors")
        segments = _count(conn, "SELECT COUNT(*) FROM audio_segments")
        feedback = _count(conn, "SELECT COUNT(*) FROM similarity_feedback")
    finally:
        conn.close()
    return [
        FeatureFinding("similarity", "Cached descriptors", descriptors, "info"),
        FeatureFinding("similarity", "Event segments", segments, "info"),
        FeatureFinding("similarity", "Review decisions", feedback, "accepted" if feedback else "clear"),
    ]


def advanced_findings(db_path: Path = DEFAULT_DB_PATH, config_path: Path | None = None) -> list[FeatureFinding]:
    rules = build_preservation_rules(config_path=config_path)
    return [
        FeatureFinding("advanced", "Index file", str(db_path), "info", "Advanced cache used by scans and plans."),
        FeatureFinding("advanced", "Protected folders", len(rules.safe_folders), "safe"),
        FeatureFinding(
            "advanced", "Permanent delete", "Advanced only", "warning", "Requires reviewed quarantine logs."
        ),
        FeatureFinding("advanced", "Embedded metadata writes", "Advanced only", "warning", "Requires reviewed plans."),
    ]


def workflow_capabilities(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    library_path: str | Path | None = None,
) -> list[WorkflowCapability]:
    """Return implemented CLI workflows and how the TUI currently surfaces them."""
    queues = {queue.key: queue for queue in review_queues(db_path=db_path, library_path=library_path)}
    db = _db_arg(db_path)
    root = _command_root(db_path, library_path)
    quoted_root = _quote_path(root)

    def queue_signal(key: str, empty: str = "0 indexed") -> str:
        queue = queues.get(key)
        if queue is None:
            return empty
        return f"{queue.count:,} {queue.label.lower()}"

    return [
        WorkflowCapability(
            "Import",
            "Standalone audit",
            "CLI only",
            "No index required",
            f"python3 audit.py {quoted_root} --output-dir ~/reports",
            "CLI / Reports",
            "Run the zero-dependency Phase 0 filesystem audit before or outside SQLite indexing.",
        ),
        WorkflowCapability(
            "Import",
            "Scan library",
            "Guided",
            "Indexed DB",
            f"uv run sfx scan {quoted_root} {db}",
            "Start / Files",
            "Build or refresh the SQLite index that powers every review surface.",
        ),
        WorkflowCapability(
            "Import",
            "Scan-error cleanup",
            "Guided",
            queue_signal("scan_errors"),
            queues["scan_errors"].next_action,
            "Review",
            "Plan review-first quarantine for unreadable indexed files.",
        ),
        WorkflowCapability(
            "Cleanup",
            "Junk cleanup",
            "CLI only",
            "Not indexed",
            f"uv run sfx clean {quoted_root}",
            "CLI",
            "Preview or remove AppleDouble, .DS_Store, REAPER peaks, and other known junk.",
        ),
        WorkflowCapability(
            "Cleanup",
            "Exact duplicates",
            "Guided",
            queue_signal("duplicates"),
            queues["duplicates"].next_action,
            "Review",
            "Review exact MD5 duplicate groups before quarantine.",
        ),
        WorkflowCapability(
            "Cleanup",
            "Rename cleanup",
            "Reports",
            queue_signal("filename_issues"),
            f"uv run sfx rename {quoted_root} --pattern portable --json",
            "Review / Reports",
            "Preview/apply/undo UCS, safe, and portable filename/path cleanup.",
        ),
        WorkflowCapability(
            "Cleanup",
            "Folder organization",
            "Reports",
            "JSON reports/plans/logs",
            f"uv run sfx organize audit {quoted_root} --output ~/reports/organize_report.json",
            "Reports",
            "Review/apply/undo top-level, vendor/product, numeric-series, common-prefix, and nesting cleanup.",
        ),
        WorkflowCapability(
            "Cleanup",
            "Pack overlap",
            "Reports",
            "JSON reports/plans/logs",
            f"uv run sfx packs audit {quoted_root} {db} --output ~/reports/pack_overlap_report.json",
            "Reports",
            "Detect duplicate folders and fully-covered pack overlaps before quarantine planning.",
        ),
        WorkflowCapability(
            "Metadata",
            "Metadata audit",
            "Guided",
            queue_signal("missing_metadata"),
            queues["missing_metadata"].next_action,
            "Review / Reports",
            "Find files missing embedded BEXT/iXML and unusual sample rates.",
        ),
        WorkflowCapability(
            "Metadata",
            "Metadata view",
            "Guided",
            "Per selected file",
            f"uv run sfx metadata view QUERY {db}",
            "Files",
            "Inspect indexed facts, embedded fields, UCS provenance, and accepted DB-only tags.",
        ),
        WorkflowCapability(
            "Metadata",
            "Metadata backends",
            "CLI only",
            "Backend discovery",
            "uv run sfx metadata backends --json",
            "CLI",
            "Report available embedded metadata writer backends without mutating audio.",
        ),
        WorkflowCapability(
            "Metadata",
            "Embedded metadata write",
            "Reports",
            "JSON plans/readback/logs",
            f"uv run sfx metadata write-plan ~/reports/metadata_write_plan.json {db} --path {quoted_root}",
            "Reports",
            "Plan, review, fixture-test, apply, and undo reviewed embedded metadata writes.",
        ),
        WorkflowCapability(
            "Tagging",
            "Tag suggestions",
            "Reports",
            "JSON reports/plans/logs",
            f"uv run sfx tag suggest {quoted_root} {db} --output ~/reports/tag_suggestions.json",
            "Reports",
            "Generate report-only tag suggestions from filename, path, group, UCS, and synonym evidence.",
        ),
        WorkflowCapability(
            "Tagging",
            "Tag proposals",
            "Reports",
            "JSON reports",
            f"uv run sfx tag propose {quoted_root} {db} --output ~/reports/tag_proposals.json",
            "Reports",
            "Classify evidence-fusion UCS proposals as strong/review/weak/blocked.",
        ),
        WorkflowCapability(
            "Tagging",
            "Tag review/apply",
            "Guided",
            queue_signal("db_only_tags"),
            queues["db_only_tags"].next_action,
            "Review / Reports",
            "Review DB-only tag plans, apply accepted tags, and export/import portable sidecars.",
        ),
        WorkflowCapability(
            "UCS",
            "Catalog import/info",
            "CLI only",
            "Catalog cache",
            "uv run sfx ucs info",
            "CLI",
            "Import and inspect official UCS category data cached outside the package.",
        ),
        WorkflowCapability(
            "UCS",
            "UCS validation",
            "Guided",
            queue_signal("ucs_named"),
            queues["ucs_named"].next_action,
            "Review / Reports",
            "Validate UCS-looking filenames against the loaded catalog.",
        ),
        WorkflowCapability(
            "Similarity",
            "Similarity crawl/search/audit",
            "Reports",
            "Segments and reports",
            f"uv run sfx similarity crawl {quoted_root} {db} --cache ~/.sfxworkbench/similarity",
            "Reports",
            "Cache deterministic audio descriptors, search by query file, and audit near-duplicates.",
        ),
        WorkflowCapability(
            "Similarity",
            "Similarity feedback",
            "Guided",
            queue_signal("similarity_feedback"),
            queues["similarity_feedback"].next_action,
            "Review",
            "List accepted, rejected, ignored, hidden, or favorite similarity relationships.",
        ),
        WorkflowCapability(
            "Advanced",
            "Compare import",
            "Reports",
            "JSON report/plan",
            f"uv run sfx compare audit CANDIDATE --against-db {db_path}",
            "Reports",
            "Compare a candidate import against the existing index before merging libraries.",
        ),
        WorkflowCapability(
            "Advanced",
            "Processed variants",
            "Reports",
            "JSON report",
            f"uv run sfx processed {quoted_root} {db} --output ~/reports/processed_report.json",
            "Reports",
            "Report likely processed/rendered variants without changing files.",
        ),
        WorkflowCapability(
            "Advanced",
            "Reviewed permanent delete",
            "Reports",
            "JSON plan/log",
            "uv run sfx delete plan ~/reports/quarantine_log.json --output ~/reports/delete_plan.json",
            "Reports",
            "Permanently delete only reviewed paths already present in quarantine logs.",
        ),
        WorkflowCapability(
            "Advanced",
            "Dual-mono conversion",
            "Reports",
            "JSON report/plan/log",
            f"uv run sfx audio dual-mono audit {quoted_root} {db} --output ~/reports/dual_mono_report.json",
            "Reports",
            "Detect dual-mono stereo files and copy-convert reviewed outputs.",
        ),
        WorkflowCapability(
            "Reports",
            "Groups/format reports",
            "Reports",
            "JSON reports",
            f"uv run sfx groups audit {quoted_root} {db} --output ~/reports/related_groups_report.json",
            "Reports",
            "Inspect related sound groups and mixed format consistency inside groups.",
        ),
        WorkflowCapability(
            "Reports",
            "Search/export/audit",
            "CLI only",
            "Read-only CLI",
            f"uv run sfx audit {db}",
            "CLI",
            "Run quick DB audit, FTS search, and CSV export from the command line.",
        ),
    ]


def review_queues(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    library_path: str | Path | None = None,
) -> list[QueueSummary]:
    """Return queue counts that map CLI reports into app review lanes."""
    conn = get_connection(db_path)
    try:
        scan_errors = _count(conn, "SELECT COUNT(*) FROM files WHERE scan_error IS NOT NULL")
        filename_issues = _count(conn, "SELECT COUNT(*) FROM fn_issues")
        long_paths = _count(conn, "SELECT COUNT(*) FROM fn_issues WHERE issue = 'path_too_long'")
        unicode_issues = _count(conn, "SELECT COUNT(*) FROM fn_issues WHERE issue = 'unicode_normalization'")
        missing_bext = _count(conn, "SELECT COUNT(*) FROM files WHERE has_bext = 0")
        missing_ixml = _count(conn, "SELECT COUNT(*) FROM files WHERE has_ixml = 0")
        missing_metadata = _count(conn, "SELECT COUNT(*) FROM files WHERE has_bext = 0 AND has_ixml = 0")
        unusual_rates = _count(
            conn,
            f"""
            SELECT COUNT(*) FROM files
            WHERE sample_rate IS NOT NULL
              AND sample_rate NOT IN ({",".join("?" for _ in _STANDARD_SAMPLE_RATES)})
            """,
            tuple(sorted(_STANDARD_SAMPLE_RATES)),
        )
        duplicate_groups = _duplicate_group_count(conn)
        db_only_tags = _count(conn, "SELECT COUNT(*) FROM accepted_tags")
        ucs_named = _count(conn, "SELECT COUNT(*) FROM files WHERE is_ucs = 1")
        similarity_feedback = _count(conn, "SELECT COUNT(*) FROM similarity_feedback")
    finally:
        conn.close()

    db = _db_arg(db_path)
    quoted_root = _quote_path(_command_root(db_path, library_path))
    return [
        QueueSummary(
            "scan_errors",
            "Health",
            "Scan errors",
            scan_errors,
            "Indexed files that could not be read.",
            f"Plan obvious quarantines: uv run sfx scan-errors {db} --output ~/reports/scan_error_plan.json",
            "error",
        ),
        QueueSummary(
            "filename_issues",
            "Health",
            "Unsafe filenames",
            filename_issues,
            "Illegal characters, risky characters, path length, or normalization issues.",
            f"Preview portable cleanup: uv run sfx rename {quoted_root} --pattern portable",
            "warning",
        ),
        QueueSummary(
            "long_paths",
            "Cleanup",
            "Long paths",
            long_paths,
            "Paths that may break tools or filesystems.",
            f"Preview portable cleanup: uv run sfx rename {quoted_root} --pattern portable",
            "warning",
        ),
        QueueSummary(
            "unicode_normalization",
            "Cleanup",
            "Unicode normalization",
            unicode_issues,
            "Names that should be normalized for cross-platform safety.",
            f"Preview portable cleanup: uv run sfx rename {quoted_root} --pattern portable",
            "warning",
        ),
        QueueSummary(
            "duplicates",
            "Cleanup",
            "Exact duplicate groups",
            duplicate_groups,
            "MD5 duplicate groups ready for review.",
            f"Write review plan: uv run sfx dedupe {db} --output ~/reports/dedupe_plan.json",
        ),
        QueueSummary(
            "missing_metadata",
            "Metadata",
            "Missing BEXT/iXML",
            missing_metadata,
            "Files with neither BEXT nor iXML.",
            f"Write metadata gap report: uv run sfx metadata audit {db} --output ~/reports/metadata_report.json",
        ),
        QueueSummary(
            "missing_bext",
            "Metadata",
            "Missing BEXT",
            missing_bext,
            "Files without BWF/BEXT metadata.",
            f"Write metadata gap report: uv run sfx metadata audit {db} --output ~/reports/metadata_report.json",
        ),
        QueueSummary(
            "missing_ixml",
            "Metadata",
            "Missing iXML",
            missing_ixml,
            "Files without iXML metadata.",
            f"Write metadata gap report: uv run sfx metadata audit {db} --output ~/reports/metadata_report.json",
        ),
        QueueSummary(
            "unusual_rates",
            "Metadata",
            "Unusual sample rates",
            unusual_rates,
            "Files outside common SFX rates.",
            f"Write format report: uv run sfx format audit {quoted_root} {db} --output ~/reports/format_report.json",
        ),
        QueueSummary(
            "ucs_named",
            "Naming",
            "UCS-looking filenames",
            ucs_named,
            "Filename provenance to validate against catalog.",
            f"Validate against catalog: uv run sfx ucs validate {quoted_root} {db} --json",
        ),
        QueueSummary(
            "db_only_tags",
            "Decisions",
            "DB-only accepted tags",
            db_only_tags,
            "Accepted tags not necessarily embedded.",
            f"Export accepted tags: uv run sfx tag sidecar-export ~/reports/accepted_tags.sidecar.json {db} --path {quoted_root}",
        ),
        QueueSummary(
            "similarity_feedback",
            "Decisions",
            "Similarity decisions",
            similarity_feedback,
            "Accepted, rejected, ignored, hidden, or favorite similarity relationships.",
            f"Review decisions: uv run sfx similarity feedback list {db} --json",
        ),
    ]


_REVIEW_PRESETS: dict[str, tuple[ReviewPreset, ...]] = {
    "scan_errors": (
        ReviewPreset("scan_errors", "All scan errors", "", "Show every unreadable indexed file."),
        ReviewPreset("scan_errors", "RIFF/WAV errors", "wav riff", "Focus likely WAV container read failures."),
        ReviewPreset("scan_errors", "AppleDouble artifacts", "._", "Find macOS metadata blobs that reached the index."),
    ),
    "filename_issues": (
        ReviewPreset("filename_issues", "All unsafe names", "", "Show every filename issue."),
        ReviewPreset(
            "filename_issues", "Illegal characters", "illegal_chars", "Names with characters that break tools."
        ),
        ReviewPreset("filename_issues", "Normalization", "unicode_normalization", "Unicode normalization conflicts."),
        ReviewPreset("filename_issues", "Long paths", "path_too_long", "Paths over the portability guardrail."),
    ),
    "long_paths": (
        ReviewPreset("long_paths", "All long paths", "", "Show every path-length issue."),
        ReviewPreset("long_paths", "WAV long paths", "wav", "Start with production WAV assets."),
    ),
    "unicode_normalization": (
        ReviewPreset("unicode_normalization", "All normalization", "", "Show every Unicode normalization issue."),
        ReviewPreset("unicode_normalization", "Composed marks", "unicode", "Review Unicode-specific path details."),
    ),
    "duplicates": (
        ReviewPreset("duplicates", "All duplicates", "", "Show every file in exact MD5 duplicate groups."),
        ReviewPreset("duplicates", "WAV duplicates", "wav", "Prioritize production WAV duplicates."),
        ReviewPreset("duplicates", "AIF/AIFF duplicates", "aif", "Check alternate production audio containers."),
        ReviewPreset("duplicates", "MP3 duplicates", "mp3", "Review compressed preview or reference duplicates."),
    ),
    "missing_metadata": (
        ReviewPreset("missing_metadata", "All gaps", "", "Show files with neither BEXT nor iXML."),
        ReviewPreset("missing_metadata", "WAV first", "wav", "Focus BWF-capable files first."),
        ReviewPreset("missing_metadata", "48k WAV", "wav 48000", "Common production delivery format."),
        ReviewPreset("missing_metadata", "96k WAV", "wav 96000", "High-resolution production libraries."),
    ),
    "missing_bext": (
        ReviewPreset("missing_bext", "All BEXT gaps", "", "Show files without BEXT metadata."),
        ReviewPreset("missing_bext", "WAV first", "wav", "Focus files that can carry BWF descriptions."),
        ReviewPreset("missing_bext", "Multichannel", "6", "Surface likely surround or ambisonic files."),
    ),
    "missing_ixml": (
        ReviewPreset("missing_ixml", "All iXML gaps", "", "Show files without iXML metadata."),
        ReviewPreset("missing_ixml", "WAV first", "wav", "Focus files most likely to benefit from iXML later."),
    ),
    "unusual_rates": (
        ReviewPreset("unusual_rates", "All unusual rates", "", "Show every non-standard sample rate."),
        ReviewPreset("unusual_rates", "22.05k", "22050", "Find low-rate legacy or preview assets."),
        ReviewPreset("unusual_rates", "32k", "32000", "Find broadcast/legacy rate assets."),
        ReviewPreset("unusual_rates", "192k", "192000", "Find very high-rate assets."),
    ),
    "ucs_named": (
        ReviewPreset("ucs_named", "All UCS-looking", "", "Show every filename that matches the UCS-shaped heuristic."),
        ReviewPreset("ucs_named", "Ambience", "AMB_", "Review ambience-like UCS prefixes."),
        ReviewPreset("ucs_named", "Foley", "FOL_", "Review foley-like UCS prefixes."),
        ReviewPreset("ucs_named", "UI", "UI_", "Review interface sound prefixes."),
    ),
    "db_only_tags": (
        ReviewPreset("db_only_tags", "All accepted tags", "", "Show every file with accepted DB-only tags."),
        ReviewPreset("db_only_tags", "UCS provenance", "ucs_", "Check catalog-derived provenance decisions."),
        ReviewPreset("db_only_tags", "Descriptions", "description", "Review accepted description values."),
        ReviewPreset("db_only_tags", "Originator", "originator", "Review source/creator metadata decisions."),
    ),
    "similarity_feedback": (
        ReviewPreset("similarity_feedback", "All decisions", "", "Show every similarity feedback row."),
        ReviewPreset("similarity_feedback", "Ignored", "ignored", "Review intentionally hidden matches."),
        ReviewPreset("similarity_feedback", "Accepted", "accepted", "Review confirmed similarity relationships."),
        ReviewPreset("similarity_feedback", "Segment scope", "segment", "Review event-window decisions."),
    ),
}


def review_presets(queue_key: str | None = None) -> list[ReviewPreset]:
    """Return built-in saved views for read-only queue triage."""
    if queue_key is not None:
        return list(_REVIEW_PRESETS.get(queue_key, (ReviewPreset(queue_key, "All items", "", "Show every row."),)))
    presets: list[ReviewPreset] = []
    for queue_presets in _REVIEW_PRESETS.values():
        presets.extend(queue_presets)
    return presets


def report_presets() -> list[ReportPreset]:
    """Return built-in saved views for generated JSON evidence."""
    return [
        ReportPreset("Everything", "", "", "Show every discovered JSON report, plan, and log."),
        ReportPreset("Reports", "Report", "", "Show read-only audit and diagnostic reports."),
        ReportPreset("Plans", "Plan", "", "Show reviewed or reviewable change plans."),
        ReportPreset("Logs", "Log", "", "Show apply/undo logs and after-action records."),
        ReportPreset("Protected", "", "safe_folder", "Find evidence that touched safe-folder guardrails."),
        ReportPreset("Conflicts", "", "conflict", "Find reports or plans with conflict markers."),
        ReportPreset("Metadata", "", "metadata", "Focus metadata audit, tagging, and write evidence."),
        ReportPreset("Dedupe", "", "dedupe", "Focus exact-duplicate cleanup evidence."),
    ]


def start_steps(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    library_path: str | Path | None = None,
) -> list[StartStep]:
    """Return a first-run work order ranked by expected user payoff."""
    queues = {queue.key: queue for queue in review_queues(db_path=db_path, library_path=library_path)}

    def queue_count(key: str) -> int:
        queue = queues.get(key)
        return queue.count if queue else 0

    health_count = queue_count("scan_errors") + queue_count("filename_issues")
    steps: list[StartStep] = [
        StartStep(
            1,
            "Fix import health",
            "highest",
            "needs review" if health_count else "clear",
            f"{queue_count('scan_errors'):,} scan errors / {queue_count('filename_issues'):,} unsafe names",
            "Broken reads and unsafe paths can spoil every later batch change.",
            queues["scan_errors"].next_action if queue_count("scan_errors") else queues["filename_issues"].next_action,
            "Review",
            "scan_errors" if queue_count("scan_errors") else "filename_issues",
        ),
        StartStep(
            2,
            "Remove exact duplicates",
            "highest",
            "needs review" if queue_count("duplicates") else "clear",
            f"{queue_count('duplicates'):,} duplicate groups",
            "This quickly reduces clutter, storage, and repeated decisions.",
            queues["duplicates"].next_action,
            "Review",
            "duplicates",
        ),
        StartStep(
            3,
            "Fill metadata gaps",
            "high",
            "ready" if queue_count("missing_metadata") else "clear",
            f"{queue_count('missing_metadata'):,} missing BEXT+iXML",
            "Better descriptions and embedded fields improve search in other audio tools.",
            queues["missing_metadata"].next_action,
            "Review",
            "missing_metadata",
        ),
        StartStep(
            4,
            "Validate naming provenance",
            "medium",
            "ready" if queue_count("ucs_named") else "clear",
            f"{queue_count('ucs_named'):,} UCS-looking names",
            "UCS-looking names are useful evidence, but they should not be trusted blindly.",
            queues["ucs_named"].next_action,
            "Review",
            "ucs_named",
        ),
        StartStep(
            5,
            "Inspect accepted tags",
            "medium",
            "ready" if queue_count("db_only_tags") else "not started",
            f"{queue_count('db_only_tags'):,} accepted DB-only tags",
            "Accepted tags are decisions worth checking before export or embedding.",
            queues["db_only_tags"].next_action,
            "Review",
            "db_only_tags",
        ),
        StartStep(
            6,
            "Browse reports and logs",
            "supporting",
            "available",
            "Reports, plans, logs",
            "Use generated evidence to understand what changed and what is still pending.",
            "Pass report paths with: uv run sfx tui --db "
            + _quote_path(_display_path(db_path))
            + " --report ~/reports",
            "Reports",
            "",
        ),
    ]
    return steps


def list_files(db_path: Path = DEFAULT_DB_PATH, *, query: str = "", limit: int = 100) -> list[FileRow]:
    """List files for the alpha file browser.

    FTS is used when a query is provided; otherwise this returns a stable path
    ordering from the index.
    """
    conn = get_connection(db_path)
    try:
        if query.strip():
            try:
                rows = conn.execute(
                    """
                    SELECT f.path, f.filename, f.extension, f.size_bytes, f.sample_rate,
                           f.bit_depth, f.channels, f.duration_s, f.is_ucs, f.has_bext,
                           f.has_ixml, f.scan_error,
                           (SELECT COUNT(*) FROM accepted_tags t WHERE t.file_id = f.id) AS accepted_tag_count,
                           (SELECT COUNT(*) FROM metadata_fields mf WHERE mf.file_id = f.id) AS metadata_field_count,
                           (SELECT COUNT(*) FROM fn_issues i WHERE i.file_id = f.id) AS issue_count
                    FROM files_fts fts
                    JOIN files f ON f.id = fts.rowid
                    WHERE files_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                like = f"%{query.strip()}%"
                rows = conn.execute(
                    """
                    SELECT f.path, f.filename, f.extension, f.size_bytes, f.sample_rate,
                           f.bit_depth, f.channels, f.duration_s, f.is_ucs, f.has_bext,
                           f.has_ixml, f.scan_error,
                           (SELECT COUNT(*) FROM accepted_tags t WHERE t.file_id = f.id) AS accepted_tag_count,
                           (SELECT COUNT(*) FROM metadata_fields mf WHERE mf.file_id = f.id) AS metadata_field_count,
                           (SELECT COUNT(*) FROM fn_issues i WHERE i.file_id = f.id) AS issue_count
                    FROM files f
                    WHERE f.filename LIKE ? OR f.path LIKE ?
                    ORDER BY f.path
                    LIMIT ?
                    """,
                    (like, like, limit),
                ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT f.path, f.filename, f.extension, f.size_bytes, f.sample_rate,
                       f.bit_depth, f.channels, f.duration_s, f.is_ucs, f.has_bext,
                       f.has_ixml, f.scan_error,
                       (SELECT COUNT(*) FROM accepted_tags t WHERE t.file_id = f.id) AS accepted_tag_count,
                       (SELECT COUNT(*) FROM metadata_fields mf WHERE mf.file_id = f.id) AS metadata_field_count,
                       (SELECT COUNT(*) FROM fn_issues i WHERE i.file_id = f.id) AS issue_count
                FROM files f
                ORDER BY f.path
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    return [
        FileRow(
            path=row["path"],
            filename=row["filename"],
            extension=row["extension"],
            size_bytes=row["size_bytes"],
            sample_rate=row["sample_rate"],
            bit_depth=row["bit_depth"],
            channels=row["channels"],
            duration_s=row["duration_s"],
            is_ucs=bool(row["is_ucs"]),
            has_bext=bool(row["has_bext"]),
            has_ixml=bool(row["has_ixml"]),
            scan_error=row["scan_error"],
            accepted_tag_count=int(row["accepted_tag_count"]),
            metadata_field_count=int(row["metadata_field_count"]),
            issue_count=int(row["issue_count"]),
        )
        for row in rows
    ]


def file_detail(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    path: str,
    library_path: str | Path | None = None,
    plan_path: Path | None = None,
) -> FileDetail | None:
    """Return a compact file detail payload for the read-only TUI."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT path, filename, stem, extension, size_bytes, mtime, md5,
                   sample_rate, bit_depth, channels, duration_s, subtype,
                   has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
                   has_sampler, metadata_sources, is_ucs, scan_error, scanned_at
            FROM files
            WHERE path = ?
            """,
            (path,),
        ).fetchone()
        if row is None:
            return None
        issues = conn.execute(
            """
            SELECT issue, component, detail
            FROM fn_issues
            WHERE file_id = (SELECT id FROM files WHERE path = ?)
            ORDER BY issue, component
            """,
            (path,),
        ).fetchall()
        tags = conn.execute(
            """
            SELECT field, value, source, confidence
            FROM accepted_tags
            WHERE file_id = (SELECT id FROM files WHERE path = ?)
            ORDER BY field, value
            """,
            (path,),
        ).fetchall()
        embedded_fields = conn.execute(
            """
            SELECT namespace, key, value, source
            FROM metadata_fields
            WHERE file_id = (SELECT id FROM files WHERE path = ?)
            ORDER BY namespace, key, value, source
            LIMIT 24
            """,
            (path,),
        ).fetchall()
        segment_count = _count(
            conn,
            "SELECT COUNT(*) FROM audio_segments WHERE file_id = (SELECT id FROM files WHERE path = ?)",
            (path,),
        )
        duplicate_count = 0
        if row["md5"]:
            duplicate_count = _count(conn, "SELECT COUNT(*) FROM files WHERE md5 = ?", (row["md5"],))
    finally:
        conn.close()

    db = _db_arg(db_path)
    quoted_path = _quote_path(row["path"])
    quoted_root = _quote_path(_command_root(db_path, library_path))
    proposed_rows: list[tuple[str, str]] = []
    if plan_path is not None and plan_path.exists():
        try:
            payload = json.loads(plan_path.read_text())
        except json.JSONDecodeError:
            payload = {}
        for entry in payload.get("entries", []):
            if str(entry.get("path", "")) != row["path"]:
                continue
            field = str(entry.get("field", "")).strip()
            proposed = str(entry.get("proposed_value", "")).strip()
            if not field or not proposed:
                continue
            status = str(entry.get("review_status", "pending")).strip() or "pending"
            source = str(entry.get("source", "")).strip()
            confidence = entry.get("confidence")
            suffix_parts = [status]
            if source:
                suffix_parts.append(source)
            if isinstance(confidence, int | float):
                suffix_parts.append(f"{float(confidence):.2f}")
            proposed_rows.append((_tag_label(field), f"{proposed} [{' / '.join(suffix_parts)}]"))
        proposed_rows.sort(key=lambda item: (_tag_field_rank(item[0]), item[0].lower(), item[1].lower()))
    actions: list[str] = []
    actions.append(f"Reveal in Finder: open -R {quoted_path}")
    actions.append(f"Audition with default audio app: open {quoted_path}")
    if row["scan_error"]:
        actions.append(f"Plan scan-error cleanup: uv run sfx scan-errors {db} --output ~/reports/scan_error_plan.json")
    if issues:
        actions.append(f"Preview portable rename for this library: uv run sfx rename {quoted_root} --pattern portable")
    if duplicate_count > 1:
        actions.append(f"Write duplicate review plan: uv run sfx dedupe {db} --output ~/reports/dedupe_plan.json")
    if not row["has_bext"] and not row["has_ixml"]:
        actions.append(f"Inspect indexed metadata: uv run sfx metadata view {quoted_path} {db}")
    elif not row["has_bext"]:
        actions.append(f"Review BEXT gap: uv run sfx metadata view {quoted_path} {db}")
    elif not row["has_ixml"]:
        actions.append(f"Review iXML gap: uv run sfx metadata view {quoted_path} {db}")
    if row["is_ucs"]:
        actions.append(f"Validate UCS provenance: uv run sfx ucs validate {quoted_root} {db} --json")
    if tags:
        actions.append(
            f"Export accepted DB tags: uv run sfx tag sidecar-export ~/reports/accepted_tags.sidecar.json {db}"
        )

    location_rows = (
        ("Filename", row["filename"]),
        ("Path", row["path"]),
        ("Stem", row["stem"] or ""),
        ("Extension", row["extension"] or ""),
        ("Size", f"{int(row['size_bytes'] or 0):,} bytes" if row["size_bytes"] is not None else ""),
        ("Scanned", row["scanned_at"] or ""),
    )
    audio_rows = (
        ("Duration", f"{float(row['duration_s']):.2f}s" if row["duration_s"] is not None else ""),
        ("Format", row["subtype"] or ""),
        ("Sample rate", str(row["sample_rate"] or "")),
        ("Bit depth", str(row["bit_depth"] or "")),
        ("Channels", str(row["channels"] or "")),
    )
    embedded_flag_rows = (
        ("BEXT", "yes" if row["has_bext"] else "no"),
        ("iXML", "yes" if row["has_ixml"] else "no"),
        ("RIFF INFO", "yes" if row["has_riff_info"] else "no"),
        ("ADM", "yes" if row["has_adm"] else "no"),
        ("Cue markers", "yes" if row["has_cue_markers"] else "no"),
        ("Sampler", "yes" if row["has_sampler"] else "no"),
        ("Metadata sources", row["metadata_sources"] or ""),
    )
    search_note_rows = (
        (
            "Search fields",
            "description, keywords, category/subcategory, title/name, and comments are the useful values to vet.",
        ),
        ("Context only", "filename/path help inference but are not proposed metadata by themselves."),
    )
    sorted_embedded_fields = sorted(
        embedded_fields,
        key=lambda field: (
            _metadata_key_rank(str(field["namespace"]), str(field["key"])),
            str(field["namespace"]).lower(),
            str(field["key"]).lower(),
            str(field["value"]).lower(),
        ),
    )
    search_embedded_rows = tuple(
        (
            _metadata_label(str(field["namespace"]), str(field["key"])),
            f"{field['value']} [{field['source']}]",
        )
        for field in sorted_embedded_fields
        if _metadata_key_rank(str(field["namespace"]), str(field["key"])) < 50
    )
    context_embedded_rows = tuple(
        (
            f"{field['key']} ({field['namespace']})",
            f"{field['value']} [{field['source']}]",
        )
        for field in sorted_embedded_fields
        if _metadata_key_rank(str(field["namespace"]), str(field["key"])) >= 50
    )
    accepted_tag_rows = tuple(
        (
            _tag_label(str(tag["field"])),
            f"{tag['value']} [{tag['source']}"
            + (f", {float(tag['confidence']):.2f}" if tag["confidence"] is not None else "")
            + "]",
        )
        for tag in sorted(tags, key=lambda item: (_tag_field_rank(str(item["field"])), item["field"], item["value"]))
    )
    review_rows = (
        ("UCS-looking", "yes" if row["is_ucs"] else "no"),
        ("MD5", row["md5"] or ""),
        ("Duplicate count", str(duplicate_count) if duplicate_count > 1 else "0"),
        ("Segments", str(segment_count)),
        ("Scan error", row["scan_error"] or ""),
    )
    sections = (
        FileDetailSection("Searchable Metadata To Vet", search_note_rows),
        FileDetailSection("Read From File - Search Fields", search_embedded_rows),
        FileDetailSection("Planned DB Tags", tuple(proposed_rows)),
        FileDetailSection("Already Applied - DB Tags", accepted_tag_rows),
        FileDetailSection("Read From File - Provenance/Technical", context_embedded_rows),
        FileDetailSection("Audio", audio_rows),
        FileDetailSection("Embedded Metadata Flags", embedded_flag_rows),
        FileDetailSection("Review State", review_rows),
        FileDetailSection("Location", location_rows),
    )
    facts = (
        search_note_rows
        + search_embedded_rows
        + tuple(proposed_rows)
        + accepted_tag_rows
        + context_embedded_rows
        + audio_rows
        + embedded_flag_rows
        + review_rows
        + location_rows
    )
    issue_lines = tuple(f"{issue['issue']} ({issue['component']}): {issue['detail'] or ''}".strip() for issue in issues)
    tag_lines = tuple(
        f"{tag['field']}={tag['value']} [{tag['source']}"
        + (f", {float(tag['confidence']):.2f}" if tag["confidence"] is not None else "")
        + "]"
        for tag in tags
    )
    return FileDetail(
        path=row["path"],
        filename=row["filename"],
        facts=facts,
        sections=sections,
        issues=issue_lines,
        tags=tag_lines,
        actions=tuple(actions),
    )


def list_queue_items(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    queue_key: str,
    filter_text: str = "",
    limit: int = 100,
) -> list[QueueItem]:
    """Return representative rows for a review queue."""
    conn = get_connection(db_path)
    try:
        standard_rate_placeholders = ",".join("?" for _ in _STANDARD_SAMPLE_RATES)
        standard_rates = tuple(sorted(_STANDARD_SAMPLE_RATES))
        if queue_key in {"filename_issues", "long_paths", "unicode_normalization"}:
            where = ""
            params: tuple[Any, ...] = ()
            if queue_key == "long_paths":
                where = "WHERE i.issue = ?"
                params = ("path_too_long",)
            elif queue_key == "unicode_normalization":
                where = "WHERE i.issue = ?"
                params = ("unicode_normalization",)
            filter_clause, filter_params = _like_filter_clause(
                ("f.filename", "f.path", "i.issue", "i.component", "i.detail"),
                filter_text,
            )
            where_prefix = where if where else "WHERE 1 = 1"
            rows = conn.execute(
                f"""
                SELECT f.filename, f.path, i.issue, i.component, i.detail
                FROM fn_issues i
                JOIN files f ON f.id = i.file_id
                {where_prefix}
                {filter_clause}
                ORDER BY i.issue, f.path
                LIMIT ?
                """,
                (*params, *filter_params, limit),
            ).fetchall()
            return [
                QueueItem(
                    queue_key,
                    row["filename"],
                    row["path"],
                    f"{row['issue']} ({row['component']}): {row['detail'] or ''}".strip(),
                    "warning",
                )
                for row in rows
            ]
        if queue_key == "scan_errors":
            filter_clause, filter_params = _like_filter_clause(("filename", "path", "scan_error"), filter_text)
            rows = conn.execute(
                f"""
                SELECT filename, path, scan_error
                FROM files
                WHERE scan_error IS NOT NULL
                {filter_clause}
                ORDER BY path
                LIMIT ?
                """,
                (*filter_params, limit),
            ).fetchall()
            return [
                QueueItem(queue_key, row["filename"], row["path"], row["scan_error"] or "", "error") for row in rows
            ]
        if queue_key in {"missing_metadata", "missing_bext", "missing_ixml"}:
            if queue_key == "missing_metadata":
                where = "has_bext = 0 AND has_ixml = 0"
                detail = "No BEXT or iXML metadata"
            elif queue_key == "missing_bext":
                where = "has_bext = 0"
                detail = "No BEXT metadata"
            else:
                where = "has_ixml = 0"
                detail = "No iXML metadata"
            filter_clause, filter_params = _like_filter_clause(
                ("filename", "path", "extension", "subtype", "sample_rate", "bit_depth", "channels"),
                filter_text,
            )
            rows = conn.execute(
                f"""
                SELECT filename, path, sample_rate, bit_depth, channels, duration_s
                FROM files
                WHERE {where}
                {filter_clause}
                ORDER BY path
                LIMIT ?
                """,
                (*filter_params, limit),
            ).fetchall()
            return [
                QueueItem(
                    queue_key,
                    row["filename"],
                    row["path"],
                    detail + (f" | {_audio_detail(row)}" if _audio_detail(row) else ""),
                    "review",
                )
                for row in rows
            ]
        if queue_key == "unusual_rates":
            filter_clause, filter_params = _like_filter_clause(
                ("filename", "path", "extension", "subtype", "sample_rate", "bit_depth", "channels"),
                filter_text,
            )
            rows = conn.execute(
                f"""
                SELECT filename, path, sample_rate, bit_depth, channels, duration_s
                FROM files
                WHERE sample_rate IS NOT NULL
                  AND sample_rate NOT IN ({standard_rate_placeholders})
                {filter_clause}
                ORDER BY sample_rate, path
                LIMIT ?
                """,
                (*standard_rates, *filter_params, limit),
            ).fetchall()
            return [
                QueueItem(
                    queue_key,
                    row["filename"],
                    row["path"],
                    _audio_detail(row) or f"{row['sample_rate']} Hz",
                    "review",
                )
                for row in rows
            ]
        if queue_key == "duplicates":
            filter_clause, filter_params = _like_filter_clause(("f.filename", "f.path", "f.md5"), filter_text)
            rows = conn.execute(
                f"""
                SELECT f.filename, f.path, f.md5, d.copy_count
                FROM files f
                JOIN (
                    SELECT md5, COUNT(*) AS copy_count
                    FROM files
                    WHERE md5 IS NOT NULL
                    GROUP BY md5
                    HAVING COUNT(*) > 1
                ) d ON d.md5 = f.md5
                WHERE 1 = 1
                {filter_clause}
                ORDER BY d.copy_count DESC, f.md5, f.path
                LIMIT ?
                """,
                (*filter_params, limit),
            ).fetchall()
            return [
                QueueItem(
                    queue_key,
                    row["filename"],
                    row["path"],
                    f"{row['copy_count']} copies, md5 {str(row['md5'])[:12]}",
                    "review",
                )
                for row in rows
            ]
        if queue_key == "ucs_named":
            filter_clause, filter_params = _like_filter_clause(("filename", "path"), filter_text)
            rows = conn.execute(
                f"""
                SELECT filename, path
                FROM files
                WHERE is_ucs = 1
                {filter_clause}
                ORDER BY path
                LIMIT ?
                """,
                (*filter_params, limit),
            ).fetchall()
            return [QueueItem(queue_key, row["filename"], row["path"], "UCS-looking filename", "info") for row in rows]
        if queue_key == "db_only_tags":
            filter_clause, filter_params = _like_filter_clause(
                ("f.filename", "f.path", "t.field", "t.value", "t.source"), filter_text
            )
            rows = conn.execute(
                f"""
                SELECT f.filename, f.path, GROUP_CONCAT(t.field || '=' || t.value, '; ') AS tags
                FROM accepted_tags t
                JOIN files f ON f.id = t.file_id
                WHERE 1 = 1
                {filter_clause}
                GROUP BY f.id
                ORDER BY f.path
                LIMIT ?
                """,
                (*filter_params, limit),
            ).fetchall()
            return [QueueItem(queue_key, row["filename"], row["path"], row["tags"] or "", "info") for row in rows]
        if queue_key == "similarity_feedback":
            filter_clause, filter_params = _like_filter_clause(
                ("lf.filename", "lf.path", "rf.filename", "fb.state", "fb.scope", "fb.note"),
                filter_text,
            )
            rows = conn.execute(
                f"""
                SELECT lf.filename AS left_filename, lf.path AS left_path,
                       rf.filename AS right_filename, fb.state, fb.scope, fb.note
                FROM similarity_feedback fb
                JOIN files lf ON lf.id = fb.left_file_id
                JOIN files rf ON rf.id = fb.right_file_id
                WHERE 1 = 1
                {filter_clause}
                ORDER BY fb.updated_at DESC
                LIMIT ?
                """,
                (*filter_params, limit),
            ).fetchall()
            return [
                QueueItem(
                    queue_key,
                    row["left_filename"],
                    row["left_path"],
                    f"{row['state']} {row['scope']} match with {row['right_filename']}"
                    + (f": {row['note']}" if row["note"] else ""),
                    "info",
                )
                for row in rows
            ]
    finally:
        conn.close()
    return []


def protected_folders(config_path: Path | None = None) -> list[str]:
    return list(build_preservation_rules(config_path=config_path).safe_folders)


def _list_value(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key, [])
    return value if isinstance(value, list) else []


def _summary_value(payload: dict[str, Any], key: str) -> int:
    summary = payload.get("summary", {})
    if isinstance(summary, dict):
        value = summary.get(key, 0)
        return int(value or 0) if isinstance(value, int | float) else 0
    return 0


def _report_category(path: Path, kind: str, *, command: str | None = None, pattern: str | None = None) -> str:
    stem = path.stem.casefold()
    if kind == "action_history":
        return "History"
    if kind == "organize_nesting_report":
        return "Report"
    if kind == "clean_preview":
        return "Preview"
    if kind == "clean_apply":
        return "Log"
    if "log" in stem or "undo" in stem or (command and ("apply" in command or "undo" in command)):
        return "Log"
    if "plan" in stem or kind.endswith("_plan") or kind in {"dedupe_plan", "pack_plan", "metadata_write_plan"}:
        return "Plan"
    if pattern and not pattern.startswith("organize:"):
        return "Plan"
    return "Report"


def summarize_plan_file(path: Path) -> PlanSummary:
    """Summarize a JSON report/plan/log for the first before/after viewer."""
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")

    body = payload.get("plan") or payload.get("report") or payload
    if not isinstance(body, dict):
        body = payload
    command = payload.get("command") if isinstance(payload.get("command"), str) else None
    pattern = body.get("pattern") if isinstance(body.get("pattern"), str) else None
    target = body.get("target") if isinstance(body.get("target"), str) else None
    entries = _list_value(body, "entries")
    errors = _list_value(body, "errors")
    protected = sum(1 for error in errors if isinstance(error, dict) and error.get("safe_folder"))
    conflicts = sum(1 for error in errors if isinstance(error, dict) and "conflict" in str(error.get("error", "")))

    if command == "tui_action":
        kind = "action_history"
        entries_count = 1
        action = body.get("action") if isinstance(body.get("action"), str) else "action"
        status = body.get("status") if isinstance(body.get("status"), str) else ""
        title = f"{action.replace('_', ' ').title()} ({status})" if status else action.replace("_", " ").title()
        undoable = False
    elif "groups" in body:
        kind = "dedupe_plan"
        entries_count = len(_list_value(body, "groups"))
        title = "Dedupe plan"
        undoable = True
    elif "dry_run" in body and ("removed_files" in body or "removed_dirs" in body):
        dry_run = bool(body.get("dry_run"))
        kind = "clean_preview" if dry_run else "clean_apply"
        entries_count = len(_list_value(body, "removed_files")) + len(_list_value(body, "removed_dirs"))
        title = "Junk cleanup preview" if dry_run else "Junk cleanup log"
        undoable = False
    elif body.get("tool") == "sfxworkbench" and "summary" in body and "entries" in body and "source_report" in body:
        kind = "pack_plan"
        entries_count = len(entries)
        title = "Pack consolidation plan"
        undoable = True
    elif pattern == "redundant-nesting":
        kind = "organize_nesting_report"
        entries_count = len(_list_value(body, "candidates"))
        title = "Nested folder candidates"
        undoable = False
    elif "source_report" in body and entries and all(isinstance(entry, dict) and "moves" in entry for entry in entries):
        kind = "organize_nesting_plan"
        entries_count = len(entries)
        title = "Nesting apply plan"
        undoable = True
    elif pattern and pattern.startswith("organize:"):
        kind = "organize_apply_log"
        entries_count = len(entries)
        title = f"Organization log ({pattern})"
        undoable = True
    elif pattern:
        kind = "rename_or_organize"
        entries_count = len(entries)
        title = f"{pattern} plan"
        undoable = True
    elif target == "embedded_metadata" or body.get("backend"):
        kind = "metadata_write_plan"
        entries_count = len(entries)
        title = "Metadata write plan"
        conflicts += _summary_value(body, "conflict_entries")
        undoable = False
    elif (
        body.get("source_log") and entries and all(isinstance(entry, dict) and "entry_id" in entry for entry in entries)
    ):
        kind = "delete_plan"
        entries_count = len(entries)
        title = "Permanent delete plan"
        undoable = False
    elif command:
        kind = command
        entries_count = len(entries)
        title = command.replace("_", " ").title()
        undoable = "undo" in json.dumps(body) or "log" in command
    else:
        kind = "json_report"
        entries_count = len(entries)
        title = body.get("tool", path.stem) if isinstance(body.get("tool"), str) else path.stem
        undoable = False

    candidates = len(_list_value(body, "candidates"))
    if entries_count == 0 and candidates:
        entries_count = candidates
    category = _report_category(path, kind, command=command, pattern=pattern)
    description = f"{entries_count:,} item(s), {len(errors):,} error(s)"
    if protected:
        description += f", {protected:,} protected"
    return PlanSummary(
        path=str(path),
        category=category,
        kind=kind,
        title=title,
        entries=entries_count,
        errors=len(errors),
        protected=protected,
        conflicts=conflicts,
        undoable=undoable,
        description=description,
    )


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str | int | float):
            return str(value)
    return ""


def _nesting_candidate_detail(candidate: dict[str, Any]) -> str:
    parts = []
    reason = _first_text(candidate, "reason")
    if reason:
        parts.append(reason)
    audio_files = candidate.get("audio_files")
    if isinstance(audio_files, int | float):
        parts.append(f"{int(audio_files):,} audio file(s)")
    child_dirs = candidate.get("child_dirs")
    direct_files = candidate.get("direct_files")
    if isinstance(child_dirs, int | float) or isinstance(direct_files, int | float):
        parts.append(f"{int(child_dirs or 0):,} child dir(s), {int(direct_files or 0):,} direct file(s)")
    return "; ".join(parts)


def _append_output_report_rows(rows: list[PlanDetailRow], body: dict[str, Any], path: Path, limit: int) -> None:
    output_path = body.get("output_path")
    if not isinstance(output_path, str) or not output_path:
        return
    report_path = Path(output_path).expanduser()
    if not report_path.exists() or report_path.resolve() == path.resolve() or report_path.suffix.lower() != ".json":
        return
    rows.append(PlanDetailRow("output", "report", str(report_path), "", "", "Generated report detail"))
    remaining = max(0, limit - len(rows))
    if not remaining:
        return
    try:
        rows.extend(plan_detail_rows(report_path, limit=remaining))
    except (OSError, ValueError, json.JSONDecodeError):
        return


def plan_detail_rows(path: Path, *, limit: int = 100) -> list[PlanDetailRow]:
    """Return representative rows from a JSON report, plan, or apply log."""
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    body = payload.get("plan") or payload.get("report") or payload
    if not isinstance(body, dict):
        body = payload

    rows: list[PlanDetailRow] = []
    if payload.get("command") == "tui_action":
        rows.append(
            PlanDetailRow(
                "action",
                _first_text(body, "action"),
                _first_text(body, "output_path"),
                "",
                _first_text(body, "status"),
                _first_text(body, "message"),
            )
        )
        details = body.get("details")
        if isinstance(details, dict):
            summary = details.get("summary")
            if isinstance(summary, dict):
                for key, value in summary.items():
                    rows.append(PlanDetailRow("summary", str(key), _display_value(value)))
                    if len(rows) >= limit:
                        return rows[:limit]
        _append_output_report_rows(rows, body, path, limit)
        if len(rows) >= limit:
            return rows[:limit]

    summary = body.get("summary")
    if isinstance(summary, dict):
        for key, value in summary.items():
            rows.append(PlanDetailRow("summary", str(key), _display_value(value)))
            if len(rows) >= limit:
                return rows[:limit]

    entries = _list_value(body, "entries")
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            rows.append(PlanDetailRow("entry", "", _display_value(entry)))
            continue
        action = _first_text(entry, "action", "operation", "status", "review_status")
        if "entry_id" in entry and "source_log" in entry:
            source = _first_text(entry, "path")
            target = _first_text(entry, "source_path")
        else:
            source = _first_text(entry, "old_path", "source_path", "path", "file_path", "filename", "field")
            target = _first_text(entry, "new_path", "target_path", "destination_path", "value", "new_value")
        status = _first_text(entry, "status", "review_status", "result", "decision")
        moves = _list_value(entry, "moves")
        detail = _first_text(entry, "reason", "detail", "message", "error")
        if "entry_id" in entry and "source_log" in entry:
            path_type = _first_text(entry, "path_type")
            size = entry.get("size_bytes")
            detail_parts = [
                part for part in (path_type, f"{size:,} byte(s)" if isinstance(size, int | float) else "") if part
            ]
            detail = "; ".join(detail_parts)
        if moves:
            move_detail = f"{len(moves):,} move(s)"
            audio_files = entry.get("audio_files")
            if isinstance(audio_files, int | float):
                move_detail += f", {int(audio_files):,} audio file(s)"
            detail = f"{detail}; {move_detail}" if detail else move_detail
        rows.append(PlanDetailRow("entry", action, source, target, status, detail))
        for move in moves[: max(0, limit - len(rows))]:
            if isinstance(move, dict):
                rows.append(
                    PlanDetailRow(
                        "move",
                        _first_text(move, "path_type"),
                        _first_text(move, "old_path"),
                        _first_text(move, "new_path"),
                    )
                )
            else:
                rows.append(PlanDetailRow("move", "", _display_value(move)))
        if len(rows) >= limit:
            return rows[:limit]

    groups = _list_value(body, "groups")
    for group in groups[: max(0, limit - len(rows))]:
        if not isinstance(group, dict):
            rows.append(PlanDetailRow("group", "", _display_value(group)))
            continue
        source = _first_text(group, "md5", "group_key", "path")
        files = _list_value(group, "files")
        detail = f"{len(files)} file(s)" if files else _first_text(group, "reason", "detail")
        rows.append(PlanDetailRow("group", _first_text(group, "action", "status"), source, "", "", detail))

    errors = _list_value(body, "errors")
    for error in errors[: max(0, limit - len(rows))]:
        if isinstance(error, dict):
            rows.append(
                PlanDetailRow(
                    "error",
                    _first_text(error, "action", "kind"),
                    _first_text(error, "path", "file_path", "old_path"),
                    _first_text(error, "new_path", "target_path"),
                    "error",
                    _first_text(error, "error", "message", "detail"),
                )
            )
        else:
            rows.append(PlanDetailRow("error", "", "", "", "error", _display_value(error)))

    candidates = _list_value(body, "candidates")
    for candidate in candidates[: max(0, limit - len(rows))]:
        if isinstance(candidate, dict):
            rows.append(
                PlanDetailRow(
                    "candidate",
                    _first_text(candidate, "suggested_action", "action", "kind", "status"),
                    _first_text(candidate, "path", "source_path", "filename"),
                    _first_text(candidate, "target_path", "destination_path"),
                    _first_text(candidate, "confidence", "status", "review_status"),
                    _nesting_candidate_detail(candidate),
                )
            )
        else:
            rows.append(PlanDetailRow("candidate", "", _display_value(candidate)))

    return rows[:limit]


def _plan_matches_query(path: Path, query: str) -> bool:
    terms = tuple(term.casefold() for term in query.split() if term.strip())
    if not terms:
        return True
    haystacks = [path.name.casefold(), str(path).casefold()]
    try:
        text = path.read_text(errors="ignore").casefold()
    except OSError:
        text = ""
    haystacks.append(text)
    return any(any(term in haystack for haystack in haystacks) for term in terms)


def discover_plan_files(
    paths: list[Path],
    *,
    query: str = "",
    category: str = "",
    limit: int = 100,
    modified_since: float | None = None,
) -> list[PlanSummary]:
    """Discover JSON plans/reports/logs from files or directories."""

    def candidate_mtime(candidate: Path) -> float:
        try:
            return candidate.stat().st_mtime
        except OSError:
            return 0.0

    summaries: list[PlanSummary] = []
    candidates: list[Path] = []
    category_filter = category.casefold().strip()
    for path in paths:
        expanded = path.expanduser()
        if expanded.is_file() and expanded.suffix.lower() == ".json":
            candidates.append(expanded)
        elif expanded.is_dir():
            candidates.extend(sorted(expanded.glob("*.json")))
            apply_log_dir = expanded / APPLY_LOG_DIR_NAME
            if apply_log_dir.is_dir():
                candidates.extend(sorted(apply_log_dir.glob("*.json")))
            action_history_dir = expanded / "action_history"
            if action_history_dir.is_dir():
                candidates.extend(sorted(action_history_dir.glob("*.json")))
    candidates = sorted(
        dict.fromkeys(candidates),
        key=lambda candidate: (candidate_mtime(candidate), str(candidate)),
        reverse=True,
    )
    for candidate in candidates:
        if modified_since is not None:
            try:
                if candidate.stat().st_mtime < modified_since:
                    continue
            except OSError:
                continue
        if query and not _plan_matches_query(candidate, query):
            continue
        try:
            summary = summarize_plan_file(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if category_filter and summary.category.casefold() != category_filter:
            continue
        summaries.append(summary)
        if len(summaries) >= limit:
            break
    return summaries
