"""Shared operation actions for the TUI and future GUI."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

APPLY_LOG_DIR_NAME = "apply_logs"
_TUI_SYNONYM_LIMIT = 8
_TUI_SYNONYM_DEPTH = 0
_TUI_UCS_RELEASE_VERSION = "v8.2.1"
_TUI_DEFAULT_TAG_FIELDS = [
    "description",
    "keyword",
    "ucs_category",
    "ucs_subcategory",
    "category",
    "subcategory",
    "title",
    "comment",
    "channel_position",
]


@dataclass(frozen=True)
class ActionResult:
    action: str
    status: str
    message: str
    output_path: str | None = None
    errors: tuple[str, ...] = ()
    refresh: tuple[str, ...] = ()
    details: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "dry_run", "applied"}


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def operation_report_dir(
    db_path: Path,
    *,
    library_path: str | Path | None = None,
    report_paths: list[Path] | None = None,
) -> Path:
    """Choose the primary report directory for UI-generated artifacts."""
    for path in report_paths or []:
        expanded = path.expanduser()
        return expanded if expanded.suffix == "" else expanded.parent
    root = Path(str(library_path)).expanduser() if library_path and str(library_path) != "PATH" else None
    if root is not None:
        return root.parent / "reports"
    return db_path.expanduser().parent / "reports"


def _ensure_report_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_action_name(action: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in action.strip().lower())
    return cleaned or "action"


def _compact_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Keep action history small; full plans/reports are written separately."""
    if not details:
        return {}
    compact: dict[str, Any] = {}
    for key, value in details.items():
        if isinstance(value, str | int | float | bool) or value is None:
            compact[key] = value
        elif key in {"summary", "result"} and isinstance(value, dict):
            compact[key] = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if isinstance(nested_value, str | int | float | bool) or nested_value is None
            }
    return compact


def write_action_history(result: ActionResult, report_dir: Path) -> Path:
    """Write a compact JSON history row for every TUI action, including failures."""
    from sfxworkbench.utils import atomic_write_json

    history_dir = _ensure_report_dir(report_dir) / "action_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    output = history_dir / f"tui_action_{_now_stamp()}_{uuid4().hex[:8]}_{_safe_action_name(result.action)}.json"
    payload = {
        "schema_version": 1,
        "command": "tui_action",
        "generated_at": datetime.now(UTC).isoformat(),
        "action": result.action,
        "status": result.status,
        "message": result.message,
        "output_path": result.output_path,
        "errors": list(result.errors),
        "refresh": list(result.refresh),
        "details": _compact_details(result.details),
    }
    atomic_write_json(output, payload)
    return output


def _action_error(action: str, exc: Exception) -> ActionResult:
    return ActionResult(action=action, status="error", message=str(exc), errors=(str(exc),), refresh=("status",))


def _result_errors(result: Any) -> tuple[str, ...]:
    errors = getattr(result, "errors", []) or []
    return tuple(str(error.get("error", error)) if isinstance(error, dict) else str(error) for error in errors)


def _per_entry_plan_has_approvals(plan_path: Path) -> bool:
    """Return ``True`` if a per-entry plan (tag/embedded/delete) has any approved entries."""
    try:
        payload = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    entries = payload.get("entries") or []
    return any(isinstance(entry, dict) and entry.get("review_status") == "approved" for entry in entries)


def _group_plan_has_approvals(plan_path: Path) -> bool:
    """Return ``True`` if a group-review plan (dedupe/pack) has any approved groups."""
    try:
        payload = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    review = payload.get("review") or {}
    return bool(review.get("approved_groups"))


def _auto_approve_plan(
    plan_path: Path,
    review_fn: Callable[..., Any],
    has_approvals: Callable[[Path], bool],
) -> Exception | None:
    """Approve every entry in *plan_path* when nothing has been approved yet.

    Rolls the legacy "Approve" button into "Apply" while still respecting any
    selective review a user already made via a per-entry review screen
    (e.g. ``Metadata Review``). If at least one entry/group is already
    approved, this is a no-op so existing rejections are preserved.
    """
    if has_approvals(plan_path):
        return None
    try:
        review_fn(plan_path, approve_all=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return e
    return None


def _latest(path: Path, pattern: str) -> Path | None:
    if not path.exists():
        return None
    matches = sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _has_quarantine_entries(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    entries = payload.get("entries")
    return isinstance(entries, list) and any(
        isinstance(entry, dict) and entry.get("quarantine_path") for entry in entries
    )


def _all_quarantine_logs(report_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for directory in (report_dir / APPLY_LOG_DIR_NAME, report_dir):
        if directory.exists():
            candidates.extend(path for path in directory.glob("*.json") if _has_quarantine_entries(path))
    return sorted(set(candidates), key=lambda item: item.stat().st_mtime)


def _latest_quarantine_log(report_dir: Path) -> Path | None:
    logs = _all_quarantine_logs(report_dir)
    return logs[-1] if logs else None


def _quarantine_dirs(report_dir: Path) -> list[Path]:
    if not report_dir.exists():
        return []
    candidates: list[Path] = []
    for pattern in ("sfxworkbench*_quarantine_*", "wavwarden*_quarantine_*"):
        candidates.extend(path for path in report_dir.glob(pattern) if path.is_dir())
    return sorted(set(candidates), key=lambda item: item.stat().st_mtime, reverse=True)


def _aggregate_quarantine_entries(report_dir: Path) -> tuple[list[dict], list[Path]]:
    """Return ``(entries, source_logs)`` covering every quarantined path under *report_dir*.

    Walks every quarantine log under ``apply_logs/`` and the report root, plus
    any legacy top-level quarantine folders that no log references. Deduplicates
    by ``quarantine_path`` so a single quarantined file recorded across multiple
    logs is only counted once.
    """
    entries: list[dict] = []
    seen_paths: set[str] = set()
    source_logs: list[Path] = []
    for log_path in _all_quarantine_logs(report_dir):
        try:
            payload = json.loads(log_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        source_logs.append(log_path)
        for item in payload.get("entries", []) or []:
            if not isinstance(item, dict):
                continue
            quarantine_path = item.get("quarantine_path")
            if not isinstance(quarantine_path, str) or not quarantine_path:
                continue
            if quarantine_path in seen_paths:
                continue
            seen_paths.add(quarantine_path)
            entries.append(item)
    for legacy_dir in _quarantine_dirs(report_dir):
        legacy_str = str(legacy_dir)
        if legacy_str in seen_paths or any(
            seen.startswith(legacy_str + "/") or seen == legacy_str for seen in seen_paths
        ):
            continue
        seen_paths.add(legacy_str)
        entries.append({"quarantine_path": legacy_str, "path": None, "source": "legacy_quarantine_folder"})
    return entries, source_logs


def _write_combined_quarantine_log(report_dir: Path, entries: list[dict]) -> Path:
    from sfxworkbench.utils import atomic_write_json

    log_dir = _ensure_report_dir(report_dir) / APPLY_LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"combined_quarantine_log_{_now_stamp()}.json"
    payload = {
        "schema_version": 1,
        "command": "combined_quarantine_log",
        "generated_at": datetime.now(UTC).isoformat(),
        "entries": entries,
    }
    atomic_write_json(log_path, payload)
    return log_path


def _write_legacy_quarantine_log(report_dir: Path, quarantine_dirs: list[Path]) -> Path:
    """Back-compat shim used by tests that pre-date :func:`_aggregate_quarantine_entries`."""
    from sfxworkbench.utils import atomic_write_json

    entries = [
        {
            "quarantine_path": str(quarantine_dir),
            "path": None,
            "source": "legacy_quarantine_folder",
        }
        for quarantine_dir in quarantine_dirs
    ]
    log_dir = _ensure_report_dir(report_dir) / APPLY_LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"legacy_quarantine_log_{_now_stamp()}.json"
    payload = {
        "schema_version": 1,
        "command": "legacy_quarantine_log",
        "generated_at": datetime.now(UTC).isoformat(),
        "entries": entries,
    }
    atomic_write_json(log_path, payload)
    return log_path


def scan_action(
    root: Path,
    db_path: Path,
    *,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    from sfxworkbench.scan import scan_library

    try:
        result = scan_library(
            root,
            db_path,
            quiet=True,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("scan", e)
    cancelled = bool(cancel_requested()) if cancel_requested is not None else False
    return ActionResult(
        action="scan",
        status="cancelled" if cancelled else "ok" if result.errors == 0 else "error",
        message=(
            f"{'Stopped after indexing' if cancelled else 'Indexed'} "
            f"{result.scanned:,} file(s), skipped {result.skipped:,}, errors {result.errors:,}."
        ),
        errors=() if result.errors == 0 else (f"{result.errors:,} scan error(s)",),
        refresh=("files", "status", "reports"),
        details=result.model_dump(),
    )


def full_audit_action(
    root: Path,
    db_path: Path,
    report_dir: Path,
    *,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
) -> ActionResult:
    from sfxworkbench.audit_bundle import build_audit_bundle

    try:
        bundle = build_audit_bundle(
            root,
            db_path=db_path,
            output_dir=_ensure_report_dir(report_dir),
            quiet=True,
            progress_callback=progress_callback,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("full_audit", e)
    summary = bundle.summary
    return ActionResult(
        action="full_audit",
        status="ok" if summary.errors == 0 else "error",
        message=(
            f"Audit bundle wrote {summary.reports_written:,} report(s): "
            f"{summary.total_files:,} files, {summary.duplicate_groups:,} duplicate group(s), "
            f"{summary.missing_metadata:,} metadata gap(s)."
        ),
        output_path=bundle.output_dir,
        errors=tuple(error.get("error", str(error)) for error in bundle.errors),
        refresh=("files", "status", "reports"),
        details=bundle.model_dump(),
    )


def clean_action(
    root: Path,
    report_dir: Path,
    *,
    apply: bool = False,
    db_path: Path | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    from sfxworkbench.clean import clean_library

    action = "clean_apply" if apply else "clean_preview"
    try:
        log_path = _ensure_report_dir(report_dir) / f"clean_{'apply' if apply else 'preview'}_{_now_stamp()}.json"
        result = clean_library(
            root,
            dry_run=not apply,
            log_path=log_path,
            quiet=True,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
            db_path=db_path if apply else None,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error(action, e)
    count = len(result.removed_files) + len(result.removed_dirs)
    # Bugfix: pre-Tier 5.12 every action triggered a full tab refresh, so the
    # Clean tab repopulated after Preview/Apply. With smart invalidation the
    # ``clean`` hint is required to mark the tab dirty; apply also touches
    # the file index, so ``files`` belongs in the apply tuple.
    refresh_hints = ("clean", "files", "reports") if apply else ("clean", "reports")
    return ActionResult(
        action=action,
        status="applied" if apply else "dry_run",
        message=(
            f"{'Removed' if apply else 'Found'} {count:,} junk item(s) "
            f"({len(result.removed_files):,} files, {len(result.removed_dirs):,} dirs)."
        ),
        output_path=str(log_path),
        refresh=refresh_hints,
        details=result.model_dump(),
    )


def metadata_audit_action(db_path: Path, report_dir: Path) -> ActionResult:
    from sfxworkbench.metadata_audit import build_metadata_audit_report, write_metadata_audit_report

    try:
        report = build_metadata_audit_report(db_path)
        output = _ensure_report_dir(report_dir) / "metadata_audit.json"
        write_metadata_audit_report(report, output, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("metadata_audit", e)
    return ActionResult(
        action="metadata_audit",
        status="ok",
        message=(
            f"Metadata audit found {report.summary.missing_metadata:,} missing BEXT/iXML file(s) "
            f"and {report.summary.unusual_sample_rate_files:,} unusual sample-rate file(s)."
        ),
        output_path=str(output),
        refresh=("metadata", "reports"),
        details=report.model_dump(),
    )


def _ensure_ucs_catalog_for_suggestions(
    root: Path,
    report_dir: Path,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
) -> dict[str, Any]:
    """Load or import the UCS cache before the metadata suggestion pass."""
    from sfxworkbench.ucs_catalog import (
        default_cache_path,
        discover_import_source,
        import_catalog,
        load_catalog,
        resolve_catalog_path,
    )

    loaded = load_catalog(None)
    if loaded is not None:
        return {
            "ucs_catalog_available": True,
            "ucs_catalog_imported": False,
            "ucs_catalog_path": str(resolve_catalog_path(None) or default_cache_path()),
            "ucs_catalog_entries": loaded.provenance.entry_count,
        }

    source = discover_import_source([report_dir, root.parent, root])
    if source is None:
        return {
            "ucs_catalog_available": False,
            "ucs_catalog_imported": False,
            "ucs_catalog_path": None,
            "ucs_catalog_source": None,
        }

    if progress_callback is not None:
        progress_callback("catalog", 0, None, f"Importing UCS catalog from {source.name}...")
    result, catalog = import_catalog(
        source,
        output_path=default_cache_path(),
        release_version=_TUI_UCS_RELEASE_VERSION,
    )
    return {
        "ucs_catalog_available": True,
        "ucs_catalog_imported": True,
        "ucs_catalog_path": result.catalog_path,
        "ucs_catalog_source": result.source_path,
        "ucs_catalog_entries": catalog.provenance.entry_count,
    }


def tag_plan_action(
    root: Path,
    db_path: Path,
    report_dir: Path,
    *,
    sources: list[str] | None = None,
    fields: list[str] | None = None,
    include_synonyms: bool = False,
    min_confidence: float = 0.75,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    from sfxworkbench.tag_plan import build_tag_plan, write_tag_plan

    used_catalog = True
    catalog_details: dict[str, Any] = {}
    effective_fields = fields if fields is not None else _TUI_DEFAULT_TAG_FIELDS
    effective_min_confidence = min(min_confidence, 0.62) if include_synonyms else min_confidence
    try:
        catalog_details = _ensure_ucs_catalog_for_suggestions(root, report_dir, progress_callback)
        try:
            plan = build_tag_plan(
                root,
                db_path=db_path,
                min_confidence=effective_min_confidence,
                limit=0,
                use_ucs_catalog=True,
                include_synonyms=include_synonyms,
                synonym_limit=_TUI_SYNONYM_LIMIT if include_synonyms else 0,
                synonym_depth=_TUI_SYNONYM_DEPTH if include_synonyms else 0,
                sources=sources,
                fields=effective_fields,
                progress_callback=progress_callback,
                cancel_requested=cancel_requested,
            )
        except ValueError as catalog_error:
            if "No UCS catalog loaded" not in str(catalog_error):
                raise
            used_catalog = False
            fallback_confidence = min(effective_min_confidence, 0.55)
            plan = build_tag_plan(
                root,
                db_path=db_path,
                min_confidence=fallback_confidence,
                limit=0,
                use_ucs_catalog=False,
                include_synonyms=include_synonyms,
                synonym_limit=_TUI_SYNONYM_LIMIT if include_synonyms else 0,
                synonym_depth=_TUI_SYNONYM_DEPTH if include_synonyms else 0,
                sources=sources,
                fields=effective_fields,
                progress_callback=progress_callback,
                cancel_requested=cancel_requested,
            )
        output = _ensure_report_dir(report_dir) / "metadata_tag_plan.json"
        write_tag_plan(plan, output, quiet=True)
    except InterruptedError as e:
        return ActionResult(
            action="tag_plan",
            status="cancelled",
            message=str(e),
            errors=(str(e),),
            refresh=("metadata", "status"),
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("tag_plan", e)
    message = f"Built metadata tag plan with {plan.summary.add_entries:,} planned DB tag write(s)."
    if catalog_details.get("ucs_catalog_imported"):
        message += f" Imported UCS catalog with {catalog_details.get('ucs_catalog_entries', 0):,} entries first."
    if not used_catalog:
        message += " UCS catalog not loaded; used filename/path/group heuristics only."
    return ActionResult(
        action="tag_plan",
        status="ok",
        message=message,
        output_path=str(output),
        refresh=("metadata", "reports"),
        details={
            **plan.model_dump(),
            "used_ucs_catalog": used_catalog,
            **catalog_details,
            "fields": effective_fields,
            "include_synonyms": include_synonyms,
            "synonym_limit": _TUI_SYNONYM_LIMIT if include_synonyms else 0,
            "synonym_depth": _TUI_SYNONYM_DEPTH if include_synonyms else 0,
        },
    )


def approve_tag_plan_action(report_dir: Path) -> ActionResult:
    from sfxworkbench.tag_plan import review_tag_plan

    plan_path = report_dir / "metadata_tag_plan.json"
    if not plan_path.exists():
        return ActionResult(
            "tag_review", "error", "No metadata tag plan found.", errors=("No metadata tag plan found.",)
        )
    try:
        result = review_tag_plan(plan_path, approve_all=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("tag_review", e)
    return ActionResult(
        action="tag_review",
        status="ok",
        message=f"Approved {result.approved_entries:,} of {result.total_entries:,} metadata tag entrie(s).",
        output_path=result.output_path,
        refresh=("metadata", "reports"),
        details=result.model_dump(),
    )


def apply_tag_plan_action(
    db_path: Path,
    report_dir: Path,
    *,
    target_paths: tuple[str, ...] | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    """Apply the approved tag plan.

    ``target_paths`` (Tier 3.8): if given, only plan entries whose path is in
    this set are applied. Used by the TUI to scope an apply to the user's
    Files-tab selection.

    ``cancel_requested``: polled by the executor every ``_COMMIT_CHUNK_SIZE``
    entries. Cancellation preserves already-committed chunks; re-running the
    same plan converges via the ``ON CONFLICT … DO UPDATE`` upsert.
    """
    plan_path = report_dir / "metadata_tag_plan.json"
    if not plan_path.exists():
        return ActionResult(
            "tag_apply", "error", "No metadata tag plan found.", errors=("No metadata tag plan found.",)
        )
    from sfxworkbench.tag_plan import apply_tag_plan, review_tag_plan

    auto_approve_error = _auto_approve_plan(plan_path, review_tag_plan, _per_entry_plan_has_approvals)
    if auto_approve_error is not None:
        return _action_error("tag_apply", auto_approve_error)
    try:
        result = apply_tag_plan(
            plan_path,
            db_path=db_path,
            dry_run=False,
            require_reviewed=True,
            quiet=True,
            target_paths=target_paths,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("tag_apply", e)
    errors = _result_errors(result)
    scope_note = f" (scoped to {len(target_paths)} selected file(s))" if target_paths else ""
    cancel_note = " — cancelled mid-apply, partial commits preserved" if result.cancelled else ""
    status = "cancelled" if result.cancelled else ("applied" if not errors else "error")
    return ActionResult(
        action="tag_apply",
        status=status,
        message=f"Applied {result.applied:,} DB-only metadata tag(s), skipped {result.skipped:,}.{scope_note}{cancel_note}",
        output_path=result.log_path,
        errors=errors,
        refresh=("metadata", "files", "reports"),
        details=result.model_dump(),
    )


def export_sidecar_action(root: Path, db_path: Path, report_dir: Path) -> ActionResult:
    from sfxworkbench.tag_sidecar import build_tag_sidecar_report, write_tag_sidecar_report

    try:
        output = _ensure_report_dir(report_dir) / "accepted_tags.sidecar.json"
        report = build_tag_sidecar_report(db_path=db_path, root=root, limit=0)
        write_tag_sidecar_report(report, output, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("tag_sidecar_export", e)
    return ActionResult(
        action="tag_sidecar_export",
        status="ok",
        message=f"Exported {report.tag_count:,} accepted tag(s) for {report.entry_count:,} file(s).",
        output_path=str(output),
        refresh=("metadata", "reports"),
        details=report.model_dump(),
    )


def build_dedupe_plan_action(db_path: Path, report_dir: Path) -> ActionResult:
    from sfxworkbench.dedupe import find_duplicates, write_dedupe_plan

    try:
        groups = find_duplicates(db_path)
        output = _ensure_report_dir(report_dir) / "dedupe_plan.json"
        write_dedupe_plan(groups, output, db_path=db_path, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("dedupe_plan", e)
    return ActionResult(
        action="dedupe_plan",
        status="ok",
        message=f"Built dedupe plan with {len(groups):,} duplicate group(s).",
        output_path=str(output),
        refresh=("dedupe", "reports"),
        details={"duplicate_groups": len(groups)},
    )


def approve_dedupe_plan_action(report_dir: Path) -> ActionResult:
    from sfxworkbench.dedupe import review_dedupe_plan

    plan_path = report_dir / "dedupe_plan.json"
    if not plan_path.exists():
        return ActionResult("dedupe_review", "error", "No dedupe plan found.", errors=("No dedupe plan found.",))
    try:
        result = review_dedupe_plan(plan_path, approve_all=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("dedupe_review", e)
    return ActionResult(
        action="dedupe_review",
        status="ok",
        message=f"Approved {result.approved_groups:,} of {result.total_groups:,} duplicate group(s).",
        output_path=result.output_path,
        refresh=("dedupe", "reports"),
        details=result.model_dump(),
    )


def apply_dedupe_plan_action(
    db_path: Path,
    report_dir: Path,
    *,
    target_paths: tuple[str, ...] | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    """Apply the approved dedupe plan by quarantining duplicate files.

    ``target_paths`` (Tier 3.8): if given, only entries whose path is in this
    set are quarantined.
    """
    plan_path = report_dir / "dedupe_plan.json"
    if not plan_path.exists():
        return ActionResult("dedupe_apply", "error", "No dedupe plan found.", errors=("No dedupe plan found.",))
    from sfxworkbench.dedupe import apply_dedupe_plan, review_dedupe_plan

    auto_approve_error = _auto_approve_plan(plan_path, review_dedupe_plan, _group_plan_has_approvals)
    if auto_approve_error is not None:
        return _action_error("dedupe_apply", auto_approve_error)
    try:
        log_path = (report_dir / APPLY_LOG_DIR_NAME) / f"dedupe_quarantine_log_{_now_stamp()}.json"
        result = apply_dedupe_plan(
            plan_path,
            db_path=db_path,
            dry_run=False,
            require_reviewed=True,
            quiet=True,
            log_path=log_path,
            target_paths=target_paths,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("dedupe_apply", e)
    errors = _result_errors(result)
    cancel_note = " — cancelled mid-apply" if result.cancelled else ""
    status = "cancelled" if result.cancelled else ("applied" if not errors else "error")
    return ActionResult(
        action="dedupe_apply",
        status=status,
        message=f"Quarantined {result.quarantined:,} duplicate file(s), freed {result.bytes_freed:,} byte(s).{cancel_note}",
        output_path=result.log_path or result.quarantine_dir,
        errors=errors,
        refresh=("dedupe", "files", "reports"),
        details=result.model_dump(),
    )


def pack_audit_action(root: Path, db_path: Path, report_dir: Path) -> ActionResult:
    from sfxworkbench.packs import audit_packs, write_pack_audit_report

    try:
        report = audit_packs(root, db_path=db_path)
        output = _ensure_report_dir(report_dir) / "pack_overlap_report.json"
        write_pack_audit_report(report, output, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("pack_audit", e)
    return ActionResult(
        action="pack_audit",
        status="ok",
        message=(
            f"Pack audit found {report.summary.exact_duplicate_groups:,} exact duplicate group(s) "
            f"and {report.summary.overlap_candidates:,} overlap candidate(s)."
        ),
        output_path=str(output),
        refresh=("dedupe", "reports"),
        details=report.model_dump(),
    )


def pack_plan_action(report_dir: Path) -> ActionResult:
    report_path = report_dir / "pack_overlap_report.json"
    if not report_path.exists():
        return ActionResult(
            "pack_plan", "error", "No pack overlap report found.", errors=("No pack overlap report found.",)
        )
    from sfxworkbench.packs import build_pack_plan

    try:
        output = report_dir / "pack_consolidation_plan.json"
        plan = build_pack_plan(report_path, output_path=output, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("pack_plan", e)
    return ActionResult(
        action="pack_plan",
        status="ok",
        message=f"Built pack plan with {plan.summary.candidate_entries:,} candidate entrie(s).",
        output_path=str(output),
        refresh=("dedupe", "reports"),
        details=plan.model_dump(),
    )


def approve_pack_plan_action(report_dir: Path) -> ActionResult:
    from sfxworkbench.packs import review_pack_plan

    plan_path = report_dir / "pack_consolidation_plan.json"
    if not plan_path.exists():
        return ActionResult("pack_review", "error", "No pack plan found.", errors=("No pack plan found.",))
    try:
        result = review_pack_plan(plan_path, approve_all=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("pack_review", e)
    return ActionResult(
        action="pack_review",
        status="ok",
        message=f"Approved {result.approved_groups:,} of {result.total_groups:,} pack group(s).",
        output_path=result.output_path,
        refresh=("dedupe", "reports"),
        details=result.model_dump(),
    )


def apply_pack_plan_action(db_path: Path, report_dir: Path) -> ActionResult:
    plan_path = report_dir / "pack_consolidation_plan.json"
    if not plan_path.exists():
        return ActionResult("pack_apply", "error", "No pack plan found.", errors=("No pack plan found.",))
    from sfxworkbench.packs import apply_pack_plan, review_pack_plan

    auto_approve_error = _auto_approve_plan(plan_path, review_pack_plan, _group_plan_has_approvals)
    if auto_approve_error is not None:
        return _action_error("pack_apply", auto_approve_error)
    try:
        result = apply_pack_plan(plan_path, db_path=db_path, dry_run=False, require_reviewed=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("pack_apply", e)
    errors = _result_errors(result)
    return ActionResult(
        action="pack_apply",
        status="applied" if not errors else "error",
        message=f"Quarantined {result.quarantined:,} pack folder(s).",
        output_path=result.log_path,
        errors=errors,
        refresh=("dedupe", "files", "reports"),
        details=result.model_dump(),
    )


def rename_preview_action(root: Path, report_dir: Path, *, pattern: str = "portable") -> ActionResult:
    from sfxworkbench.rename import build_rename_plan, write_rename_log

    try:
        plan = build_rename_plan(root, pattern=pattern)
        output = _ensure_report_dir(report_dir) / f"{pattern}_rename_plan.json"
        write_rename_log(plan, output)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("rename_preview", e)
    return ActionResult(
        action="rename_preview",
        status="dry_run",
        message=f"Previewed {len(plan.entries):,} {pattern} rename(s), errors {len(plan.errors):,}.",
        output_path=str(output),
        errors=tuple(str(error.get("error", error)) for error in plan.errors),
        refresh=("clean", "reports"),
        details=plan.model_dump(),
    )


def apply_rename_action(
    db_path: Path,
    report_dir: Path,
    *,
    pattern: str = "portable",
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    plan_path = report_dir / f"{pattern}_rename_plan.json"
    if not plan_path.exists():
        return ActionResult("rename_apply", "error", "No rename plan found.", errors=("No rename plan found.",))
    from sfxworkbench.models import RenamePlan
    from sfxworkbench.rename import apply_rename_plan

    try:
        plan = RenamePlan.model_validate_json(plan_path.read_text())
        result = apply_rename_plan(
            plan,
            db_path=db_path,
            dry_run=False,
            quiet=True,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("rename_apply", e)
    errors = _result_errors(result)
    cancel_note = " — cancelled mid-apply" if result.cancelled else ""
    status = "cancelled" if result.cancelled else ("applied" if not errors else "error")
    return ActionResult(
        action="rename_apply",
        status=status,
        message=f"Renamed {result.renamed:,} path(s).{cancel_note}",
        output_path=result.log_path,
        errors=errors,
        refresh=("clean", "files", "reports"),
        details=result.model_dump(),
    )


def undo_rename_action(db_path: Path, report_dir: Path) -> ActionResult:
    log_dir = report_dir / APPLY_LOG_DIR_NAME
    log_path = _latest(log_dir, "rename_log_*.json") or _latest(report_dir, "rename_log_*.json")
    if log_path is None:
        return ActionResult("rename_undo", "error", "No rename undo log found.", errors=("No rename undo log found.",))
    from sfxworkbench.rename import undo_rename_log

    try:
        result = undo_rename_log(log_path, db_path=db_path, dry_run=False, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("rename_undo", e)
    errors = _result_errors(result)
    return ActionResult(
        action="rename_undo",
        status="applied" if not errors else "error",
        message=f"Restored {result.renamed:,} renamed path(s).",
        output_path=str(log_path),
        errors=errors,
        refresh=("clean", "files", "reports"),
        details=result.model_dump(),
    )


def organize_audit_action(root: Path, report_dir: Path, *, pattern: str = "strip-leading-numbers") -> ActionResult:
    action = "organize_nesting_audit" if pattern == "redundant-nesting" else "organize_audit"
    output_name = "redundant_nesting_report.json" if pattern == "redundant-nesting" else "organize_report.json"
    depth = 8 if pattern == "redundant-nesting" else 1
    from sfxworkbench.organize import audit_organization, write_organize_audit_report

    try:
        report = audit_organization(root, pattern=pattern, depth=depth)
        output = _ensure_report_dir(report_dir) / output_name
        write_organize_audit_report(report, output, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error(action, e)
    return ActionResult(
        action=action,
        status="ok",
        message=(
            f"Previewed {report.summary.planned:,} folder organization entrie(s), "
            f"{report.summary.candidates:,} candidate(s), errors {report.summary.errors:,}."
        ),
        output_path=str(output),
        errors=tuple(str(error.get("error", error)) for error in report.errors),
        refresh=("clean", "reports"),
        details=report.model_dump(),
    )


def approve_organize_action(report_dir: Path, *, plan_name: str = "organize_report.json") -> ActionResult:
    from sfxworkbench.organize import review_organize_report

    report_path = report_dir / plan_name
    action = "organize_nesting_review" if plan_name == "nesting_plan.json" else "organize_review"
    if not report_path.exists():
        return ActionResult(action, "error", f"No {plan_name} found.", errors=(f"No {plan_name} found.",))
    try:
        result = review_organize_report(report_path, approve_all=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error(action, e)
    return ActionResult(
        action=action,
        status="ok",
        message=f"Approved {result.approved_entries:,} of {result.total_entries:,} entrie(s).",
        output_path=result.output_path,
        refresh=("clean", "reports"),
        details=result.model_dump(),
    )


def apply_organize_action(db_path: Path, report_dir: Path) -> ActionResult:
    report_path = report_dir / "organize_report.json"
    if not report_path.exists():
        return ActionResult(
            "organize_apply", "error", "No organization report found.", errors=("No organization report found.",)
        )
    from sfxworkbench.organize import apply_organize_report, review_organize_report

    auto_approve_error = _auto_approve_plan(report_path, review_organize_report, _per_entry_plan_has_approvals)
    if auto_approve_error is not None:
        return _action_error("organize_apply", auto_approve_error)
    try:
        result = apply_organize_report(report_path, db_path=db_path, require_reviewed=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("organize_apply", e)
    errors = _result_errors(result)
    return ActionResult(
        action="organize_apply",
        status="applied" if not errors else "error",
        message=f"Applied {result.renamed:,} folder organization rename(s).",
        output_path=result.log_path,
        errors=errors,
        refresh=("clean", "files", "reports"),
        details=result.model_dump(),
    )


def undo_organize_action(db_path: Path, report_dir: Path) -> ActionResult:
    log_dir = report_dir / APPLY_LOG_DIR_NAME
    log_path = _latest(log_dir, "organize_log_*.json") or _latest(report_dir, "organize_log_*.json")
    if log_path is None:
        return ActionResult(
            "organize_undo", "error", "No organization undo log found.", errors=("No organization undo log found.",)
        )
    from sfxworkbench.organize import undo_organize_log

    try:
        result = undo_organize_log(log_path, db_path=db_path, dry_run=False, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("organize_undo", e)
    errors = _result_errors(result)
    return ActionResult(
        action="organize_undo",
        status="applied" if not errors else "error",
        message=f"Restored {result.renamed:,} folder organization rename(s).",
        output_path=str(log_path),
        errors=errors,
        refresh=("clean", "files", "reports"),
        details=result.model_dump(),
    )


def build_nesting_plan_action(report_dir: Path, *, kind: str = "repeated_folder_name") -> ActionResult:
    report_path = report_dir / "redundant_nesting_report.json"
    if not report_path.exists():
        return ActionResult(
            "organize_nesting_plan",
            "error",
            "No redundant nesting report found.",
            errors=("No redundant nesting report found.",),
        )
    from sfxworkbench.organize import build_nesting_plan_from_report

    try:
        output = _ensure_report_dir(report_dir) / "nesting_plan.json"
        plan = build_nesting_plan_from_report(report_path, kind=kind, output_path=output, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("organize_nesting_plan", e)
    return ActionResult(
        action="organize_nesting_plan",
        status="ok",
        message=f"Built nesting plan with {len(plan.entries):,} entrie(s), errors {len(plan.errors):,}.",
        output_path=str(output),
        errors=tuple(str(error.get("error", error)) for error in plan.errors),
        refresh=("clean", "reports"),
        details=plan.model_dump(),
    )


def apply_nesting_action(db_path: Path, report_dir: Path) -> ActionResult:
    plan_path = report_dir / "nesting_plan.json"
    if not plan_path.exists():
        return ActionResult(
            "organize_nesting_apply", "error", "No nesting plan found.", errors=("No nesting plan found.",)
        )
    from sfxworkbench.organize import apply_nesting_plan, review_organize_report

    auto_approve_error = _auto_approve_plan(plan_path, review_organize_report, _per_entry_plan_has_approvals)
    if auto_approve_error is not None:
        return _action_error("organize_nesting_apply", auto_approve_error)
    try:
        result = apply_nesting_plan(plan_path, db_path=db_path, require_reviewed=True, dry_run=False, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("organize_nesting_apply", e)
    errors = _result_errors(result)
    return ActionResult(
        action="organize_nesting_apply",
        status="applied" if not errors else "error",
        message=f"Flattened {result.flattened:,} nested folder(s), moved {result.moved:,} path(s).",
        output_path=result.log_path,
        errors=errors,
        refresh=("clean", "files", "reports"),
        details=result.model_dump(),
    )


def undo_nesting_action(db_path: Path, report_dir: Path) -> ActionResult:
    log_dir = report_dir / APPLY_LOG_DIR_NAME
    log_path = _latest(log_dir, "nesting_log_*.json") or _latest(report_dir, "nesting_log_*.json")
    if log_path is None:
        return ActionResult(
            "organize_nesting_undo", "error", "No nesting undo log found.", errors=("No nesting undo log found.",)
        )
    from sfxworkbench.organize import undo_nesting_log

    try:
        result = undo_nesting_log(log_path, db_path=db_path, dry_run=False, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("organize_nesting_undo", e)
    errors = _result_errors(result)
    return ActionResult(
        action="organize_nesting_undo",
        status="applied" if not errors else "error",
        message=f"Restored {result.undone:,} nested folder(s), moved {result.moved:,} path(s).",
        output_path=str(log_path),
        errors=errors,
        refresh=("clean", "files", "reports"),
        details=result.model_dump(),
    )


def apply_tag_plan_and_build_embedded_plan_action(
    db_path: Path,
    report_dir: Path,
    *,
    root: Path | None = None,
    target_paths: tuple[str, ...] | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    """Apply the tag plan to ``accepted_tags`` then build the embedded-write plan.

    Replaces the old two-button flow (Apply DB Tags → Plan Embedded Metadata).
    The DB-apply step is fast and reversible; the embedded plan step is the
    slow file-probe pass that must run before Apply Embedded Metadata. There
    is no realistic case where the user wants the first without the second,
    so they're chained here.

    If the DB apply errors or is cancelled, the slower probe step is skipped
    and the apply result is returned as-is. If the DB apply succeeds but the
    probe step fails (e.g. ``bwfmetaedit`` not installed), both messages are
    surfaced so the user knows the DB write landed.
    """
    apply_result = apply_tag_plan_action(
        db_path,
        report_dir,
        target_paths=target_paths,
        progress_callback=progress_callback,
        cancel_requested=cancel_requested,
    )
    if not apply_result.ok or apply_result.status == "cancelled":
        return apply_result
    plan_result = build_embedded_metadata_plan_action(
        root if root is not None else Path("."),
        db_path,
        report_dir,
        progress_callback=progress_callback,
        cancel_requested=cancel_requested,
    )
    merged_refresh = tuple(dict.fromkeys((*apply_result.refresh, *plan_result.refresh)))
    merged_errors = tuple(dict.fromkeys((*apply_result.errors, *plan_result.errors)))
    return ActionResult(
        action="tag_apply_and_embedded_plan",
        status=plan_result.status if plan_result.ok else "error",
        message=f"{apply_result.message} {plan_result.message}".strip(),
        output_path=plan_result.output_path or apply_result.output_path,
        errors=merged_errors,
        refresh=merged_refresh,
        details={"apply": apply_result.details, "plan": plan_result.details},
    )


def build_embedded_metadata_plan_action(
    root: Path,
    db_path: Path,
    report_dir: Path,
    *,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    from sfxworkbench.metadata_write import build_metadata_write_plan, write_metadata_write_plan

    try:
        output = _ensure_report_dir(report_dir) / "metadata_write_plan.json"
        plan = build_metadata_write_plan(
            db_path=db_path,
            root=root,
            backend="auto",
            limit=0,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("metadata_write_plan", e)
    write_metadata_write_plan(plan, output, quiet=True)
    return ActionResult(
        action="metadata_write_plan",
        status="ok" if plan.summary.supported_entries else "error",
        message=(
            f"Built embedded metadata plan with {plan.summary.candidate_entries:,} candidate entrie(s), "
            f"{plan.summary.supported_entries:,} supported, {plan.summary.unsupported_entries:,} unsupported."
        ),
        output_path=str(output),
        errors=tuple(str(error.get("error", error)) for error in plan.errors),
        refresh=("metadata", "reports"),
        details=plan.model_dump(),
    )


def approve_embedded_metadata_action(report_dir: Path) -> ActionResult:
    from sfxworkbench.metadata_write import review_metadata_write_plan

    plan_path = report_dir / "metadata_write_plan.json"
    if not plan_path.exists():
        return ActionResult(
            "metadata_write_review",
            "error",
            "No embedded metadata write plan found.",
            errors=("No embedded metadata write plan found.",),
        )
    try:
        result = review_metadata_write_plan(plan_path, approve_all=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("metadata_write_review", e)
    return ActionResult(
        action="metadata_write_review",
        status="ok",
        message=f"Approved {result.approved_entries:,} of {result.total_entries:,} embedded metadata entrie(s).",
        output_path=result.output_path,
        refresh=("metadata", "reports"),
        details=result.model_dump(),
    )


def apply_embedded_metadata_action(
    db_path: Path,
    report_dir: Path,
    *,
    target_paths: tuple[str, ...] | None = None,
    progress_callback: Callable[[str, int, int | None, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> ActionResult:
    """Apply the embedded metadata write plan.

    ``target_paths`` (Tier 3.8): scope the write to the user's selected files.
    """
    plan_path = report_dir / "metadata_write_plan.json"
    if not plan_path.exists():
        return ActionResult(
            "metadata_write_apply",
            "error",
            "No embedded metadata write plan found.",
            errors=("No embedded metadata write plan found.",),
        )
    from sfxworkbench.metadata_write import apply_metadata_write_plan, review_metadata_write_plan

    auto_approve_error = _auto_approve_plan(plan_path, review_metadata_write_plan, _per_entry_plan_has_approvals)
    if auto_approve_error is not None:
        return _action_error("metadata_write_apply", auto_approve_error)
    try:
        result = apply_metadata_write_plan(
            plan_path,
            db_path=db_path,
            require_reviewed=True,
            dry_run=False,
            quiet=True,
            target_paths=target_paths,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("metadata_write_apply", e)
    errors = _result_errors(result)
    scope_note = f" (scoped to {len(target_paths)} selected file(s))" if target_paths else ""
    cancel_note = " — cancelled mid-apply" if result.cancelled else ""
    status = "cancelled" if result.cancelled else ("applied" if not errors else "error")
    return ActionResult(
        action="metadata_write_apply",
        status=status,
        message=f"Wrote {result.applied:,} embedded metadata entrie(s) to {result.files_written:,} file(s).{scope_note}{cancel_note}",
        output_path=result.log_path,
        errors=errors,
        refresh=("metadata", "files", "reports"),
        details=result.model_dump(),
    )


def undo_embedded_metadata_action(db_path: Path, report_dir: Path) -> ActionResult:
    log_dir = report_dir / APPLY_LOG_DIR_NAME
    log_path = _latest(log_dir, "metadata_write_apply_log_*.json") or _latest(
        report_dir, "metadata_write_apply_log_*.json"
    )
    if log_path is None:
        return ActionResult(
            "metadata_write_undo",
            "error",
            "No embedded metadata write undo log found.",
            errors=("No embedded metadata write undo log found.",),
        )
    from sfxworkbench.metadata_write import undo_metadata_write_apply_log

    try:
        result = undo_metadata_write_apply_log(log_path, db_path=db_path, dry_run=False, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("metadata_write_undo", e)
    errors = _result_errors(result)
    return ActionResult(
        action="metadata_write_undo",
        status="applied" if not errors else "error",
        message=f"Restored {result.restored:,} embedded metadata backup file(s).",
        output_path=str(log_path),
        errors=errors,
        refresh=("metadata", "files", "reports"),
        details=result.model_dump(),
    )


def build_delete_plan_action(report_dir: Path) -> ActionResult:
    entries, _source_logs = _aggregate_quarantine_entries(report_dir)
    if not entries:
        return ActionResult(
            "delete_plan",
            "error",
            "No quarantine log or folder found. Apply Dedupe or Apply Pack first.",
            errors=("No quarantine log or folder found.",),
        )
    try:
        source_log = _write_combined_quarantine_log(report_dir, entries)
    except OSError as e:
        return _action_error("delete_plan", e)
    from sfxworkbench.delete import build_delete_plan, write_delete_plan
    from sfxworkbench.utils import fmt_bytes

    try:
        output = _ensure_report_dir(report_dir) / "delete_plan.json"
        plan = build_delete_plan(source_log)
        write_delete_plan(plan, output, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("delete_plan", e)
    size_note = f", {fmt_bytes(plan.summary.bytes_planned)}" if plan.summary.bytes_planned else ""
    folder_note = (
        f" across {plan.summary.directory_entries:,} quarantine folder(s)" if plan.summary.directory_entries else ""
    )
    return ActionResult(
        action="delete_plan",
        status="ok",
        message=(f"Built permanent-delete plan with {plan.summary.files_planned:,} file(s){folder_note}{size_note}."),
        output_path=str(output),
        errors=tuple(str(error.get("error", error)) for error in plan.errors),
        refresh=("files", "reports"),
        details=plan.model_dump(),
    )


def approve_delete_plan_action(report_dir: Path) -> ActionResult:
    from sfxworkbench.delete import review_delete_plan

    plan_path = report_dir / "delete_plan.json"
    if not plan_path.exists():
        return ActionResult(
            "delete_review", "error", "No permanent-delete plan found.", errors=("No delete plan found.",)
        )
    try:
        result = review_delete_plan(plan_path, approve_all=True, quiet=True)
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("delete_review", e)
    return ActionResult(
        action="delete_review",
        status="ok",
        message=f"Approved {result.approved_entries:,} of {result.total_entries:,} permanent-delete entrie(s).",
        output_path=result.output_path,
        refresh=("files", "reports"),
        details=result.model_dump(),
    )


def apply_delete_plan_action(report_dir: Path, db_path: Path | None = None) -> ActionResult:
    plan_path = report_dir / "delete_plan.json"
    if not plan_path.exists():
        return ActionResult(
            "delete_apply", "error", "No permanent-delete plan found.", errors=("No delete plan found.",)
        )
    from sfxworkbench.delete import apply_delete_plan, review_delete_plan

    auto_approve_error = _auto_approve_plan(plan_path, review_delete_plan, _per_entry_plan_has_approvals)
    if auto_approve_error is not None:
        return _action_error("delete_apply", auto_approve_error)
    try:
        result = apply_delete_plan(
            plan_path,
            db_path=db_path,
            dry_run=False,
            require_reviewed=True,
            understand_permanent_delete=True,
            quiet=True,
        )
    except Exception as e:  # pragma: no cover - defensive UI boundary
        return _action_error("delete_apply", e)
    errors = _result_errors(result)
    return ActionResult(
        action="delete_apply",
        status="applied" if not errors else "error",
        message=f"Permanently deleted {result.deleted:,} quarantine path(s), skipped {result.skipped:,}.",
        output_path=result.log_path,
        errors=errors,
        refresh=("files", "reports"),
        details=result.model_dump(),
    )
