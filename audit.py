#!/usr/bin/env python3
"""Standalone zero-dependency wavwarden Phase 0 auditor.

This file intentionally does not import from the wavwarden package. It is meant
to run with only Python 3.9+ on an unprepared machine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
import wave
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".w64", ".rf64"}
ILLEGAL_CHARS = set(':*?"<>|')
RISKY_CHARS = set("#&;'\\!")
MAX_NAME_BYTES = 255
MAX_PATH_BYTES = 260
SCHEMA_VERSION = 1


def md5(path: Path, block: int = 65536) -> str | None:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def check_path(path: Path, root: Path) -> list[dict]:
    issues: list[dict] = []
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts

    for component in rel_parts:
        nfc = unicodedata.normalize("NFC", component)
        if component != nfc:
            issues.append({"component": component, "issue": "unicode_normalization", "detail": f"NFC form: {nfc!r}"})
        found_illegal = sorted(ILLEGAL_CHARS & set(component))
        if found_illegal:
            issues.append(
                {"component": component, "issue": "illegal_chars", "detail": f"Illegal characters: {found_illegal}"}
            )
        found_risky = sorted(RISKY_CHARS & set(component))
        if found_risky:
            issues.append(
                {"component": component, "issue": "risky_chars", "detail": f"Risky characters: {found_risky}"}
            )
        name_bytes = len(component.encode("utf-8"))
        if name_bytes > MAX_NAME_BYTES:
            issues.append({"component": component, "issue": "name_too_long", "detail": f"{name_bytes} UTF-8 bytes"})
        if any(ord(c) > 127 for c in component):
            issues.append({"component": component, "issue": "non_ascii", "detail": "Contains non-ASCII characters"})
        if component != component.strip():
            issues.append(
                {"component": component, "issue": "leading_trailing_space", "detail": "Starts or ends with a space"}
            )
        if component.startswith(".") and component not in (".", ".."):
            issues.append({"component": component, "issue": "dot_prefix", "detail": "Hidden dot-prefixed name"})

    path_bytes = len(str(path).encode("utf-8"))
    if path_bytes > MAX_PATH_BYTES:
        issues.append({"component": str(path), "issue": "path_too_long", "detail": f"{path_bytes} UTF-8 bytes"})
    return issues


def wav_info(path: Path) -> dict:
    if path.suffix.lower() != ".wav":
        return {}
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return {
                "sample_rate": rate,
                "bit_depth": w.getsampwidth() * 8,
                "channels": w.getnchannels(),
                "duration_s": round(frames / rate, 3) if rate else None,
            }
    except Exception as e:
        return {"error": str(e)}


def audit(root: Path, no_hash: bool = False) -> dict:
    root = root.resolve()
    files: list[dict] = []
    file_types: Counter[str] = Counter()
    sample_rates: Counter[str] = Counter()
    bit_depths: Counter[str] = Counter()
    channels: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    duplicates: dict[str, list[str]] = defaultdict(list)
    unreadable: list[dict] = []
    total_bytes = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        total_bytes += size
        ext = path.suffix.lower()
        file_types[ext or "(none)"] += 1
        issues = check_path(path, root)
        for issue in issues:
            issue_counts[issue["issue"]] += 1

        record = {"path": str(path), "size_bytes": size, "extension": ext, "filename_issues": issues}
        if ext in AUDIO_EXTENSIONS:
            info = wav_info(path)
            record.update(info)
            if "sample_rate" in info:
                sample_rates[str(info["sample_rate"])] += 1
                bit_depths[str(info["bit_depth"])] += 1
                channels[str(info["channels"])] += 1
            if "error" in info:
                unreadable.append({"path": str(path), "error": info["error"]})
            if not no_hash:
                digest = md5(path)
                record["md5"] = digest
                if digest:
                    duplicates[digest].append(str(path))
        files.append(record)

    duplicate_groups = [
        {"hash": digest, "files": paths, "count": len(paths)} for digest, paths in duplicates.items() if len(paths) > 1
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "summary": {
            "total_files": len(files),
            "audio_files": sum(1 for f in files if f["extension"] in AUDIO_EXTENSIONS),
            "total_bytes": total_bytes,
            "filename_issues": sum(issue_counts.values()),
            "duplicate_groups": len(duplicate_groups),
            "unreadable_files": len(unreadable),
        },
        "file_types": dict(file_types),
        "sample_rates": dict(sample_rates),
        "bit_depths": dict(bit_depths),
        "channels": dict(channels),
        "filename_issues": dict(issue_counts),
        "duplicate_groups": duplicate_groups,
        "unreadable_files": unreadable,
        "files": files,
    }


def markdown_report(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# wavwarden Audit Report",
        "",
        f"Root: `{report['root']}`",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Total files: {summary['total_files']:,}",
        f"- Audio files: {summary['audio_files']:,}",
        f"- Total bytes: {summary['total_bytes']:,}",
        f"- Filename issues: {summary['filename_issues']:,}",
        f"- Duplicate groups: {summary['duplicate_groups']:,}",
        f"- Unreadable files: {summary['unreadable_files']:,}",
        "",
        "## File Types",
        "",
    ]
    for ext, count in sorted(report["file_types"].items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- `{ext}`: {count:,}")
    lines.extend(["", "## Filename Issues", ""])
    if report["filename_issues"]:
        for issue, count in sorted(report["filename_issues"].items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{issue}`: {count:,}")
    else:
        lines.append("- None")
    lines.extend(["", "## Duplicate Groups", ""])
    if report["duplicate_groups"]:
        for group in report["duplicate_groups"][:25]:
            lines.append(f"- `{group['hash']}`: {group['count']} files")
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone wavwarden audit.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--no-hash", action="store_true", help="Skip MD5 hashing and duplicate detection.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    args = parser.parse_args()

    if not args.path.exists():
        parser.error(f"path not found: {args.path}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = audit(args.path, no_hash=args.no_hash)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"audit_{ts}.json"
    md_path = args.output_dir / f"audit_{ts}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md = markdown_report(report)
    md_path.write_text(md, encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
