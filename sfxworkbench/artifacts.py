"""SQLite artifact registry for generated JSON reports, plans, and logs."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sfxworkbench.db import DEFAULT_DB_PATH, get_connection
from sfxworkbench.platform_paths import canonical_path_key, is_scoped_path
from sfxworkbench.utils import fmt_bytes

APPLY_LOG_DIR_NAME = "apply_logs"
ACTION_HISTORY_DIR_NAME = "action_history"
_LIGHTWEIGHT_SUMMARY_FULL_PARSE_MAX_BYTES = 128 * 1024

_HISTORY_FEATURE_LABELS = {
    "scan": "Scan",
    "files": "Files",
    "clean": "Cleanup",
    "dedupe": "Dedupe",
    "metadata": "Metadata",
}

_HISTORY_FEATURE_QUERIES = {
    "scan": "audit scan metadata format groups ucs pack",
    "files": "scan delete quarantine compare processed",
    "clean": "clean scan_error rename organize nesting",
    "dedupe": "dedupe pack quarantine",
    "metadata": "metadata tag sidecar metadata_write dual_mono",
}

_MATERIALIZED_KINDS = {
    "dedupe_plan",
    "delete_plan",
    "metadata_write_plan",
    "organize_nesting_plan",
    "organize_nesting_report",
    "pack_plan",
    "rename_or_organize",
    "tag_plan",
}


@dataclass(frozen=True)
class ArtifactSummary:
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
    id: int | None = None
    feature: str = ""
    status: str = "ok"
    created_at: str = ""


@dataclass(frozen=True)
class ArtifactDetailRow:
    kind: str
    action: str
    source: str
    target: str = ""
    status: str = ""
    detail: str = ""


@dataclass(frozen=True)
class ArtifactSyncResult:
    scanned: int = 0
    registered: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    errors: int = 0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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


def _list_value(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key, [])
    return value if isinstance(value, list) else []


def _summary_int(summary: dict[str, Any] | None, key: str) -> int:
    if not summary:
        return 0
    value = summary.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _summary_value(payload: dict[str, Any], key: str) -> int:
    summary = payload.get("summary", {})
    return _summary_int(summary if isinstance(summary, dict) else None, key)


def _json_summary_from_tail(path: Path, *, tail_bytes: int = 256 * 1024) -> dict[str, Any] | None:
    """Read a top-level ``summary`` object from the end of a large JSON file."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - tail_bytes))
            text = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return None
    marker = '"summary"'
    marker_index = text.rfind(marker)
    if marker_index < 0:
        return None
    colon_index = text.find(":", marker_index + len(marker))
    if colon_index < 0:
        return None
    start = colon_index + 1
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] != "{":
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_head_values(path: Path, *, max_bytes: int = 64 * 1024) -> dict[str, str]:
    try:
        with path.open("rb") as handle:
            text = handle.read(max_bytes).decode("utf-8", errors="ignore")
    except OSError:
        return {}
    if text.lstrip()[:1] != "{":
        return {}
    values: dict[str, str] = {}
    for key in ("command", "pattern", "target", "action", "status", "tool", "generated_at"):
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', text)
        if not match:
            continue
        try:
            values[key] = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            values[key] = match.group(1)
    return values


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


def _summary_entry_count(summary: dict[str, Any] | None) -> int:
    if not summary:
        return 0
    for key in (
        "entries",
        "total_entries",
        "candidate_entries",
        "add_entries",
        "groups",
        "duplicate_groups",
        "candidate_groups",
        "reported_groups",
        "candidates",
        "files",
        "files_scanned",
        "removed_files",
    ):
        value = _summary_int(summary, key)
        if value:
            return value
    return 0


def _metadata_tag_summary(path: Path) -> ArtifactSummary | None:
    stem = path.stem.casefold()
    if "tag_plan" not in stem and "metadata_tag_plan" not in stem:
        return None
    summary = _json_summary_from_tail(path)
    candidate_entries = _summary_int(summary, "candidate_entries")
    add_entries = _summary_int(summary, "add_entries")
    skip_existing_entries = _summary_int(summary, "skip_existing_entries")
    approved_entries = _summary_int(summary, "approved_entries")
    rejected_entries = _summary_int(summary, "rejected_entries")
    if not any((candidate_entries, add_entries, skip_existing_entries, approved_entries, rejected_entries)):
        return None
    entries = candidate_entries or add_entries + skip_existing_entries
    description = f"{add_entries:,} add, {skip_existing_entries:,} skipped existing"
    if approved_entries or rejected_entries:
        description += f", {approved_entries:,} approved, {rejected_entries:,} rejected"
    return ArtifactSummary(
        path=str(path),
        category="Plan",
        kind="tag_plan",
        title="Metadata tag plan",
        entries=entries,
        errors=0,
        description=description,
        feature="metadata",
    )


def _lightweight_kind_from_name(path: Path, head: dict[str, str]) -> tuple[str, str, str, bool]:
    stem = path.stem.casefold()
    parent = path.parent.name.casefold()
    command = head.get("command", "")
    pattern = head.get("pattern", "")
    target = head.get("target", "")
    action = head.get("action", "")
    status = head.get("status", "")

    if parent == ACTION_HISTORY_DIR_NAME or stem.startswith("tui_action_") or command == "tui_action":
        title_action = (action or stem).replace("_", " ").title()
        title = f"{title_action} ({status})" if status else title_action
        return "action_history", title, "", False
    if "metadata_tag_plan" in stem or "tag_plan" in stem:
        return "tag_plan", "Metadata tag plan", "", False
    if "metadata_write" in stem or target == "embedded_metadata":
        return "metadata_write_plan", "Metadata write plan", "", False
    if "dedupe" in stem:
        return "dedupe_plan", "Dedupe plan", "", True
    if "pack" in stem:
        return "pack_plan", "Pack consolidation plan", "", True
    if "clean_preview" in stem:
        return "clean_preview", "Junk cleanup preview", "", False
    if "clean" in stem and ("log" in stem or "apply" in stem):
        return "clean_apply", "Junk cleanup log", "", False
    if "delete" in stem and "plan" in stem:
        return "delete_plan", "Permanent delete plan", "", False
    if pattern == "redundant-nesting" or ("nesting" in stem and "report" in stem):
        return "organize_nesting_report", "Nested folder candidates", pattern, False
    if "nesting" in stem and "plan" in stem:
        return "organize_nesting_plan", "Nesting apply plan", pattern, True
    if pattern.startswith("organize:") or ("organize" in stem and ("log" in stem or "apply" in stem)):
        return "organize_apply_log", f"Organization log ({pattern})" if pattern else "Organization log", pattern, True
    if "rename" in stem or "organize" in stem or "plan" in stem:
        title = f"{pattern} plan" if pattern else path.stem.replace("_", " ").title()
        return "rename_or_organize", title, pattern, True
    if command:
        return command, command.replace("_", " ").title(), pattern, "undo" in command or "log" in command
    return "json_report", path.stem, pattern, False


def _summarize_artifact_payload(path: Path, payload: dict[str, Any]) -> ArtifactSummary:
    try:
        body = payload.get("plan") or payload.get("report") or payload
    except AttributeError as exc:
        raise ValueError(f"{path}: expected JSON object") from exc
    if not isinstance(body, dict):
        body = payload
    command = payload.get("command") if isinstance(payload.get("command"), str) else None
    pattern = body.get("pattern") if isinstance(body.get("pattern"), str) else None
    target = body.get("target") if isinstance(body.get("target"), str) else None
    artifact_status = (
        body.get("status")
        if isinstance(body.get("status"), str)
        else payload.get("status")
        if isinstance(payload.get("status"), str)
        else "ok"
    )
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
        artifact_status = status or artifact_status
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
    summary = ArtifactSummary(
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
        status=artifact_status,
    )
    return _with_feature(summary)


def summarize_artifact_file(path: Path, *, lightweight: bool = False) -> ArtifactSummary:
    path = path.expanduser()
    if lightweight:
        tag_summary = _metadata_tag_summary(path)
        if tag_summary is not None:
            return tag_summary
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValueError(f"{path}: file not found") from exc
        if size > _LIGHTWEIGHT_SUMMARY_FULL_PARSE_MAX_BYTES:
            head = _json_head_values(path)
            summary = _json_summary_from_tail(path)
            kind, title, pattern, undoable = _lightweight_kind_from_name(path, head)
            command = head.get("command") or None
            category = _report_category(path, kind, command=command, pattern=pattern or None)
            entries = _summary_entry_count(summary)
            errors = _summary_int(summary, "errors")
            description = f"{entries:,} item(s), {errors:,} error(s)"
            if summary:
                visible = [
                    f"{key}={value:,}"
                    for key, value in summary.items()
                    if isinstance(value, int | float) and key != "errors"
                ][:3]
                if visible:
                    description = ", ".join(visible + ([f"errors={errors:,}"] if errors else []))
            return _with_feature(
                ArtifactSummary(
                    path=str(path),
                    category=category,
                    kind=kind,
                    title=title,
                    entries=entries,
                    errors=errors,
                    protected=_summary_int(summary, "protected"),
                    conflicts=_summary_int(summary, "conflicts") or _summary_int(summary, "conflict_entries"),
                    undoable=undoable,
                    description=description,
                    status=head.get("status", "ok") or "ok",
                )
            )
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return _summarize_artifact_payload(path, payload)


def _invalid_summary(path: Path, message: str) -> ArtifactSummary:
    return ArtifactSummary(
        path=str(path),
        category="Report",
        kind="invalid_json",
        title=path.stem,
        entries=0,
        errors=1,
        description=message,
        feature="",
        status="error",
    )


def history_features_for_summary(summary: ArtifactSummary) -> tuple[str, ...]:
    if summary.feature:
        return (summary.feature,)
    haystack = " ".join(
        (
            Path(summary.path).name,
            summary.path,
            summary.category,
            summary.kind,
            summary.title,
            summary.description,
        )
    ).casefold()
    matches: list[str] = []
    for feature, query in _HISTORY_FEATURE_QUERIES.items():
        terms = tuple(term for term in query.casefold().split() if term)
        if any(term in haystack for term in terms):
            matches.append(feature)
    return tuple(matches)


def history_feature_labels(summary: ArtifactSummary) -> str:
    features = history_features_for_summary(summary)
    if not features:
        return "All"
    return ", ".join(_HISTORY_FEATURE_LABELS.get(feature, feature.title()) for feature in features)


def history_matches_feature(summary: ArtifactSummary, feature_filter: str) -> bool:
    normalized = _normalize_feature_filter(feature_filter)
    if normalized in {"", "all", "all recent", "recent"}:
        return True
    return normalized in history_features_for_summary(summary)


def _normalize_feature_filter(value: str) -> str:
    return value.strip().casefold().replace("declutter", "clean").replace("cleanup", "clean")


def _with_feature(summary: ArtifactSummary) -> ArtifactSummary:
    if summary.feature:
        return summary
    features = history_features_for_summary(summary)
    if not features:
        return summary
    return ArtifactSummary(
        path=summary.path,
        category=summary.category,
        kind=summary.kind,
        title=summary.title,
        entries=summary.entries,
        errors=summary.errors,
        protected=summary.protected,
        conflicts=summary.conflicts,
        undoable=summary.undoable,
        description=summary.description,
        id=summary.id,
        feature=features[0],
        status=summary.status,
        created_at=summary.created_at,
    )


def _summary_json(summary: ArtifactSummary) -> str:
    return json.dumps(
        {
            "title": summary.title,
            "description": summary.description,
            "protected": summary.protected,
            "conflicts": summary.conflicts,
            "undoable": summary.undoable,
        },
        sort_keys=True,
    )


def _created_at_for(path: Path) -> str:
    head = _json_head_values(path, max_bytes=16 * 1024)
    generated_at = head.get("generated_at")
    if generated_at:
        return generated_at
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:
        return _utc_now()


def _row_to_summary(row: sqlite3.Row) -> ArtifactSummary:
    try:
        meta = json.loads(row["summary_json"] or "{}")
    except json.JSONDecodeError:
        meta = {}
    return ArtifactSummary(
        id=int(row["id"]),
        path=str(row["path"]),
        category=str(row["category"]),
        kind=str(row["kind"]),
        title=str(meta.get("title") or row["kind"]),
        entries=int(row["entry_count"] or 0),
        errors=int(row["error_count"] or 0),
        protected=int(meta.get("protected") or 0),
        conflicts=int(meta.get("conflicts") or 0),
        undoable=bool(meta.get("undoable")),
        description=str(meta.get("description") or ""),
        feature=str(row["feature"] or ""),
        status=str(row["status"] or "ok"),
        created_at=str(row["created_at"] or ""),
    )


def register_artifact(
    db_path: Path = DEFAULT_DB_PATH,
    path: Path | str | None = None,
    *,
    status: str | None = None,
    materialize: bool = False,
) -> ArtifactSummary:
    if path is None:
        raise ValueError("path is required")
    artifact_path = Path(path).expanduser()
    try:
        summary = summarize_artifact_file(artifact_path, lightweight=True)
    except ValueError as exc:
        summary = _invalid_summary(artifact_path, str(exc))
    if status is not None:
        summary = ArtifactSummary(**{**summary.__dict__, "status": status})
    try:
        stat = artifact_path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    except OSError:
        mtime = 0.0
        size = 0
        summary = ArtifactSummary(**{**summary.__dict__, "status": "missing"})
    created_at = _created_at_for(artifact_path)
    summary = ArtifactSummary(**{**summary.__dict__, "created_at": created_at})

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT id FROM artifacts WHERE path = ?", (str(artifact_path),)).fetchone()
        conn.execute(
            """
            INSERT INTO artifacts (
                path, kind, feature, category, created_at, mtime, size,
                summary_json, entry_count, error_count, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                kind = excluded.kind,
                feature = excluded.feature,
                category = excluded.category,
                created_at = excluded.created_at,
                mtime = excluded.mtime,
                size = excluded.size,
                summary_json = excluded.summary_json,
                entry_count = excluded.entry_count,
                error_count = excluded.error_count,
                status = excluded.status
            """,
            (
                str(artifact_path),
                summary.kind,
                summary.feature,
                summary.category,
                created_at,
                mtime,
                size,
                _summary_json(summary),
                summary.entries,
                summary.errors,
                summary.status,
            ),
        )
        conn.commit()
        artifact_id = row["id"] if row is not None else conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    result = ArtifactSummary(**{**summary.__dict__, "id": int(artifact_id)})
    if materialize and result.kind in _MATERIALIZED_KINDS and result.status != "missing":
        materialize_artifact_rows(db_path, artifact_id=result.id)
    return result


def _artifact_candidates(paths: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    for path in paths:
        expanded = path.expanduser()
        if expanded.is_file() and expanded.suffix.lower() == ".json":
            candidates.append(expanded)
        elif expanded.is_dir():
            candidates.extend(sorted(expanded.glob("*.json")))
            apply_log_dir = expanded / APPLY_LOG_DIR_NAME
            if apply_log_dir.is_dir():
                candidates.extend(sorted(apply_log_dir.glob("*.json")))
            action_history_dir = expanded / ACTION_HISTORY_DIR_NAME
            if action_history_dir.is_dir():
                candidates.extend(sorted(action_history_dir.glob("*.json")))
    return sorted(
        dict.fromkeys(candidates), key=lambda candidate: (candidate.stat().st_mtime, str(candidate)), reverse=True
    )


def _path_under(candidate: Path, root: Path) -> bool:
    if root.is_file():
        return canonical_path_key(candidate.expanduser()) == canonical_path_key(root.expanduser())
    return is_scoped_path(candidate.expanduser(), root.expanduser())


def sync_artifacts_from_paths(
    db_path: Path = DEFAULT_DB_PATH,
    paths: list[Path] | None = None,
    *,
    materialize: bool = False,
) -> ArtifactSyncResult:
    search_paths = paths or default_artifact_search_paths(db_path)
    candidates = _artifact_candidates(search_paths)
    registered = updated = unchanged = errors = 0
    conn = get_connection(db_path)
    try:
        known = {
            row["path"]: (
                int(row["id"]),
                float(row["mtime"] or 0),
                int(row["size"] or 0),
                str(row["status"] or ""),
                str(row["kind"] or ""),
                int(row["materialized_rows"] or 0),
            )
            for row in conn.execute(
                """
                SELECT
                    artifacts.path,
                    artifacts.id,
                    artifacts.mtime,
                    artifacts.size,
                    artifacts.status,
                    artifacts.kind,
                    COUNT(artifact_rows.id) AS materialized_rows
                FROM artifacts
                LEFT JOIN artifact_rows ON artifact_rows.artifact_id = artifacts.id
                GROUP BY artifacts.id
                """
            ).fetchall()
        }
    finally:
        conn.close()

    for candidate in candidates:
        try:
            stat = candidate.stat()
        except OSError:
            continue
        previous = known.get(str(candidate))
        if previous is not None and previous[1:3] == (float(stat.st_mtime), int(stat.st_size)):
            if materialize and previous[4] in _MATERIALIZED_KINDS and previous[5] == 0:
                try:
                    materialize_artifact_rows(db_path, artifact_id=previous[0])
                except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
                    errors += 1
            unchanged += 1
            continue
        try:
            summary = register_artifact(db_path, candidate, materialize=False)
        except (OSError, sqlite3.Error, ValueError):
            errors += 1
            continue
        if previous is None:
            registered += 1
        else:
            updated += 1
        if materialize and summary.kind in _MATERIALIZED_KINDS:
            try:
                materialize_artifact_rows(db_path, artifact_id=summary.id)
            except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
                errors += 1

    missing = 0
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT path FROM artifacts WHERE status != 'missing'").fetchall()
        for row in rows:
            artifact_path = Path(row["path"])
            if artifact_path.exists():
                continue
            if not any(_path_under(artifact_path, root) for root in search_paths):
                continue
            conn.execute("UPDATE artifacts SET status = 'missing', mtime = 0, size = 0 WHERE path = ?", (row["path"],))
            missing += 1
        conn.commit()
    finally:
        conn.close()

    return ArtifactSyncResult(
        scanned=len(candidates),
        registered=registered,
        updated=updated,
        unchanged=unchanged,
        missing=missing,
        errors=errors,
    )


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _feature_filter_clause(feature_filter: str) -> tuple[str, list[Any]]:
    terms = tuple(
        term for term in _HISTORY_FEATURE_QUERIES.get(feature_filter, feature_filter).casefold().split() if term
    )
    if not terms:
        return "LOWER(feature) = ?", [feature_filter]
    term_clauses = []
    params: list[Any] = [feature_filter]
    for term in terms:
        term_clauses.append(
            """
            (
                LOWER(path) LIKE ? ESCAPE '\\'
                OR LOWER(kind) LIKE ? ESCAPE '\\'
                OR LOWER(category) LIKE ? ESCAPE '\\'
                OR LOWER(summary_json) LIKE ? ESCAPE '\\'
            )
            """
        )
        params.extend([_like(term)] * 4)
    return "(LOWER(feature) = ? OR " + " OR ".join(term_clauses) + ")", params


def list_artifacts(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    query: str = "",
    category: str = "",
    feature: str = "",
    limit: int = 100,
) -> list[ArtifactSummary]:
    clauses: list[str] = []
    params: list[Any] = []
    category_filter = category.strip().casefold()
    if category_filter and category_filter not in {"all", "all recent"}:
        clauses.append("LOWER(category) = ?")
        params.append(category_filter)
    feature_filter = _normalize_feature_filter(feature)
    if feature_filter and feature_filter not in {"all", "all recent", "recent"}:
        feature_clause, feature_params = _feature_filter_clause(feature_filter)
        clauses.append(feature_clause)
        params.extend(feature_params)
    terms = tuple(term.casefold() for term in query.split() if term.strip())
    if terms:
        term_clauses = []
        for term in terms:
            term_clauses.append(
                """
                (
                    LOWER(path) LIKE ? ESCAPE '\\'
                    OR LOWER(kind) LIKE ? ESCAPE '\\'
                    OR LOWER(feature) LIKE ? ESCAPE '\\'
                    OR LOWER(category) LIKE ? ESCAPE '\\'
                    OR LOWER(summary_json) LIKE ? ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1
                        FROM artifact_rows ar
                        WHERE ar.artifact_id = artifacts.id
                        AND LOWER(COALESCE(ar.search_text, '')) LIKE ? ESCAPE '\\'
                    )
                )
                """
            )
            params.extend([_like(term)] * 6)
        clauses.append("(" + " OR ".join(term_clauses) + ")")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM artifacts
            {where}
            ORDER BY mtime DESC, id DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_summary(row) for row in rows]


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


def artifact_detail_rows_from_file(path: Path, *, limit: int = 100) -> list[ArtifactDetailRow]:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    body = payload.get("plan") or payload.get("report") or payload
    if not isinstance(body, dict):
        body = payload

    rows: list[ArtifactDetailRow] = []
    if payload.get("command") == "tui_action":
        rows.append(
            ArtifactDetailRow(
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
                    rows.append(ArtifactDetailRow("summary", str(key), _display_value(value)))
                    if len(rows) >= limit:
                        return rows[:limit]
        if len(rows) >= limit:
            return rows[:limit]

    summary = body.get("summary")
    if isinstance(summary, dict):
        for key, value in summary.items():
            rows.append(ArtifactDetailRow("summary", str(key), _display_value(value)))
            if len(rows) >= limit:
                return rows[:limit]

    entries = _list_value(body, "entries")
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            rows.append(ArtifactDetailRow("entry", "", _display_value(entry)))
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
                part for part in (path_type, fmt_bytes(float(size)) if isinstance(size, int | float) else "") if part
            ]
            detail = "; ".join(detail_parts)
        if moves:
            move_detail = f"{len(moves):,} move(s)"
            audio_files = entry.get("audio_files")
            if isinstance(audio_files, int | float):
                move_detail += f", {int(audio_files):,} audio file(s)"
            detail = f"{detail}; {move_detail}" if detail else move_detail
        rows.append(ArtifactDetailRow("entry", action, source, target, status, detail))
        for move in moves[: max(0, limit - len(rows))]:
            if isinstance(move, dict):
                rows.append(
                    ArtifactDetailRow(
                        "move",
                        _first_text(move, "path_type"),
                        _first_text(move, "old_path"),
                        _first_text(move, "new_path"),
                    )
                )
            else:
                rows.append(ArtifactDetailRow("move", "", _display_value(move)))
        if len(rows) >= limit:
            return rows[:limit]

    groups = _list_value(body, "groups")
    for group in groups[: max(0, limit - len(rows))]:
        if not isinstance(group, dict):
            rows.append(ArtifactDetailRow("group", "", _display_value(group)))
            continue
        source = _first_text(group, "md5", "group_key", "path")
        files = _list_value(group, "files")
        detail = f"{len(files)} file(s)" if files else _first_text(group, "reason", "detail")
        rows.append(ArtifactDetailRow("group", _first_text(group, "action", "status"), source, "", "", detail))

    errors = _list_value(body, "errors")
    for error in errors[: max(0, limit - len(rows))]:
        if isinstance(error, dict):
            rows.append(
                ArtifactDetailRow(
                    "error",
                    _first_text(error, "action", "kind"),
                    _first_text(error, "path", "file_path", "old_path"),
                    _first_text(error, "new_path", "target_path"),
                    "error",
                    _first_text(error, "error", "message", "detail"),
                )
            )
        else:
            rows.append(ArtifactDetailRow("error", "", "", "", "error", _display_value(error)))

    candidates = _list_value(body, "candidates")
    for candidate in candidates[: max(0, limit - len(rows))]:
        if isinstance(candidate, dict):
            rows.append(
                ArtifactDetailRow(
                    "candidate",
                    _first_text(candidate, "suggested_action", "action", "kind", "status"),
                    _first_text(candidate, "path", "source_path", "filename"),
                    _first_text(candidate, "target_path", "destination_path"),
                    _first_text(candidate, "confidence", "status", "review_status"),
                    _nesting_candidate_detail(candidate),
                )
            )
        else:
            rows.append(ArtifactDetailRow("candidate", "", _display_value(candidate)))
    return rows[:limit]


def materialize_artifact_rows(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    artifact_id: int | None = None,
    path: Path | str | None = None,
    limit: int = 1000,
) -> int:
    conn = get_connection(db_path)
    try:
        if artifact_id is None:
            if path is None:
                raise ValueError("artifact_id or path is required")
            row = conn.execute(
                "SELECT id, path FROM artifacts WHERE path = ?", (str(Path(path).expanduser()),)
            ).fetchone()
        else:
            row = conn.execute("SELECT id, path FROM artifacts WHERE id = ?", (int(artifact_id),)).fetchone()
        if row is None:
            return 0
        artifact_id = int(row["id"])
        artifact_path = Path(row["path"])
        rows = artifact_detail_rows_from_file(artifact_path, limit=limit)
        conn.execute("DELETE FROM artifact_rows WHERE artifact_id = ?", (artifact_id,))
        for index, detail in enumerate(rows):
            search_text = " ".join(
                part
                for part in (detail.kind, detail.action, detail.source, detail.target, detail.status, detail.detail)
                if part
            )
            conn.execute(
                """
                INSERT INTO artifact_rows (
                    artifact_id, row_index, row_type, action, source,
                    target, status, detail, search_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    index,
                    detail.kind,
                    detail.action,
                    detail.source,
                    detail.target,
                    detail.status,
                    detail.detail,
                    search_text,
                ),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def artifact_detail_rows(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    artifact_id: int | None = None,
    path: Path | str | None = None,
    limit: int = 100,
    parse_fallback: bool = False,
) -> list[ArtifactDetailRow]:
    conn = get_connection(db_path)
    try:
        if artifact_id is None and path is not None:
            row = conn.execute("SELECT id FROM artifacts WHERE path = ?", (str(Path(path).expanduser()),)).fetchone()
            artifact_id = int(row["id"]) if row is not None else None
        if artifact_id is None:
            return []
        rows = conn.execute(
            """
            SELECT row_type, action, source, target, status, detail
            FROM artifact_rows
            WHERE artifact_id = ?
            ORDER BY row_index
            LIMIT ?
            """,
            (int(artifact_id), int(limit)),
        ).fetchall()
        if rows:
            return [
                ArtifactDetailRow(
                    str(row["row_type"] or ""),
                    str(row["action"] or ""),
                    str(row["source"] or ""),
                    str(row["target"] or ""),
                    str(row["status"] or ""),
                    str(row["detail"] or ""),
                )
                for row in rows
            ]
        artifact = conn.execute("SELECT path FROM artifacts WHERE id = ?", (int(artifact_id),)).fetchone()
    finally:
        conn.close()
    if parse_fallback and artifact is not None:
        return artifact_detail_rows_from_file(Path(artifact["path"]), limit=limit)
    return []


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


def default_artifact_search_paths(
    db_path: Path = DEFAULT_DB_PATH,
    report_paths: list[Path] | None = None,
    library_path: str | Path | None = None,
) -> list[Path]:
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
                row = conn.execute("SELECT value FROM scan_meta WHERE key = 'last_scan_root'").fetchone()
                root = str(row["value"] or "") if row is not None else ""
            finally:
                conn.close()
        except sqlite3.Error:
            root = ""
    if root and root != "PATH":
        root_path = Path(root).expanduser()
        candidates.extend([root_path / "reports", root_path.parent / "reports"])

    candidates.append(Path.home() / "reports")
    return [path for path in _dedupe_paths(candidates) if path.exists()]
