#!/usr/bin/env python3
"""Benchmark sfxworkbench scan behavior on a full or sampled library.

By default this creates a temporary symlink mirror for the first N audio files,
so large-library timing can be measured without indexing the entire collection.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from sfxworkbench import junk
from sfxworkbench.scan import scan_library


def collect_audio_files(root: Path, limit: int | None) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if junk.is_inside_junk_dir(path) or junk.is_junk_file(path):
            continue
        if path.suffix.lower() in junk.AUDIO_EXTENSIONS:
            files.append(path)
            if limit is not None and len(files) >= limit:
                break
    return files


def make_symlink_sample(root: Path, files: list[Path], sample_root: Path) -> None:
    for source in files:
        rel = source.relative_to(root)
        target = sample_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark sfxworkbench scan on a library or sampled subset.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--limit", type=int, default=None, help="Sample the first N audio files via symlink mirror.")
    parser.add_argument("--db", type=Path, default=None, help="Optional DB path. Defaults to a temp DB.")
    parser.add_argument("--no-hash", action="store_true", help="Skip MD5 hashing during benchmark.")
    parser.add_argument("--repeat", type=int, default=1, help="Number of scan runs.")
    args = parser.parse_args()

    root = args.path.resolve()
    if not root.exists():
        parser.error(f"path not found: {root}")

    files = collect_audio_files(root, args.limit)
    with tempfile.TemporaryDirectory(prefix="sfxworkbench-bench-") as tmp:
        tmp_path = Path(tmp)
        scan_root = root
        if args.limit is not None:
            scan_root = tmp_path / "sample"
            scan_root.mkdir()
            make_symlink_sample(root, files, scan_root)

        db_path = args.db or (tmp_path / "bench.db")
        runs = []
        for _ in range(args.repeat):
            start = time.perf_counter()
            result = scan_library(scan_root, db_path=db_path, skip_hash=args.no_hash, force_rescan=True, quiet=True)
            elapsed_s = time.perf_counter() - start
            runs.append(
                {
                    "elapsed_s": round(elapsed_s, 3),
                    "files_per_second": round(result.total / elapsed_s, 2) if elapsed_s else None,
                    "result": result.model_dump(),
                }
            )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "bench_scan",
                    "source_root": str(root),
                    "scan_root": str(scan_root),
                    "db_path": str(db_path),
                    "limit": args.limit,
                    "sampled_files": len(files),
                    "skip_hash": args.no_hash,
                    "runs": runs,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
