# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
# Install (requires uv; creates .venv with Python 3.11)
uv pip install -e ".[dev]"
uv pip install -e ".[metadata,dev]"   # optional wavinfo-backed metadata reads

# Run all tests
uv run pytest tests/ -v
uv run --extra dev poe check
uv run --extra dev poe json-smoke

# Run a single test file or test
uv run pytest tests/test_clean.py -v
uv run pytest tests/test_health.py::test_unicode_normalization_detected -v

# Run the sfx CLI
uv run sfx --help
uv run sfx clean ~/CommercialLibraries           # dry-run
uv run sfx clean ~/CommercialLibraries --apply   # actually remove junk
uv run sfx scan ~/CommercialLibraries --db ~/.wavwarden/index.db
uv run sfx scan-errors --db ~/.wavwarden/index.db --output ~/reports/scan_error_plan.json
uv run sfx scan-errors --apply ~/reports/scan_error_plan.json --db ~/.wavwarden/index.db
uv run sfx dedupe --db ~/.wavwarden/index.db --summary-only
uv run sfx dedupe --db ~/.wavwarden/index.db --output ~/reports/dedupe_plan.json
uv run sfx dedupe --review ~/reports/dedupe_plan.json --approve-all
uv run sfx dedupe --apply ~/reports/dedupe_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx packs audit ~/CommercialLibraries --db ~/.wavwarden/index.db --output ~/reports/pack_overlap_report.json
uv run sfx organize audit ~/CommercialLibraries --depth 1 --output ~/reports/organize_report.json
uv run sfx organize review ~/reports/organize_report.json --approve-all
uv run sfx organize apply ~/reports/organize_report.json --db ~/.wavwarden/index.db --require-reviewed --log organize_log.json
uv run sfx organize undo organize_log.json --db ~/.wavwarden/index.db --apply
uv run sfx search "gunshot exterior"
uv run sfx rename ~/CommercialLibraries --pattern ucs                   # dry-run
uv run sfx rename ~/CommercialLibraries --pattern safe                  # dry-run
uv run sfx rename ~/CommercialLibraries --pattern ucs --apply --log rename_log.json
uv run sfx rename ~/CommercialLibraries --pattern safe --apply --allow-partial --log safe_rename_log.json

# Run the standalone Phase 0 auditor (no install required, Python 3.9+)
python3 audit.py ~/CommercialLibraries --output-dir ~/reports
python3 audit.py ~/CommercialLibraries --no-hash   # skip MD5

# Developer benchmark
uv run --extra dev poe bench-scan --files 1000 --no-hash
```

## Architecture

Two parallel layers that don't depend on each other:

**`audit.py`** — standalone zero-dependency Phase 0 auditor. Uses only stdlib (no soundfile, no Typer). Runs on Python 3.9+. Do not import from the `wavwarden` package here and do not break it.

**`wavwarden/` package** — Phase 1+ CLI engine. Requires Python 3.10+, installed via uv. Entry point is `sfx` → `wavwarden/cli.py`. All commands lazy-import their module (e.g. `from wavwarden.clean import clean_library`) to keep startup fast.

### Data flow

```
sfx scan PATH  →  audio.read_audio_info()  →  SQLite (files + files_fts)
                  health.check_path()      →  SQLite (fn_issues)
                  MD5 hash                 →  SQLite (files.md5)

sfx scan-errors → classify scan_error rows → review/quarantine obvious artifacts
sfx dedupe     →  GROUP BY md5 WHERE count > 1  →  summary or reviewed plan JSON
sfx dedupe --review PLAN → approve groups
sfx dedupe --apply PLAN → validate size/hash → quarantine duplicates + update SQLite
sfx packs audit PATH → folder hash signatures + overlap candidates → report JSON
sfx organize audit/review/apply/undo PATH → folder-structure cleanup with undo log
sfx rename PATH → preview/apply UCS-oriented or safe names → rename_log_TIMESTAMP.json
sfx audit      →  SELECT queries against index
sfx search Q   →  FTS5 MATCH query on files_fts
```

### Key modules

- **`db.py`** — single source of truth for schema. `get_connection(db_path)` creates the DB, applies schema idempotently, enables WAL mode and foreign keys. Default DB: `~/.wavwarden/index.db`.
- **`audio.py`** — wraps `soundfile` (libsndfile). Handles 32-bit float WAV, RF64, W64, AIFF, FLAC. Falls back gracefully if soundfile isn't installed. Also does a manual RIFF chunk walk to detect `bext` and `iXML` chunks, since soundfile doesn't expose those.
- **`health.py`** — extracted verbatim from `audit.py`. 8 filename checks; returns `list[FilenameIssue]`. Used by both `sfx scan` (written to `fn_issues` table) and `audit.py` (inline in report).
- **`clean.py`** — `find_junk()` returns `(junk_files, junk_dirs)`. AppleDouble files (`._*`) bypass the audio-extension safety guard since they're always metadata blobs regardless of apparent extension.
- **`scan.py`** — incremental: skips files where `mtime + size_bytes` match the existing DB row. Junk detection uses shared `junk.py`; junk files are never indexed.
- **`scan_errors.py`** — plans quarantine for unreadable indexed files. Only all-zero blobs and AppleDouble artifacts are auto-marked `quarantine`; broken RIFF files stay `review`.
- **`dedupe.py`** — exact MD5 duplicate grouping. Writes versioned JSON plans and quarantines by default on apply.
- **`packs.py`** — report-only pack/folder duplicate detection. Computes recursive folder signatures from indexed MD5 hashes and reports exact duplicate folders plus high-overlap pack candidates.
- **`organize.py`** — folder organization preview/review/apply/undo. Starts with conservative top-level numeric sort-prefix removal and reuses the rename engine for apply.
- **`rename.py`** — UCS-oriented and safe filename/path rename preview/apply/undo. Refuses collisions and updates SQLite paths after apply.
- **`ucs.py`** — shared UCS-looking filename heuristic/parser. This is not a full official UCS catalog validator yet.

### Critical design constraints

- **Every destructive command defaults to dry-run, quarantine, or undoable behavior.** `clean --apply`, `dedupe --apply`, and `rename --apply` are the commands that modify the filesystem.
- **`soundfile` over stdlib `wave`.** The stdlib `wave` module can't read 32-bit float WAV, which is the default format for modern field recorders (Sound Devices, Zoom F-series). Using stdlib wave produces ~30% false-positive "unreadable" counts on real libraries.
- **Junk patterns live in one place:** `junk.py`. If you add a new junk pattern, add it there and cover it in tests.
- **UCS naming heuristic**: `^[A-Z]{2,5}_[A-Z]{2,8}(_|$)` matched against the file stem. This is a heuristic, not a full UCS validator.
- **FTS5 sync is handled by three SQL triggers** in `db.py` (`files_ai`, `files_au`, `files_ad`). Don't do manual FTS inserts — let the triggers fire.

### SQLite schema (key tables)

| Table | Purpose |
|-------|---------|
| `files` | One row per indexed audio file; all metadata + audio properties |
| `files_fts` | FTS5 virtual table over `filename` + `stem`; kept in sync via triggers |
| `fn_issues` | Filename health issues linked to `files.id`; replaced on each rescan |
| `scan_meta` | Key-value store: `last_scan_root`, `last_scan_at` |

### Tests

Fixtures in `tests/conftest.py`:
- `tmp_library(tmp_path)` — builds a fake library tree with valid WAVs, AppleDouble files, `.DS_Store`, `_wfCache/`, `__MACOSX/`, `.reapeaks`, a file with `:` in the name, and an NFD-encoded filename.
- `tmp_db(tmp_path)` — returns path to a fresh initialized SQLite DB.

## Roadmap

Full phase spec: `docs/PHASES.md`. Current status:
- **Phase 0** ✅ — `audit.py` standalone auditor
- **Phase 1** ✅ — `sfx` CLI package (clean, scan, dedupe, audit, search, export, JSON output)
- **Phase 2** 🔜 — metadata writing (`sfx tag`); `sfx rename` is now the first cleanup feature
- **Pack/folder duplicate detection** 🔜 — `sfx packs audit` report is implemented; reviewed plan/apply workflow for duplicated or overlapping commercial packs remains next
- **Phase 3** ⬜ — Textual TUI first, Tauri later

Additional planning docs:
- `docs/UCS.md` — UCS catalog/import strategy; do not vendor official UCS data until redistribution terms are verified.
- `docs/METADATA_TAGGING.md` — metadata write plan and audio-listening suggestion roadmap.
- `docs/PACK_DEDUPLICATION.md` — pack/folder duplicate detection and consolidation plan.
