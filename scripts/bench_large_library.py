#!/usr/bin/env python3
"""Generate a synthetic library and benchmark wavwarden scan throughput."""

from __future__ import annotations

import argparse
import json
import shutil
import time
import unicodedata
import wave
from pathlib import Path

from wavwarden.scan import scan_library


def make_tiny_wav(path: Path, sample_rate: int = 48000, channels: int = 2, nframes: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * nframes * channels * 2)


def generate_library(root: Path, files: int, dirs: int) -> dict:
    start = time.perf_counter()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    dirs = max(1, dirs)
    for i in range(files):
        folder = root / f"pack_{i % dirs:03d}" / f"sub_{(i // max(1, dirs)) % 10:02d}"
        if i % 17 == 0:
            name = f"AMB_CITY_RAIN_{i:05d}.wav"
        elif i % 29 == 0:
            name = f"bad:name_{i:05d}.wav"
        elif i % 31 == 0:
            name = unicodedata.normalize("NFD", f"café_{i:05d}.wav")
        else:
            name = f"raw recording {i:05d}.wav"
        make_tiny_wav(folder / name, sample_rate=48000 if i % 11 else 96000, channels=1 if i % 5 == 0 else 2)

        if i % 20 == 0:
            (folder / f"{name}.reapeaks").write_bytes(b"\x00" * 16)
        if i % 50 == 0:
            (folder / f"._{name}").write_bytes(b"\x00Apple\x00")

    wf_cache = root / "_wfCache"
    wf_cache.mkdir()
    (wf_cache / "cached.wav.wf").write_bytes(b"\x00" * 64)
    elapsed_s = time.perf_counter() - start
    return {"elapsed_s": round(elapsed_s, 3), "files_requested": files, "dirs_requested": dirs}


def run_scan(root: Path, db: Path, skip_hash: bool, force_rescan: bool) -> dict:
    start = time.perf_counter()
    result = scan_library(root, db_path=db, skip_hash=skip_hash, force_rescan=force_rescan, quiet=True)
    elapsed_s = time.perf_counter() - start
    return {
        "elapsed_s": round(elapsed_s, 3),
        "files_per_second": round(result.total / elapsed_s, 2) if elapsed_s else None,
        "result": result.model_dump(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark wavwarden scan on a synthetic large library.")
    parser.add_argument("--root", type=Path, default=Path("/tmp/wavwarden-bench/library"))
    parser.add_argument("--db", type=Path, default=Path("/tmp/wavwarden-bench/index.db"))
    parser.add_argument("--files", type=int, default=10_000)
    parser.add_argument("--dirs", type=int, default=100)
    parser.add_argument("--reuse", action="store_true", help="Reuse the existing synthetic library.")
    parser.add_argument("--hash", dest="skip_hash", action="store_false", help="Enable MD5 hashing.")
    parser.add_argument("--no-hash", dest="skip_hash", action="store_true", help="Skip MD5 hashing.")
    parser.set_defaults(skip_hash=True)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    generated = None
    if not args.reuse or not args.root.exists():
        generated = generate_library(args.root, files=args.files, dirs=args.dirs)

    first = run_scan(args.root, args.db, skip_hash=args.skip_hash, force_rescan=True)
    incremental = run_scan(args.root, args.db, skip_hash=args.skip_hash, force_rescan=False)
    db_size = args.db.stat().st_size if args.db.exists() else 0

    print(
        json.dumps(
            {
                "schema_version": 1,
                "command": "bench_large_library",
                "root": str(args.root),
                "db": str(args.db),
                "skip_hash": args.skip_hash,
                "generated": generated,
                "first_scan": first,
                "incremental_scan": incremental,
                "db_size_bytes": db_size,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
