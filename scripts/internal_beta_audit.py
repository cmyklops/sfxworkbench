#!/usr/bin/env python3
"""Run a report-only Internal Studio Beta audit workflow."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from wavwarden.audit_cmd import run_audit
from wavwarden.groups import audit_related_groups, write_related_groups_report
from wavwarden.metadata_audit import build_metadata_audit_report, write_metadata_audit_report
from wavwarden.packs import apply_pack_plan, audit_packs, build_pack_plan, write_pack_audit_report
from wavwarden.scan import scan_library
from wavwarden.utils import json_dumps


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(payload) + "\n")


def run_internal_beta_audit(
    root: Path,
    output_dir: Path,
    db_path: Path | None = None,
    skip_hash: bool = False,
    force_rescan: bool = True,
    limit: int = 200,
    include_format: bool = False,
) -> dict:
    """Run the beta-safe audit path and return a manifest of generated artifacts."""
    root = root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if db_path is None:
        db_path = output_dir / "index.db"
    else:
        db_path = db_path.expanduser().resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    scan_result = scan_library(root, db_path=db_path, skip_hash=skip_hash, force_rescan=force_rescan, quiet=True)
    scan_path = output_dir / "scan_result.json"
    _write_json(
        scan_path,
        {
            "schema_version": 1,
            "command": "scan",
            "root": root,
            "db_path": db_path,
            "skip_hash": skip_hash,
            "force_rescan": force_rescan,
            "result": scan_result,
        },
    )

    audit_result = run_audit(db_path, quiet=True)
    audit_path = output_dir / "audit_result.json"
    _write_json(
        audit_path,
        {
            "schema_version": 1,
            "command": "audit",
            "db_path": db_path,
            "result": audit_result,
        },
    )

    metadata_report = build_metadata_audit_report(db_path, limit=limit)
    metadata_path = output_dir / "metadata_report.json"
    write_metadata_audit_report(metadata_report, metadata_path, quiet=True)

    groups_report = audit_related_groups(root, db_path=db_path, limit=limit)
    groups_path = output_dir / "related_groups_report.json"
    write_related_groups_report(groups_report, groups_path, quiet=True)

    format_report = None
    format_path = None
    if include_format:
        from wavwarden.format_audit import build_format_audit_report, write_format_audit_report

        format_report = build_format_audit_report(root, db_path=db_path, limit=limit)
        format_path = output_dir / "format_report.json"
        write_format_audit_report(format_report, format_path, quiet=True)

    pack_report = audit_packs(root, db_path=db_path)
    pack_report_path = output_dir / "pack_overlap_report.json"
    write_pack_audit_report(pack_report, pack_report_path, quiet=True)

    pack_plan_path = output_dir / "pack_consolidation_plan.json"
    pack_plan = build_pack_plan(pack_report_path, output_path=pack_plan_path, quiet=True)

    pack_apply_dry_run = apply_pack_plan(
        pack_plan_path, db_path=db_path, dry_run=True, require_reviewed=False, quiet=True
    )
    pack_apply_path = output_dir / "pack_apply_dry_run.json"
    _write_json(
        pack_apply_path,
        {
            "schema_version": 1,
            "command": "packs_apply_dry_run",
            "plan_path": pack_plan_path,
            "result": pack_apply_dry_run,
        },
    )

    manifest = {
        "schema_version": 1,
        "command": "internal_beta_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": root,
        "output_dir": output_dir,
        "db_path": db_path,
        "skip_hash": skip_hash,
        "force_rescan": force_rescan,
        "include_format": include_format,
        "artifacts": {
            "scan_result": scan_path,
            "audit_result": audit_path,
            "metadata_report": metadata_path,
            "related_groups_report": groups_path,
            "pack_overlap_report": pack_report_path,
            "pack_consolidation_plan": pack_plan_path,
            "pack_apply_dry_run": pack_apply_path,
        },
        "summary": {
            "scan": scan_result,
            "audit": audit_result,
            "metadata": metadata_report.summary,
            "related_groups": groups_report.summary,
            "packs": pack_report.summary,
            "pack_plan": pack_plan.summary,
            "pack_apply_dry_run": pack_apply_dry_run,
        },
    }
    if format_report is not None and format_path is not None:
        manifest["artifacts"]["format_report"] = format_path
        manifest["summary"]["format"] = format_report.summary
    manifest_path = output_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    manifest["artifacts"]["manifest"] = manifest_path
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run wavwarden's report-only Internal Studio Beta audit workflow.")
    parser.add_argument("path", type=Path, help="Root path of the sound library to audit.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated JSON reports. Defaults to ./wavwarden_internal_beta_audit_TIMESTAMP.",
    )
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path. Defaults to OUTPUT_DIR/index.db.")
    parser.add_argument("--no-hash", action="store_true", help="Skip MD5 hashing. Pack reports will be less useful.")
    parser.add_argument("--incremental", action="store_true", help="Use incremental scan instead of force rescan.")
    parser.add_argument("--limit", type=int, default=200, help="Maximum rows/groups per report section; 0 writes all.")
    parser.add_argument(
        "--include-format",
        action="store_true",
        help="Also run the advanced mixed-format report. Skipped by default because mixed formats are often intentional.",
    )
    args = parser.parse_args()

    root = args.path.expanduser()
    if not root.exists():
        parser.error(f"path not found: {root}")
    if args.limit < 0:
        parser.error("--limit must be >= 0")

    output_dir = args.output_dir or Path(f"wavwarden_internal_beta_audit_{_now_stamp()}")
    manifest = run_internal_beta_audit(
        root,
        output_dir=output_dir,
        db_path=args.db,
        skip_hash=args.no_hash,
        force_rescan=not args.incremental,
        limit=args.limit,
        include_format=args.include_format,
    )
    print(json_dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
