# wavwarden

Sound library hygiene tools. Phase 0: read-only audit. See plan for full roadmap.

## Phase 0 — Audit

Crawls a library path and produces a JSON + Markdown report covering:

- File counts by extension, sample rate, bit depth, channel layout
- BWAV/iXML metadata presence rate
- UCS naming compliance (heuristic)
- Folder depth distribution
- Exact duplicate detection (filename + size + MD5)
- Unreadable / corrupt files

No external dependencies. Read-only; makes no changes.

**Requirements:** Python 3.10+

### Usage

```bash
python audit.py ~/CommercialLibraries
python audit.py /Volumes/Sandisk/CommercialLibraries --output-dir ~/reports
python audit.py /big/library --no-hash   # skip MD5 hashing, faster
```

Reports are written to `./audit_YYYYMMDD_HHMMSS.{json,md}` (or `--output-dir`).

## Roadmap

| Phase | Description |
|-------|-------------|
| 0 | ✅ Read-only audit + report |
| 1 | CLI engine: scan index (SQLite), full-text search, dedupe |
| 2 | Cleanup: UCS rename, metadata write from filename/CSV |
| 3 | GUI shell (Tauri) for non-technical users |
