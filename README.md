# wavwarden

Sound library hygiene tools — audit, deduplicate, rename, and safely transfer
commercial sound libraries. Designed to work alongside free browsers like Soundly
or SoundQ for daily search; wavwarden handles the cleanup work they don't do.

See [`docs/PHASES.md`](docs/PHASES.md) for the full architecture, design principles,
and per-phase command reference.

---

## Phase 0 — Audit (available now)

`audit.py` is a single-file, no-dependency read-only auditor. Point it at any path;
it makes no changes.

**What it reports**

| Section | Details |
|---------|---------|
| Summary | File counts, total size, problem counts at a glance |
| File types | Extension breakdown |
| Sample rates / bit depths / channels | Format distribution across WAV/AIFF |
| Metadata presence | % of files with BWAV bext or iXML chunks |
| UCS naming | % of files following UCS naming conventions |
| **Filename health** | NFD/NFC normalization issues, illegal chars, path length, risky chars |
| Folder depth | Hierarchy depth distribution |
| Duplicates | Exact-match groups by size + MD5 |
| Unreadable files | Files that fail to open or have header errors |

**Filename health checks** catch problems before they cause data loss during transfers:

| Severity | Issue | Example |
|----------|-------|---------|
| 🔴 Critical | NFD Unicode names — rsync silently skips these on APFS | `Nikkö/`, `Argonautica - Kemençe…` |
| 🔴 Critical | Illegal characters on Windows/exFAT | `file: name.wav` |
| 🔴 Critical | Name exceeds 255 UTF-8 bytes | Very long filenames |
| 🟠 Warning | Path exceeds 260 bytes (Windows MAX_PATH) | Deep hierarchies |
| 🟠 Warning | Risky shell/DAW characters | `file#1.wav`, `it's a sound.wav` |
| 🟡 Info | Non-ASCII characters | Accented letters, symbols |

**Requirements:** Python 3.9+, no external packages.

### Usage

```bash
# Basic audit — crawl a path, write JSON + Markdown reports
python audit.py ~/CommercialLibraries

# Write reports to a specific folder
python audit.py /Volumes/Sandisk/CommercialLibraries --output-dir ~/reports

# Skip MD5 hashing (faster; disables duplicate detection)
python audit.py /big/library --no-hash
```

Reports are written as `audit_YYYYMMDD_HHMMSS.json` and `.md` in the output directory
(default: current directory). The Markdown report is also printed to stdout.

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 0 — Audit | ✅ Done | Read-only audit script with filename health checks |
| 1 — CLI engine | 🔜 Next | `sfx` CLI: `import`, `preflight`, `scan`, `audit`, `dedupe`, `search` |
| 2 — Cleanup | ⬜ Planned | `sfx rename`, `sfx tag`, `sfx normalize`, `sfx categorize` |
| 3 — GUI shell | ⬜ Planned | Tauri desktop app: Import Wizard, Health Dashboard, Duplicate Review |
| 4 — Future | ⬜ Ideas | AI categorization, watch folders, NAS support |

Full details, command specs, and design rationale: [`docs/PHASES.md`](docs/PHASES.md)
