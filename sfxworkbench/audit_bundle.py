"""Integrated read-only audit bundle for TUI/GUI workflows."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sfxworkbench import __version__
from sfxworkbench.audit_cmd import run_audit
from sfxworkbench.dedupe import find_duplicates, summarize_duplicates
from sfxworkbench.format_audit import build_format_audit_report, write_format_audit_report
from sfxworkbench.groups import audit_related_groups, write_related_groups_report
from sfxworkbench.metadata_audit import build_metadata_audit_report, write_metadata_audit_report
from sfxworkbench.models import AuditBundleReport, AuditBundleSummary
from sfxworkbench.packs import audit_packs, write_pack_audit_report
from sfxworkbench.scan import scan_library
from sfxworkbench.ucs_validate import build_ucs_validation_report, write_ucs_validation_report
from sfxworkbench.utils import atomic_write_text, json_dumps

ProgressCallback = Callable[[str, int, int | None, str], None]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_report_name(root: Path) -> str:
    stem = root.expanduser().resolve().name or "library"
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in stem).strip("_") or "library"


def default_audit_bundle_dir(root: Path) -> Path:
    """Return a timestamped report folder for an integrated audit run."""
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return Path.home() / "reports" / f"sfxworkbench_audit_{_safe_report_name(root)}_{stamp}"


def _write_json(path: Path, payload: object) -> None:
    if hasattr(payload, "model_dump"):
        atomic_write_text(path, json_dumps(payload))
    else:
        atomic_write_text(path, json.dumps(payload, indent=2))


def build_audit_bundle(
    root: Path,
    *,
    db_path: Path,
    output_dir: Path | None = None,
    skip_hash: bool = False,
    force_rescan: bool = False,
    include_similarity: bool = False,
    quiet: bool = True,
    limit: int = 200,
    progress_callback: ProgressCallback | None = None,
) -> AuditBundleReport:
    """Refresh the index and write a core read-only audit bundle.

    Similarity is intentionally not run here yet. It remains an explicit,
    slower review workflow, but the flag is recorded for future compatibility.
    """
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    output = output_dir.expanduser() if output_dir is not None else default_audit_bundle_dir(root)
    output.mkdir(parents=True, exist_ok=True)

    report_paths: dict[str, str] = {}
    errors: list[dict] = []
    step = 0
    total_steps = 8

    def advance(message: str) -> None:
        nonlocal step
        step += 1
        if progress_callback is not None:
            progress_callback("auditing", step, total_steps, message)

    if progress_callback is not None:
        progress_callback("scanning", 0, None, "Scanning library for audit bundle")
    scan_result = scan_library(
        root,
        db_path,
        skip_hash=skip_hash,
        force_rescan=force_rescan,
        quiet=quiet,
        mode="full",
        progress_callback=progress_callback,
    )
    scan_path = output / "scan_result.json"
    _write_json(scan_path, scan_result)
    report_paths["scan"] = str(scan_path)
    advance("Wrote scan result")

    audit = run_audit(db_path, quiet=True)
    audit_path = output / "index_audit.json"
    _write_json(audit_path, audit)
    report_paths["index_audit"] = str(audit_path)
    advance("Wrote index audit")

    metadata = build_metadata_audit_report(db_path, limit=limit)
    metadata_path = output / "metadata_audit.json"
    write_metadata_audit_report(metadata, metadata_path, quiet=True)
    report_paths["metadata_audit"] = str(metadata_path)
    advance("Wrote metadata audit")

    duplicates = find_duplicates(db_path, ensure_hash=not skip_hash, root=root)
    duplicate_summary = summarize_duplicates(duplicates)
    duplicates_path = output / "dedupe_summary.json"
    _write_json(
        duplicates_path,
        {
            "schema_version": 1,
            "generated_at": _now_iso(),
            "tool": "sfxworkbench",
            "tool_version": __version__,
            "db_path": str(db_path),
            "summary": duplicate_summary.model_dump(),
            "groups": [group.model_dump() for group in duplicates[: limit or None]],
        },
    )
    report_paths["dedupe_summary"] = str(duplicates_path)
    advance("Wrote duplicate summary")

    groups = audit_related_groups(root, db_path=db_path, limit=limit)
    groups_path = output / "related_groups_report.json"
    write_related_groups_report(groups, groups_path, quiet=True)
    report_paths["related_groups"] = str(groups_path)
    advance("Wrote related-groups report")

    format_report = build_format_audit_report(root, db_path=db_path, limit=limit)
    format_path = output / "format_audit.json"
    write_format_audit_report(format_report, format_path, quiet=True)
    report_paths["format_audit"] = str(format_path)
    advance("Wrote format audit")

    packs = audit_packs(root, db_path=db_path, ensure_hash=not skip_hash)
    packs_path = output / "pack_overlap_report.json"
    write_pack_audit_report(packs, packs_path, quiet=True)
    report_paths["pack_overlap"] = str(packs_path)
    advance("Wrote pack overlap report")

    ucs_matches = 0
    ucs_misses = 0
    try:
        ucs = build_ucs_validation_report(db_path, root=root, limit=limit)
    except ValueError as e:
        errors.append({"workflow": "ucs_validation", "error": str(e)})
    else:
        ucs_matches = ucs.summary.catalog_matches
        ucs_misses = ucs.summary.catalog_misses
        ucs_path = output / "ucs_validation.json"
        write_ucs_validation_report(ucs, ucs_path, quiet=True)
        report_paths["ucs_validation"] = str(ucs_path)
    advance("Wrote UCS validation status")

    summary = AuditBundleSummary(
        total_files=audit.total_files,
        scan_errors=audit.scan_errors,
        filename_issues=audit.fn_issues_total,
        missing_metadata=audit.missing_metadata,
        unusual_sample_rate_files=metadata.summary.unusual_sample_rate_files,
        duplicate_groups=duplicate_summary.duplicate_groups,
        duplicate_files=duplicate_summary.duplicate_files,
        related_groups=groups.summary.candidate_groups,
        format_inconsistent_groups=format_report.summary.inconsistent_groups,
        pack_exact_duplicate_groups=packs.summary.exact_duplicate_groups,
        pack_overlap_candidates=packs.summary.overlap_candidates,
        ucs_catalog_matches=ucs_matches,
        ucs_catalog_misses=ucs_misses,
        reports_written=len(report_paths),
        errors=len(errors),
    )
    bundle = AuditBundleReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        root=str(root),
        db_path=str(db_path),
        output_dir=str(output),
        include_similarity=include_similarity,
        report_paths=report_paths,
        summary=summary,
        audit=audit,
        errors=errors,
    )
    bundle_path = output / "audit_bundle.json"
    if progress_callback is not None:
        progress_callback("writing_report", 0, None, f"Writing audit bundle to {bundle_path.name}")
    _write_json(bundle_path, bundle)
    bundle.report_paths["audit_bundle"] = str(bundle_path)
    bundle.summary.reports_written = len(bundle.report_paths)
    _write_json(bundle_path, bundle)
    if progress_callback is not None:
        progress_callback("complete", total_steps, total_steps, "Audit bundle complete")
    return bundle
