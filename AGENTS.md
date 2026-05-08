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
uv run pytest tests/test_similarity.py tests/test_internal_beta_audit.py -v

# Run the sfx CLI
uv run sfx --help
uv run sfx clean ~/CommercialLibraries           # dry-run
uv run sfx clean ~/CommercialLibraries --apply   # actually remove junk
uv run sfx scan ~/CommercialLibraries --db ~/.wavwarden/index.db
uv run sfx metadata audit --db ~/.wavwarden/index.db --output ~/reports/metadata_report.json
uv run sfx metadata backends --json
uv run sfx metadata backends --bwfmetaedit /path/to/bwfmetaedit --json
uv run sfx groups audit ~/CommercialLibraries --db ~/.wavwarden/index.db --output ~/reports/related_groups_report.json
uv run sfx format audit ~/CommercialLibraries --db ~/.wavwarden/index.db --output ~/reports/format_report.json
uv run sfx scan-errors --db ~/.wavwarden/index.db --output ~/reports/scan_error_plan.json
uv run sfx scan-errors --apply ~/reports/scan_error_plan.json --db ~/.wavwarden/index.db
uv run sfx dedupe --db ~/.wavwarden/index.db --summary-only
uv run sfx dedupe --db ~/.wavwarden/index.db --output ~/reports/dedupe_plan.json
uv run sfx dedupe --review ~/reports/dedupe_plan.json --approve-all
uv run sfx dedupe --apply ~/reports/dedupe_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx packs audit ~/CommercialLibraries --db ~/.wavwarden/index.db --output ~/reports/pack_overlap_report.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --output ~/reports/pack_consolidation_plan.json
uv run sfx packs review ~/reports/pack_consolidation_plan.json --approve-all
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx packs undo pack_quarantine_log.json --db ~/.wavwarden/index.db --apply
uv run sfx similarity crawl ~/CommercialLibraries --db ~/.wavwarden/index.db --cache ~/.wavwarden/similarity
uv run sfx similarity segments ~/CommercialLibraries --db ~/.wavwarden/index.db --limit 200 --json
uv run sfx similarity search --file query.wav --db ~/.wavwarden/index.db --limit 20 --json
uv run sfx similarity search --file query.wav --db ~/.wavwarden/index.db --scope segment --limit 20 --json
uv run sfx similarity audit ~/CommercialLibraries --db ~/.wavwarden/index.db --threshold 0.92 --output ~/reports/similarity_audit.json
uv run sfx similarity audit ~/CommercialLibraries --db ~/.wavwarden/index.db --scope segment --threshold 0.95 --json
uv run sfx similarity feedback set --left one.wav --right two.wav --state ignored --db ~/.wavwarden/index.db
uv run sfx similarity feedback list --db ~/.wavwarden/index.db --state ignored --json
uv run sfx similarity feedback clear --left one.wav --right two.wav --db ~/.wavwarden/index.db
uv run sfx organize audit ~/CommercialLibraries --depth 1 --output ~/reports/organize_report.json
uv run sfx organize audit ~/CommercialLibraries --pattern redundant-nesting --depth 8 --output ~/reports/nesting_report.json
uv run sfx organize nesting-plan ~/reports/nesting_report.json --output ~/reports/nesting_plan.json
uv run sfx organize nesting-plan ~/reports/nesting_report.json --kind single_child_chain --output ~/reports/single_child_plan.json
uv run sfx organize nesting-plan ~/reports/nesting_report.json --kind low_value_wrapper --output ~/reports/wrapper_plan.json
uv run sfx organize review ~/reports/nesting_plan.json --approve-all
uv run sfx organize nesting-apply ~/reports/nesting_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx organize nesting-apply ~/reports/nesting_plan.json --db ~/.wavwarden/index.db --apply --require-reviewed --log nesting_log.json
uv run sfx organize nesting-undo nesting_log.json --db ~/.wavwarden/index.db --apply
uv run sfx organize review ~/reports/organize_report.json --approve-all
uv run sfx organize apply ~/reports/organize_report.json --db ~/.wavwarden/index.db --require-reviewed --log organize_log.json
uv run sfx organize undo organize_log.json --db ~/.wavwarden/index.db --apply
uv run sfx organize audit ~/CommercialLibraries --pattern vendor-product-folders --output ~/reports/vendor_folders.json
uv run sfx search "gunshot exterior"
uv run sfx rename ~/CommercialLibraries --pattern ucs                   # dry-run
uv run sfx rename ~/CommercialLibraries --pattern safe                  # dry-run
uv run sfx rename ~/CommercialLibraries --pattern portable              # dry-run
uv run sfx rename ~/CommercialLibraries --pattern ucs --apply --log rename_log.json
uv run sfx rename ~/CommercialLibraries --pattern safe --apply --allow-partial --log safe_rename_log.json
uv run sfx rename ~/CommercialLibraries --pattern portable --apply --log portable_rename_log.json
uv run sfx rename --undo rename_log.json --apply
uv run sfx tag suggest ~/CommercialLibraries --db ~/.wavwarden/index.db --output ~/reports/tag_suggestions.json
uv run sfx tag suggest ~/CommercialLibraries --db ~/.wavwarden/index.db --min-confidence 0.6 --json
uv run sfx tag suggest ~/CommercialLibraries --db ~/.wavwarden/index.db --use-ucs-catalog --min-confidence 0.8 --json
uv run sfx tag plan ~/CommercialLibraries --db ~/.wavwarden/index.db --from-suggestions ~/reports/tag_suggestions.json --output ~/reports/tag_plan.json
uv run sfx tag review ~/reports/tag_plan.json --approve-all
uv run sfx tag apply ~/reports/tag_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx tag apply ~/reports/tag_plan.json --db ~/.wavwarden/index.db --require-reviewed --apply --log ~/reports/tag_apply_log.json
uv run sfx tag sidecar-export ~/reports/accepted_tags.sidecar.json --db ~/.wavwarden/index.db --path ~/CommercialLibraries
uv run sfx tag sidecar-import ~/reports/accepted_tags.sidecar.json --db ~/.wavwarden/index.db
uv run sfx tag sidecar-import ~/reports/accepted_tags.sidecar.json --db ~/.wavwarden/index.db --apply
uv run sfx metadata write-plan ~/reports/metadata_write_plan.json --db ~/.wavwarden/index.db --path ~/CommercialLibraries --bwfmetaedit /path/to/bwfmetaedit
uv run sfx metadata write-review ~/reports/metadata_write_plan.json --approve-all
uv run sfx metadata write-preview ~/reports/metadata_write_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx ucs import ~/Desktop/_categorylist.csv --release-version v8.2.1
uv run sfx ucs info
uv run sfx ucs categories --cat-short AMB
uv run sfx ucs validate ~/CommercialLibraries --db ~/.wavwarden/index.db --json
uv run sfx organize audit ~/CommercialLibraries --pattern common-prefix-folders --output ~/reports/common_prefix_folders.json
uv run sfx organize audit ~/CommercialLibraries --pattern numeric-series-folders --output ~/reports/numeric_series_folders.json

# Run the standalone Phase 0 auditor (no install required, Python 3.9+)
python3 audit.py ~/CommercialLibraries --output-dir ~/reports
python3 audit.py ~/CommercialLibraries --no-hash   # skip MD5

# Developer benchmark
uv run --extra dev poe bench-scan --files 1000 --no-hash
uv run --extra dev poe beta-audit ~/CommercialLibraries --output-dir ~/reports/wavwarden_beta_audit --include-similarity
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

sfx metadata audit → list missing BWF/iXML metadata and unusual sample-rate files
sfx metadata backends → report installed external metadata write backends, no audio mutation
sfx metadata write-plan/review/preview → reviewed dry-run embedded metadata write plans, no audio mutation
sfx groups audit PATH → infer numbered takes and channel sets → report JSON
sfx format audit PATH → flag mixed sample rate / bit depth / channels inside related groups
sfx scan-errors → classify scan_error rows → review/quarantine obvious artifacts
sfx dedupe     →  GROUP BY md5 WHERE count > 1  →  summary or reviewed plan JSON
sfx dedupe --review PLAN → approve groups
sfx dedupe --apply PLAN → validate size/hash → quarantine duplicates + update SQLite
sfx packs audit PATH → folder hash signatures + overlap candidates → report JSON
sfx packs plan/review/apply/undo → reviewed pack/folder quarantine workflow with undo log
sfx similarity crawl PATH → optional audio descriptor + segment cache
sfx similarity segments PATH → list cached event windows
sfx similarity search --file QUERY → whole-file or segment nearest-neighbor search
sfx similarity audit PATH → report-only whole-file or segment near-duplicate groups
sfx similarity feedback set/list/clear → DB-only favorite/hidden/ignored/accepted/rejected review states
sfx organize audit/review/apply/undo PATH → folder-structure cleanup with undo log
sfx organize audit --pattern common-prefix-folders PATH → reviewed sibling family re-foldering preview
sfx organize audit --pattern numeric-series-folders PATH → reviewed numeric library-series re-foldering preview
sfx organize audit --pattern vendor-product-folders PATH → reviewed vendor/product re-foldering preview
sfx organize audit --pattern redundant-nesting PATH → report-only nested-folder review
sfx organize nesting-plan/apply/undo → reviewed repeated-folder, non-generic single-child, and strict leaf-wrapper flatten workflow
sfx rename PATH → preview/apply UCS-oriented, safe, or portable names → rename_log_TIMESTAMP.json
sfx tag suggest PATH → report-only tag suggestions from filename/path/group evidence (Phase B)
sfx tag plan/review/apply → reviewed DB-only accepted tag writes with apply log
sfx tag sidecar-export/import → portable JSON sidecars for accepted DB-only tags
sfx ucs import SOURCE → parse Soundminer/_categorylist.csv → ~/.wavwarden/ucs_catalog.json
sfx ucs info → show provenance and entry count of the loaded UCS catalog
sfx ucs categories [--category | --cat-short] → list/filter UCS entries
sfx audit      →  SELECT queries against index
sfx search Q   →  FTS5 MATCH query on files_fts
```

### Key modules

- **`db.py`** — single source of truth for schema. `get_connection(db_path)` creates the DB, applies schema idempotently, enables WAL mode and foreign keys. Default DB: `~/.wavwarden/index.db`.
- **`audio.py`** — wraps `soundfile` (libsndfile). Handles 32-bit float WAV, RF64, W64, AIFF, FLAC. Falls back gracefully if soundfile isn't installed. Also does a manual RIFF chunk walk to detect `bext` and `iXML` chunks, since soundfile doesn't expose those.
- **`health.py`** — extracted verbatim from `audit.py`. 8 filename checks; returns `list[FilenameIssue]`. Used by both `sfx scan` (written to `fn_issues` table) and `audit.py` (inline in report).
- **`clean.py`** — `find_junk()` returns `(junk_files, junk_dirs)`. AppleDouble files (`._*`) bypass the audio-extension safety guard since they're always metadata blobs regardless of apparent extension.
- **`scan.py`** — incremental: skips files where `mtime + size_bytes` match the existing DB row. Junk detection uses shared `junk.py`; junk files are never indexed.
- **`metadata_audit.py`** — report-only metadata coverage and unusual sample-rate audit for planning future tagging work.
- **`metadata_backends.py`** — report-only discovery for future embedded metadata writer backends. Probes BWF MetaEdit path/version and records capability shape without mutating audio.
- **`metadata_write.py`** — reviewed dry-run embedded metadata write plans. Consumes DB-only `accepted_tags`, maps conservative BWF MetaEdit fields, stamps review status, and previews anchor validation plus simulated BWF MetaEdit commands without mutating audio.
- **`groups.py`** — report-only related sound group detection from indexed filename patterns.
- **`format_audit.py`** — report-only format consistency audit inside related groups. It never converts audio.
- **`scan_errors.py`** — plans quarantine for unreadable indexed files. Only all-zero blobs and AppleDouble artifacts are auto-marked `quarantine`; broken RIFF files stay `review`.
- **`dedupe.py`** — exact MD5 duplicate grouping. Writes versioned JSON plans and quarantines by default on apply.
- **`packs.py`** — report-only pack/folder duplicate detection. Computes recursive folder signatures from indexed MD5 hashes and reports exact duplicate folders plus high-overlap pack candidates.
- **`organize.py`** — folder organization preview/review/apply/undo. Conservative numeric sort-prefix removal reuses the rename engine for apply; repeated-folder nesting and non-generic one-child chains have reviewed plan/apply/undo; generic wrappers remain report-only.
- **`rename.py`** — UCS-oriented, safe, and portable filename/path rename preview/apply/undo. Refuses collisions and updates SQLite paths after apply.
- **`tag_suggest.py`** — Phase B report-only tag suggestions. Pure suggestor: composes UCS stem parsing, optional UCS catalog matches, filename heuristics (abbreviation expansion, take-number extraction), parent-folder evidence, and related-group membership into versioned JSON suggestion plans. No filesystem or DB writes.
- **`tag_plan.py`** — reviewed metadata-writing workflow. Builds tag plans from suggestions, stamps review state, validates file anchors, and writes approved entries to SQLite `accepted_tags`; it does not mutate audio files.
- **`tag_sidecar.py`** — portable JSON sidecar export/import for DB-only accepted tags. Import validates indexed path, size, mtime, MD5, and file existence before writing.
- **`ucs_catalog.py`** — UCS catalog import, cache, and lookup. Parses the official `Soundminer/_categorylist.csv` from `UCS Release.zip`, writes a normalized JSON cache at `~/.wavwarden/ucs_catalog.json` with provenance (source URL, release version, import timestamp, attribution). Discovery chain for `load_catalog()`: explicit path → `WAVWARDEN_UCS_DATA` env var → default cache → `None`. XLSX import is deferred.
- **`ucs_validate.py`** — report-only validation of UCS-looking indexed filenames against a loaded UCS catalog.
- **`ucs.py`** — shared UCS-looking filename heuristic/parser. This is not a full official UCS catalog validator yet.
- **`similarity.py`** — optional deterministic audio descriptor crawler, cached event segment detection, whole-file/segment similarity search, report-only similarity audit, and DB-only review feedback. It never mutates audio or makes cleanup decisions.

### Critical design constraints

- **Every destructive command defaults to dry-run, quarantine, review-first, or undoable behavior.** Filesystem-changing commands include `clean --apply`, `dedupe --apply`, `scan-errors --apply`, `packs apply --apply`, `packs undo --apply`, `rename --apply`, `rename --undo --apply`, `organize apply`, and `organize nesting-apply --apply`.
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
| `analysis_runs` | Similarity/audio-analysis run metadata |
| `audio_descriptors` | Cached deterministic per-file audio descriptors |
| `audio_segments` | Cached event-like segment windows and per-segment descriptors |
| `similarity_feedback` | DB-only review states for similarity relationships |
| `accepted_tags` | DB-only accepted metadata tags from reviewed tag plans |
| `tag_apply_log` | Immutable DB record of tag apply attempts/results |

### Tests

Fixtures in `tests/conftest.py`:
- `tmp_library(tmp_path)` — builds a fake library tree with valid WAVs, AppleDouble files, `.DS_Store`, `_wfCache/`, `__MACOSX/`, `.reapeaks`, a file with `:` in the name, and an NFD-encoded filename.
- `tmp_db(tmp_path)` — returns path to a fresh initialized SQLite DB.

## Roadmap

Full phase spec: `docs/PHASES.md`. Current status:
- **Phase 0** ✅ — `audit.py` standalone auditor
- **Phase 1** ✅ — `sfx` CLI package (clean, scan, dedupe, audit, search, export, JSON output)
- **Phase 2** 🔜 — embedded metadata writing; DB-only `sfx tag plan/review/apply`, tag sidecars, embedded-write dry-run plans, cleanup, rename, organize, pack review, UCS import/validate, and tag suggestions are implemented
- **Pack/folder duplicate detection** ✅ — `sfx packs audit/plan/review/apply/undo` is implemented for exact duplicate folders and fully-covered overlaps
- **Phase 3** ⬜ — Textual TUI first, Tauri later

Additional planning docs:
- `docs/UCS.md` — UCS catalog/import strategy; do not vendor official UCS data until redistribution terms are verified.
- `docs/METADATA_TAGGING.md` — metadata write plan and audio-listening suggestion roadmap.
- `docs/PACK_DEDUPLICATION.md` — pack/folder duplicate detection and consolidation plan.
