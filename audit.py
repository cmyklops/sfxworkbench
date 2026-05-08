#!/usr/bin/env python3
"""
wavwarden phase0 audit — read-only library health report.

No external dependencies. Safe to point at any path; makes no changes.

Usage:
    python audit.py /path/to/library
    python audit.py ~/CommercialLibraries --output-dir ~/reports
    python audit.py /Volumes/Sandisk --no-hash
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import unicodedata
import wave
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".w64", ".rf64"}

# UCS: first segment is 2–5 uppercase letters (category), second is 2–8 uppercase letters (subcategory)
_UCS_RE = re.compile(r"^[A-Z]{2,5}_[A-Z]{2,8}(_|$)")

# Characters that are illegal on Windows/exFAT (breaks cross-platform portability)
_ILLEGAL_CHARS = set(':*?"<>|')
# Characters that cause issues in shells, URLs, or some DAWs even on macOS
_RISKY_CHARS = set("#&;'\\!")
# Max safe byte length for a single path component (APFS/HFS+ limit is 255 bytes UTF-8)
_MAX_NAME_BYTES = 255
# Warn when a full absolute path exceeds this (Windows MAX_PATH default)
_MAX_PATH_BYTES = 260


def _looks_ucs(name: str) -> bool:
    return bool(_UCS_RE.match(Path(name).stem))


def _check_filename_health(path: Path, root: Path) -> list[dict]:
    """
    Return a list of issue dicts for this path. Each issue has:
      - file: str (absolute path)
      - component: str (the specific filename or folder name that has the problem)
      - issue: str (short machine-readable tag)
      - detail: str (human-readable explanation)

    Checks performed on every component of the path relative to root:
      1. unicode_normalization — name is NFD; rsync will silently skip it on APFS (NFC)
      2. illegal_chars        — contains characters illegal on Windows/exFAT (:*?"<>|)
      3. risky_chars          — contains characters that break shells or some DAWs (#&;\\'!)
      4. name_too_long        — component exceeds 255 UTF-8 bytes (APFS/HFS+ limit)
      5. path_too_long        — full absolute path exceeds 260 bytes (Windows MAX_PATH)
      6. non_ascii            — contains non-ASCII characters (informational; not always a problem)
      7. leading_trailing_space — name starts or ends with a space (breaks some tools)
      8. dot_prefix           — name starts with a dot (hidden on macOS/Linux; can surprise users)
    """
    issues = []
    abs_str = str(path)

    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts

    for component in rel_parts:
        file_str = abs_str

        # 1. Unicode normalization: NFD names are invisible to rsync on APFS
        nfc = unicodedata.normalize("NFC", component)
        if component != nfc:
            issues.append({
                "file": file_str,
                "component": component,
                "issue": "unicode_normalization",
                "detail": (
                    f"Name is NFD-normalized. rsync will silently skip this path "
                    f"when copying to APFS. Use `ditto` or normalize names first. "
                    f"NFC form: {nfc!r}"
                ),
            })

        # 2. Illegal characters (Windows/exFAT)
        found_illegal = sorted(_ILLEGAL_CHARS & set(component))
        if found_illegal:
            issues.append({
                "file": file_str,
                "component": component,
                "issue": "illegal_chars",
                "detail": f"Contains characters illegal on Windows/exFAT: {found_illegal}",
            })

        # 3. Risky characters (shells, DAWs, URLs)
        found_risky = sorted(_RISKY_CHARS & set(component))
        if found_risky:
            issues.append({
                "file": file_str,
                "component": component,
                "issue": "risky_chars",
                "detail": f"Contains characters that may break shells or DAW imports: {found_risky}",
            })

        # 4. Component byte length
        name_bytes = len(component.encode("utf-8"))
        if name_bytes > _MAX_NAME_BYTES:
            issues.append({
                "file": file_str,
                "component": component,
                "issue": "name_too_long",
                "detail": f"Component is {name_bytes} UTF-8 bytes; APFS limit is {_MAX_NAME_BYTES}.",
            })

        # 6. Non-ASCII (informational — flag but don't treat as blocking)
        if any(ord(c) > 127 for c in component):
            issues.append({
                "file": file_str,
                "component": component,
                "issue": "non_ascii",
                "detail": "Contains non-ASCII characters. May cause issues on non-Unicode filesystems.",
            })

        # 7. Leading/trailing spaces
        if component != component.strip():
            issues.append({
                "file": file_str,
                "component": component,
                "issue": "leading_trailing_space",
                "detail": "Name starts or ends with a space. Breaks many tools and shells.",
            })

        # 8. Dot-prefixed (hidden files)
        if component.startswith(".") and component not in (".", ".."):
            issues.append({
                "file": file_str,
                "component": component,
                "issue": "dot_prefix",
                "detail": "Name starts with a dot; file will be hidden on macOS/Linux.",
            })

    # 5. Full path byte length (check once per file)
    path_bytes = len(abs_str.encode("utf-8"))
    if path_bytes > _MAX_PATH_BYTES:
        issues.append({
            "file": abs_str,
            "component": abs_str,
            "issue": "path_too_long",
            "detail": f"Full path is {path_bytes} bytes; Windows MAX_PATH is {_MAX_PATH_BYTES}.",
        })

    return issues


def _read_wav_info(path: Path) -> dict:
    info = {
        "sample_rate": None,
        "bit_depth": None,
        "channels": None,
        "duration_s": None,
        "has_bext": False,
        "has_ixml": False,
        "error": None,
    }
    try:
        with wave.open(str(path), "rb") as w:
            info["sample_rate"] = w.getframerate()
            info["bit_depth"] = w.getsampwidth() * 8
            info["channels"] = w.getnchannels()
            frames = w.getnframes()
            if info["sample_rate"] > 0:
                info["duration_s"] = round(frames / info["sample_rate"], 3)
    except Exception as e:
        info["error"] = str(e)
        return info

    # Walk RIFF chunks to detect bext and iXML
    try:
        with open(path, "rb") as f:
            header = f.read(12)
            if len(header) < 12:
                return info
            riff_id, _, wave_id = struct.unpack_from("<4sI4s", header)
            if riff_id not in (b"RIFF", b"RF64") or wave_id != b"WAVE":
                return info
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                chunk_id, chunk_size = struct.unpack_from("<4sI", hdr)
                tag = chunk_id.decode("latin-1").rstrip("\x00").strip()
                if tag == "bext":
                    info["has_bext"] = True
                elif tag == "iXML":
                    info["has_ixml"] = True
                f.seek(chunk_size + (chunk_size % 2), 1)
    except Exception:
        pass

    return info


def _file_hash(path: Path, block: int = 65536) -> str | None:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _folder_depth(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return 0


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


# ---------------------------------------------------------------------------
# Core audit
# ---------------------------------------------------------------------------

def run_audit(root: Path, skip_hash: bool = False) -> dict:
    root = root.resolve()

    report = {
        "root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_files": 0,
        "total_audio_files": 0,
        "total_size_bytes": 0,
        "extensions": {},
        "sample_rates": {},
        "bit_depths": {},
        "channel_counts": {},
        "has_bext": 0,
        "has_ixml": 0,
        "metadata_present": 0,
        "ucs_named": 0,
        "non_ucs_named": 0,
        "corrupt_or_unreadable": 0,
        "errors": [],
        "folder_depth_distribution": {},
        "max_folder_depth": 0,
        "duplicate_groups": [],
        "total_duplicate_copies": 0,
        # Filename health
        "filename_issues_by_type": {},
        "filename_issues_total": 0,
        "filename_issues": [],          # full list for JSON; capped in Markdown
    }

    size_groups: dict[int, list[Path]] = defaultdict(list)
    seen_components: set[str] = set()   # avoid re-checking the same folder name twice

    print("  Pass 1/2 — crawling files...", flush=True)
    audio_files: list[tuple[Path, int]] = []

    for f in root.rglob("*"):
        if not f.is_file():
            continue
        report["total_files"] += 1
        try:
            size = f.stat().st_size
        except OSError:
            continue
        report["total_size_bytes"] += size

        depth = _folder_depth(f, root)
        key = str(depth)
        report["folder_depth_distribution"][key] = report["folder_depth_distribution"].get(key, 0) + 1
        report["max_folder_depth"] = max(report["max_folder_depth"], depth)

        ext = f.suffix.lower()
        report["extensions"][ext] = report["extensions"].get(ext, 0) + 1

        # Filename health check (run on every file path)
        issues = _check_filename_health(f, root)
        for iss in issues:
            # De-duplicate: same component + same issue only reported once
            dedup_key = f"{iss['component']}|{iss['issue']}"
            if dedup_key not in seen_components:
                seen_components.add(dedup_key)
                report["filename_issues"].append(iss)
                report["filename_issues_total"] += 1
                t = iss["issue"]
                report["filename_issues_by_type"][t] = report["filename_issues_by_type"].get(t, 0) + 1

        if ext not in AUDIO_EXTENSIONS:
            continue

        report["total_audio_files"] += 1
        audio_files.append((f, size))

        if _looks_ucs(f.name):
            report["ucs_named"] += 1
        else:
            report["non_ucs_named"] += 1

        if not skip_hash:
            size_groups[size].append(f)

    print(f"  Found {report['total_audio_files']:,} audio files ({report['total_files']:,} total).", flush=True)
    print("  Pass 2/2 — reading metadata...", flush=True)

    for i, (f, _) in enumerate(audio_files):
        if i % 500 == 0 and i > 0:
            print(f"    {i:,}/{report['total_audio_files']:,}...", flush=True)

        ext = f.suffix.lower()
        if ext not in (".wav", ".aif", ".aiff"):
            continue

        info = _read_wav_info(f)
        if info["error"]:
            report["corrupt_or_unreadable"] += 1
            report["errors"].append({"file": str(f), "error": info["error"]})
            continue

        for field, key_map in (
            ("sample_rate", report["sample_rates"]),
            ("bit_depth", report["bit_depths"]),
            ("channels", report["channel_counts"]),
        ):
            val = info[field]
            if val is not None:
                k = str(val)
                key_map[k] = key_map.get(k, 0) + 1

        if info["has_bext"]:
            report["has_bext"] += 1
        if info["has_ixml"]:
            report["has_ixml"] += 1
        if info["has_bext"] or info["has_ixml"]:
            report["metadata_present"] += 1

    # Duplicate detection: group by size, then hash within groups
    if not skip_hash:
        print("  Finding duplicates...", flush=True)
        for size, paths in size_groups.items():
            if len(paths) < 2:
                continue
            hash_groups: dict[str, list[str]] = defaultdict(list)
            for p in paths:
                h = _file_hash(p)
                if h:
                    hash_groups[h].append(str(p))
            for h, group in hash_groups.items():
                if len(group) > 1:
                    report["duplicate_groups"].append({"hash": h, "size_bytes": size, "files": group})
                    report["total_duplicate_copies"] += len(group) - 1

    return report


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(r: dict) -> str:
    lines: list[str] = []
    a = lines.append

    a("# wavwarden — Phase 0 Library Audit")
    a(f"\n**Path:** `{r['root']}`  ")
    a(f"**Generated:** {r['generated_at']}")

    a("\n## Summary")
    a("| Metric | Value |")
    a("|--------|-------|")
    a(f"| Total files | {r['total_files']:,} |")
    a(f"| Audio files | {r['total_audio_files']:,} |")
    a(f"| Total size | {_fmt_bytes(r['total_size_bytes'])} |")
    a(f"| Unreadable / corrupt | {r['corrupt_or_unreadable']:,} |")
    a(f"| Exact duplicate copies | {r['total_duplicate_copies']:,} |")
    a(f"| Max folder depth | {r['max_folder_depth']} |")
    a(f"| Filename issues | {r['filename_issues_total']:,} |")

    wav_total = r["total_audio_files"]
    if wav_total > 0:
        meta_pct = 100 * r["metadata_present"] / wav_total
        ucs_pct = 100 * r["ucs_named"] / wav_total
        a(f"| With metadata (bext/iXML) | {r['metadata_present']:,} ({meta_pct:.1f}%) |")
        a(f"| UCS-named | {r['ucs_named']:,} ({ucs_pct:.1f}%) |")

    if r["extensions"]:
        a("\n## File Types")
        a("| Extension | Count |")
        a("|-----------|-------|")
        for ext, count in sorted(r["extensions"].items(), key=lambda x: -x[1]):
            a(f"| `{ext or '(none)'}` | {count:,} |")

    if r["sample_rates"]:
        a("\n## Sample Rates (WAV/AIFF)")
        a("| Hz | Count |")
        a("|----|-------|")
        for sr, count in sorted(r["sample_rates"].items(), key=lambda x: -x[1]):
            a(f"| {int(sr):,} | {count:,} |")

    if r["bit_depths"]:
        a("\n## Bit Depths (WAV/AIFF)")
        a("| Bit depth | Count |")
        a("|-----------|-------|")
        for bd, count in sorted(r["bit_depths"].items(), key=lambda x: -x[1]):
            a(f"| {bd}-bit | {count:,} |")

    if r["channel_counts"]:
        a("\n## Channel Layout (WAV/AIFF)")
        a("| Layout | Count |")
        a("|--------|-------|")
        for ch, count in sorted(r["channel_counts"].items(), key=lambda x: int(x[0])):
            label = {1: "Mono", 2: "Stereo"}.get(int(ch), f"{ch}-ch")
            a(f"| {label} | {count:,} |")

    if r["folder_depth_distribution"]:
        a("\n## Folder Depth Distribution")
        a("| Depth | Files |")
        a("|-------|-------|")
        for depth in sorted(r["folder_depth_distribution"], key=int):
            a(f"| {depth} | {r['folder_depth_distribution'][depth]:,} |")

    # --- Filename health ---
    fn_issues = r.get("filename_issues", [])
    fn_by_type = r.get("filename_issues_by_type", {})
    if fn_issues:
        a(f"\n## Filename Health — {r['filename_issues_total']:,} issues")

        # Severity order for display
        _SEVERITY = {
            "unicode_normalization": ("🔴 Critical", "rsync silently skips these; files will NOT transfer"),
            "illegal_chars":         ("🔴 Critical", "illegal on Windows/exFAT; breaks portability"),
            "name_too_long":         ("🔴 Critical", "exceeds filesystem name limit (255 bytes)"),
            "path_too_long":         ("🟠 Warning",  "exceeds Windows MAX_PATH (260 bytes)"),
            "risky_chars":           ("🟠 Warning",  "may break shells or DAW imports"),
            "leading_trailing_space":("🟠 Warning",  "breaks many tools and shells"),
            "non_ascii":             ("🟡 Info",     "may cause issues on non-Unicode filesystems"),
            "dot_prefix":            ("🟡 Info",     "hidden on macOS/Linux"),
        }

        a("\n### Summary by issue type")
        a("| Severity | Issue | Count | Impact |")
        a("|----------|-------|-------|--------|")
        for issue_type, count in sorted(fn_by_type.items(), key=lambda x: list(_SEVERITY).index(x[0]) if x[0] in _SEVERITY else 99):
            sev, impact = _SEVERITY.get(issue_type, ("🟡 Info", ""))
            a(f"| {sev} | `{issue_type}` | {count:,} | {impact} |")

        # Group issues by type for the detail listing
        by_type: dict[str, list[dict]] = defaultdict(list)
        for iss in fn_issues:
            by_type[iss["issue"]].append(iss)

        for issue_type in _SEVERITY:
            group = by_type.get(issue_type, [])
            if not group:
                continue
            sev, _ = _SEVERITY[issue_type]
            a(f"\n### {sev} — `{issue_type}` ({len(group):,})")
            shown = group[:20]
            for iss in shown:
                a(f"- `{iss['component']}` — {iss['detail']}")
            if len(group) > 20:
                a(f"\n_…{len(group) - 20} more in JSON report._")

    dup_groups = r["duplicate_groups"]
    if dup_groups:
        a(f"\n## Duplicates — {len(dup_groups)} groups, {r['total_duplicate_copies']:,} extra copies")
        for i, grp in enumerate(dup_groups[:25], 1):
            a(f"\n**Group {i}** — {_fmt_bytes(grp['size_bytes'])}, {len(grp['files'])} copies")
            for fp in grp["files"]:
                a(f"- `{fp}`")
        if len(dup_groups) > 25:
            a(f"\n_…{len(dup_groups) - 25} more groups in JSON report._")

    errors = r["errors"]
    if errors:
        a(f"\n## Unreadable Files — {len(errors)}")
        for err in errors[:50]:
            a(f"- `{err['file']}` — {err['error']}")
        if len(errors) > 50:
            a(f"\n_…{len(errors) - 50} more in JSON report._")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="wavwarden phase0: read-only audit of a sound library.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python audit.py ~/CommercialLibraries
  python audit.py /Volumes/Sandisk/CommercialLibraries --output-dir ~/reports
  python audit.py /big/library --no-hash   # skip MD5, faster, no dupe detection
""",
    )
    parser.add_argument("path", help="Root path of the library to audit")
    parser.add_argument("--output-dir", default=".", metavar="DIR", help="Where to write reports (default: .)")
    parser.add_argument("--no-hash", action="store_true", help="Skip MD5 hashing (faster; disables duplicate detection)")
    args = parser.parse_args()

    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"Error: path not found: {root}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nwavwarden phase0 audit")
    print(f"Root: {root}\n")

    stats = run_audit(root, skip_hash=args.no_hash)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"audit_{ts}.json"
    md_path = output_dir / f"audit_{ts}.md"

    with open(json_path, "w") as f:
        json.dump(stats, f, indent=2)

    md = render_markdown(stats)
    with open(md_path, "w") as f:
        f.write(md)

    print()
    print(md)
    print(f"\nReports saved:")
    print(f"  {json_path}")
    print(f"  {md_path}")


if __name__ == "__main__":
    main()
