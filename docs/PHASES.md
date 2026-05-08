# wavwarden — Development Phases

This document is the canonical reference for what wavwarden is, why it exists, what each
phase delivers, and how the phases connect. Update it when scope changes.

---

## Why wavwarden exists

Commercial sound library browsers (Soundly, SoundQ, Soundminer) solve the
**browse-and-drag-to-DAW** problem well. What they don't solve is **library hygiene at
scale**: auditing 2TB of files for problems, detecting true audio duplicates, migrating
to UCS naming conventions, writing metadata in bulk, and safely transferring libraries
between drives without silent data loss.

wavwarden is the librarian's toolkit that fills that gap. It is designed to be used
*alongside* a free browser (Soundly Free, SoundQ Free) for daily search/preview — not
to replace it.

**Design principles**

- Every destructive operation is dry-run by default and writes a reversible log.
- The engine is a Python CLI: scriptable, testable, runnable over SSH on a NAS.
- The GUI is a thin shell over the CLI, built later for non-technical users.
- No files are modified without explicit confirmation.
- Reports and manifests are plain JSON/Markdown — readable without the tool.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  GUI shell (Phase 3)  Tauri + web frontend  │
│  Buttons call CLI commands via subprocess   │
└─────────────────┬───────────────────────────┘
                  │ subprocess / sidecar
┌─────────────────▼───────────────────────────┐
│  CLI engine (Phases 1–2)  Python + Typer    │
│  sfx scan | audit | dedupe | import | …     │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│  SQLite + FTS5 index  (Phase 1)             │
│  All metadata, audio properties, hashes     │
└─────────────────────────────────────────────┘
```

**Tech stack**

| Layer | Library / tool | Purpose |
|-------|---------------|---------|
| CLI | `typer` + `rich` | Commands, help text, progress bars, tables |
| Data models | `pydantic` | Config, structured results |
| WAV metadata | `wavinfo` | Read iXML, BWAV bext, ADM, cue markers |
| Audio analysis | `soundfile` + `numpy` | Silence, clipping, peak, channel layout |
| Loudness | `pyloudnorm` | LUFS measurement |
| Tag writing | `mutagen` | Write ID3 tags where applicable |
| BWAV embedding | BWF MetaEdit CLI (subprocess) | Mature, faster than reimplementing |
| Fingerprinting | `chromaprint` / `fpcalc` binary | Acoustic duplicate detection |
| Index | `sqlite3` + FTS5 | Local index, full-text search |
| Tests | `pytest` | Unit + integration tests |
| Distribution | `PyInstaller` / `pipx` | CLI binaries for non-technical users |
| GUI (Phase 3) | Tauri (Rust + web frontend) | ~10 MB installers, macOS/Windows/Linux |

---

## Phase 0 — Discovery (✅ complete)

**Goal:** understand what's in the library before writing any real tooling.
No dependencies, no side effects, safe to point at the full 2TB.

**Deliverable:** `audit.py` — a single-file read-only audit script.

**Report sections**

| Section | What it tells you |
|---------|------------------|
| Summary | Total files, audio files, size, problems at a glance |
| File types | Extension breakdown — what formats are in the library |
| Sample rates | Distribution of 44.1 / 48 / 88.2 / 96 / 192 kHz files |
| Bit depths | 16 / 24 / 32-bit distribution |
| Channel layout | Mono / stereo / multi-channel counts |
| Metadata presence | % of WAV/AIFF files with BWAV bext or iXML chunks |
| UCS naming | % of files that already follow UCS naming conventions |
| Folder depth | How deep the folder hierarchy goes |
| **Filename health** | **See section below — added after Phase 0 initial run** |
| Duplicates | Exact-match groups (size + MD5); count of wasted space |
| Unreadable files | Files that fail to open or have header errors |

**Usage**

```bash
python audit.py ~/CommercialLibraries
python audit.py /Volumes/Sandisk/CommercialLibraries --output-dir ~/reports
python audit.py /big/library --no-hash   # skip MD5, no duplicate detection
```

### Filename health checks (added after initial transfer)

During the first rsync transfer from the Sandisk (exFAT) to APFS, four folders were
silently skipped due to Unicode normalization mismatches. This revealed that filename
health checks belong in Phase 0 as a baseline and in Phase 1 as a preflight step.

**Checks performed on every file and folder name:**

| Severity | Issue tag | What it catches |
|----------|-----------|----------------|
| 🔴 Critical | `unicode_normalization` | NFD-encoded names that rsync silently skips on APFS. Use `ditto` or normalize before copying. |
| 🔴 Critical | `illegal_chars` | Characters illegal on Windows/exFAT: `: * ? " < > \|` — breaks portability. |
| 🔴 Critical | `name_too_long` | Component exceeds 255 UTF-8 bytes (APFS/HFS+ hard limit). |
| 🟠 Warning | `path_too_long` | Full path exceeds 260 bytes (Windows MAX_PATH). |
| 🟠 Warning | `risky_chars` | Characters that break shells or DAW imports: `# & ; ' \ !` |
| 🟠 Warning | `leading_trailing_space` | Names starting/ending with a space. |
| 🟡 Info | `non_ascii` | Non-ASCII characters. Not always a problem, but worth knowing. |
| 🟡 Info | `dot_prefix` | Dot-prefixed names (hidden on macOS/Linux). |

**Why NFD/NFC matters:** macOS APFS normalizes filenames to NFC on write. External drives
formatted as exFAT store names as-is, which may be NFD (common in filenames with accented
characters like `é`, `ö`, `ñ`). When rsync tries to stat an NFD path on an NFC filesystem,
it returns "No such file or directory" and skips the file — silently, even with `--ignore-errors`.
The fix is to use `ditto` for affected paths (which handles normalization) or normalize
the source filenames before transferring.

---

## Phase 1 — CLI engine (next)

**Goal:** A proper CLI tool (`sfx`) that indexes the library into SQLite and exposes
the core hygiene commands. This is what you run every day and what the GUI wraps.

**New commands**

### `sfx import <src> <dest>`

Safe transfer workflow that replaces raw `rsync`:

1. Runs preflight checks (see below) and shows a plain-English summary
2. Prompts for confirmation if problems found (or `--force` to skip)
3. Runs `rsync` for the bulk transfer
4. Automatically falls back to `ditto` for any NFD-named paths rsync skips
5. Verifies transferred files with checksums
6. Writes a transfer manifest: what succeeded, what was skipped, any mismatches
7. On completion, auto-indexes new files into SQLite (`sfx scan`)

```bash
sfx import /Volumes/Sandisk/CommercialLibraries ~/CommercialLibraries
sfx import /Volumes/Sandisk/NewLibrary ~/CommercialLibraries --dest-subdir "NewLibrary"
```

### `sfx preflight <src> [--dest <dest>]`

Standalone pre-transfer check. Run this before any `rsync` or `sfx import`:

- All filename health checks from Phase 0 (NFD, illegal chars, path length, etc.)
- Estimates transfer size and file count
- Identifies files that will be skipped or broken on the destination filesystem
- Outputs a JSON manifest that `sfx import` can consume directly
- Dry-run only; makes no changes

```bash
sfx preflight /Volumes/Sandisk/NewLibrary --dest ~/CommercialLibraries
```

### `sfx scan <path>`

Crawls a path and populates the SQLite index with all metadata and audio properties.
Incremental: only re-scans files that have changed since last scan.

```bash
sfx scan ~/CommercialLibraries
sfx scan ~/CommercialLibraries/NewLibrary   # scan a subfolder only
```

### `sfx audit`

Reads from the index and reports problems:

- Missing or empty metadata (no bext, no iXML, no description)
- Silent files (below a threshold RMS)
- Clipping (peak > 0 dBFS)
- Unusual sample rates or bit depths for the collection
- Encoding errors caught during scan

```bash
sfx audit
sfx audit --only missing-metadata,clipping
sfx audit --output ~/reports/audit.md
```

### `sfx dedupe`

Find duplicates at multiple levels of confidence:

1. **Exact:** same size + MD5 hash
2. **Near-exact:** same audio hash (strips metadata, compares audio data only)
3. **Acoustic:** chromaprint fingerprint match (catches re-encoded or re-tagged copies)

Shows groups, marks extras for deletion. Dry-run by default; writes a deletion plan you
review before anything is removed.

```bash
sfx dedupe
sfx dedupe --method exact          # fast, filename+size+MD5 only
sfx dedupe --method acoustic       # slow, requires fpcalc binary
sfx dedupe --apply dedupe_plan.json  # execute a reviewed plan
```

### `sfx search <query>`

Full-text search over filenames and metadata via SQLite FTS5.

```bash
sfx search "gunshot exterior"
sfx search "AMB CITY" --format wav --sample-rate 96000
```

### `sfx export`

Get data out for spreadsheet work or external tools.

```bash
sfx export csv --output library.csv
sfx export ucs-template --output ucs_import.csv  # pre-filled UCS columns
```

---

## Phase 2 — Cleanup tooling

**Goal:** Tools that actually fix problems found in Phase 1. All destructive operations
are dry-run by default and write reversible logs.

### `sfx rename --pattern <ucs>`

Bulk rename files to UCS convention. Shows a preview table before making any changes.
Writes a rename log so every change can be undone.

```bash
sfx rename --pattern ucs --dry-run        # preview only
sfx rename --pattern ucs --apply          # execute after review
sfx rename --undo rename_log_20240501.json  # revert a rename operation
```

### `sfx tag --from-filename`

Parse UCS-named files and embed matching iXML/BWAV metadata. Useful after renaming:
once files are named correctly, metadata can be derived automatically.

```bash
sfx tag --from-filename --dry-run
sfx tag --from-filename --apply
```

### `sfx tag --from-csv <file>`

Bulk apply metadata from a spreadsheet. Common professional workflow: export library to
CSV, edit in Excel/Numbers, re-import. Validates CSV schema before writing anything.

```bash
sfx tag --from-csv metadata_edits.csv --dry-run
sfx tag --from-csv metadata_edits.csv --apply
```

### `sfx normalize`

Fix sample rate and channel layout inconsistencies.

```bash
sfx normalize --target-rate 48000 --dry-run
sfx normalize --fix-mono-as-stereo --dry-run   # fix falsely-labeled mono files
```

### `sfx categorize`

Interactive UCS category assignment. Presents unclassified files, accepts freetext,
matches against the official UCS synonym list, suggests the best category code.

```bash
sfx categorize --uncategorized-only
```

---

## Phase 3 — GUI shell

**Goal:** A Tauri desktop app that exposes the most-used CLI workflows through a clean
interface for non-technical users. The GUI calls CLI commands via subprocess — it does
not reimplement any logic.

**Why Tauri over Electron:** ~10 MB installers vs. 100 MB+, faster startup, better
security model. Frontend in React or Svelte. Produces signed installers for macOS,
Windows, and Linux.

**Screens**

### Library Health Dashboard

- Charts driven by `sfx audit` output: metadata coverage, sample rate distribution,
  problem file counts
- "Last scanned" timestamp; "Rescan" button
- Click any chart segment to drill into the file list

### Import Wizard

Replaces raw `rsync` for non-technical users:

```
[ 1. Select source drive       ]  ← folder picker
[ 2. Preflight scan  ~30 sec   ]  ← runs sfx preflight, shows plain-English summary
  ┌──────────────────────────────────────────────┐
  │  ✅ 42,180 files ready to copy               │
  │  ⚠️  4 folders — Unicode normalization issue  │
  │     (will use ditto fallback automatically)  │
  │  ⚠️  12 filenames with illegal characters     │
  │     (will rename on copy)                    │
  │  📦 Estimated: 180 GB                        │
  └──────────────────────────────────────────────┘
[ 3. Start Transfer            ]  ← runs sfx import
  [████████████░░░░] 67% — 28,341 / 42,180 files
[ 4. Complete                  ]
  42,184 files copied  •  0 errors  •  Index updated
```

### Duplicate Review

- Groups of duplicate files with waveform thumbnails side-by-side
- Click to mark keep/delete per group
- "Apply selections" runs `sfx dedupe --apply` with the reviewed plan

### Bulk Metadata Editor

- Table view: one row per file, editable cells for common metadata fields
- Multi-select rows for bulk edits
- "Write to files" runs `sfx tag --from-csv` with the edited data

### UCS Rename Wizard

- Guided flow: select files → choose/confirm UCS category → preview rename table → apply
- Designed for users who aren't familiar with UCS but want compliant naming

---

## Phase 4 — Ongoing / future

Items to build once the core is stable:

- **AI categorization:** run a local audio model to suggest UCS categories from audio
  content (not just filename). Useful for uncategorized raw recordings.
- **Watch folder:** monitor a folder for new library arrivals; auto-run `sfx import`
  and notify via Slack/Discord/email.
- **Asset tracker integration:** sync library index with an external spreadsheet or
  asset management system.
- **Auto-import on purchase:** detect new library downloads and trigger the import
  workflow.
- **NAS support:** `sfx scan` and `sfx import` already work over SSH; expose this in
  the GUI.

---

## Project hygiene

- Git repo, semantic versioning (`MAJOR.MINOR.PATCH`), `CHANGELOG.md`
- `pyproject.toml` with locked dependencies (`uv` recommended)
- GitHub Actions: run `pytest` on push; build binaries on tag
- Issues/discussions for coworker feature requests
- `docs/` folder — this file plus per-command references as they're written

---

## Open questions

- Which audio fingerprinting approach for acoustic dedupe? `fpcalc` (requires binary
  install) vs. a pure-Python approach (slower but zero-dependency). Decide in Phase 1.
- Tauri vs. a Textual TUI for the GUI. TUI is dramatically less work; worth evaluating
  whether coworkers will actually use a desktop app or are fine in a terminal.
- Self-hosted vs. cloud index: keep SQLite local, or offer a shared index for teams
  working on the same library?
