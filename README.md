# sfxworkbench

Safety-first tools for auditing, indexing, tagging, and organizing large
sound-effects libraries.

sfxworkbench is built for commercial and personal SFX collections that have
grown hard to search: Sound Ideas, GDC/Soniss bundles, vendor packs, downloaded
freebies, field recordings, and years of mixed folders.

The project is currently a **public-readiness beta**. Start on a copied library,
review the reports, and apply changes only when the plan looks right.

## Start With The TUI

The Textual workbench is now the front door. It gives you a guided view over the
same safe CLI workflows: indexing, audits, cleanup previews, duplicate plans,
pack overlap reports, metadata/tag review, apply logs, and history.

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/cmyklops/sfxworkbench/main/scripts/install-windows-tui.ps1 | iex
```

macOS Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/cmyklops/sfxworkbench/main/scripts/install-macos-tui.sh | bash
```

Those commands install or update the GitHub checkout, sync dependencies, and
launch the TUI. After the first run:

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\sfxworkbench\scripts\run-windows-tui.ps1"
```

```bash
bash "$HOME/sfxworkbench/scripts/run-macos-tui.sh"
```

From a cloned repo:

```bash
uv sync --extra tui --extra metadata --extra dev
uv run --extra tui --extra metadata --extra dev sfx tui --db ~/.sfxworkbench/index.db --report ~/reports
```

The TUI is organized around the real work:

- **Start**: choose a library, run Quick Index, or run Smart Full Audit.
- **Scan**: inspect index health and refresh scan state.
- **Cleanup**: preview junk cleanup, rename plans, and safe apply/undo flows.
- **Dedupe**: build/review/apply exact duplicate and pack overlap plans.
- **Metadata**: audit coverage, build tag plans, review DB-only tags, and prepare
  embedded metadata writes.
- **Files**: browse indexed files and metadata evidence.
- **History**: inspect generated reports, plans, logs, previews, and TUI action
  history.

## Smart Buttons

Default buttons use **Smart** mode. Smart mode is conservative: it picks a safe
default from current state, but it does not hide scope, cache, or scan-depth
decisions.

Smart actions can:

- reuse same-library indexed data or reports when `root` and `db_path` match
- refresh missing metadata instead of rescanning everything
- hash missing files before duplicate or pack planning
- rebuild reports or plans when current data is newer
- block stale or cross-library apply plans before anything destructive happens

Generated reports, plans, and TUI action history include the library root,
SQLite DB path, action mode, timestamp, and relevant counts. The command palette
keeps explicit override paths available, including:

- Reuse Indexed Data
- Quick Index
- Refresh Metadata Only
- Full Scan / Full Audit
- Force Rescan
- Rebuild Plan or Rebuild Report

## Safety Model

sfxworkbench is designed to make file operations boring:

- preview first
- never overwrite existing files
- require explicit apply steps for filesystem changes
- prefer quarantine or undo logs over deletion
- write JSON reports, plans, and logs
- update the SQLite index after successful moves or metadata writes
- block stale, cross-root, or cross-DB destructive plans

sfxworkbench does not alter audio content. Metadata write workflows are reviewed,
backed up, readback-verified, and limited to proven embedded metadata fields.
The dual-mono workflow writes reviewed mono copies to a separate output root. The
permanent delete workflow only acts on reviewed plans built from quarantine logs.

## Common TUI Workflow

1. Open the TUI and choose a copied library folder.
2. Run **Quick Index** to populate the SQLite cache.
3. Run **Smart Full Audit** for a broad report bundle.
4. Review Cleanup, Dedupe, Metadata, Files, and History tabs.
5. Build plans from the TUI, review them, then apply only the changes you want.

The default database is:

```text
~/.sfxworkbench/index.db
```

If `--report` is omitted, the TUI looks for reports beside the DB, near the last
scanned library root, and in `~/reports`.

## CLI Quick Reference

The CLI remains the automation and power-user layer. Replace `PATH` with a
copied library folder.

```bash
# Guided first run
uv run sfx guide PATH
uv run --extra tui --extra metadata --extra dev sfx tui

# Index and audit
uv run sfx scan PATH
uv run sfx audit
uv run sfx audit-bundle PATH --output-dir ~/reports/sfxworkbench_audit
uv run sfx search "gunshot exterior"

# Junk cleanup
uv run sfx clean PATH
uv run sfx clean PATH --apply

# Exact duplicate workflow
uv run sfx dedupe --summary-only
uv run sfx dedupe --output ~/reports/dedupe_plan.json
uv run sfx dedupe --review ~/reports/dedupe_plan.json --approve-all
uv run sfx dedupe --apply ~/reports/dedupe_plan.json --require-reviewed

# Pack/folder overlap workflow
uv run sfx packs audit PATH --output ~/reports/pack_overlap_report.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --output ~/reports/pack_consolidation_plan.json
uv run sfx packs review ~/reports/pack_consolidation_plan.json --approve-all
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --require-reviewed

# Portable rename preview/apply
uv run sfx rename PATH --pattern portable
uv run sfx rename PATH --pattern portable --apply --log ~/reports/apply_logs/portable_rename_log.json
uv run sfx rename --undo ~/reports/apply_logs/portable_rename_log.json --apply

# Folder organization
uv run sfx organize audit PATH --depth 1 --output ~/reports/organize_report.json
uv run sfx organize audit PATH --pattern vendor-product-folders --output ~/reports/vendor_folders.json
uv run sfx organize review ~/reports/organize_report.json --approve-all
uv run sfx organize apply ~/reports/organize_report.json --require-reviewed --log ~/reports/apply_logs/organize_log.json
```

## Metadata And Tags

Metadata workflows are report-first. DB-only accepted tags are safe to apply to
SQLite. Embedded metadata writes require reviewed plans, backups, and readback
verification.

```bash
# Read-only metadata and tag evidence
uv run sfx metadata audit --output ~/reports/metadata_report.json
uv run sfx metadata view "FIRE_BURST_SmallBurst_6109.wav" --db ~/.sfxworkbench/index.db
uv run sfx metadata backends --json
uv run sfx tag suggest PATH --use-ucs-catalog --min-confidence 0.8 --source ucs_catalog --field ucs_category --field ucs_subcategory --output ~/reports/tag_suggestions.json
uv run sfx tag propose PATH --db ~/.sfxworkbench/index.db --min-confidence 0.6 --output ~/reports/tag_proposals.json

# Reviewed DB-only tag workflow
uv run sfx tag plan PATH --from-suggestions ~/reports/tag_suggestions.json --source ucs_catalog --field ucs_category --field ucs_subcategory --output ~/reports/tag_plan.json
uv run sfx tag summarize ~/reports/tag_plan.json --value-limit 20
uv run sfx tag review ~/reports/tag_plan.json --approve-all
uv run sfx tag apply ~/reports/tag_plan.json --require-reviewed --apply --log ~/reports/apply_logs/tag_apply_log.json
uv run sfx tag sidecar-export ~/reports/accepted_tags.sidecar.json --path PATH
uv run sfx tag sidecar-import ~/reports/accepted_tags.sidecar.json --db ~/.sfxworkbench/index.db

# Reviewed embedded metadata workflow
uv run sfx metadata write-plan ~/reports/metadata_write_plan.json --path PATH --bwfmetaedit /path/to/bwfmetaedit
uv run sfx metadata write-review ~/reports/metadata_write_plan.json --approve-all
uv run sfx metadata write-preview ~/reports/metadata_write_plan.json --require-reviewed
uv run sfx metadata write-fixtures ~/reports/metadata_write_plan.json ~/reports/metadata_fixtures --write-fixture-metadata
uv run sfx metadata write-readback ~/reports/metadata_fixtures --json
uv run sfx metadata write-apply ~/reports/metadata_write_plan.json --require-reviewed --apply --log ~/reports/apply_logs/metadata_write_apply_log.json
uv run sfx metadata write-undo ~/reports/apply_logs/metadata_write_apply_log.json --apply
```

Embedded writes currently support reviewed Mutagen-backed tags for FLAC,
Ogg/Vorbis, Opus, MP3, and M4A, plus reviewed BWF `bext` fields and RIFF INFO
`IKEY` keywords for WAV/RF64 through BWF MetaEdit. Unsupported container/field
combinations remain visible in plans instead of failing during apply.

UCS catalog support:

```bash
uv run sfx ucs import ~/Desktop/_categorylist.csv --release-version v8.2.1
uv run sfx ucs info
uv run sfx ucs categories --cat-short AMB
uv run sfx ucs validate PATH --json
```

## Optional Advanced Workflows

```bash
# Compare incoming packs against an existing index
uv run sfx compare audit ~/IncomingPack --against-db ~/.sfxworkbench/index.db --output ~/reports/compare_report.json
uv run sfx compare plan ~/reports/compare_report.json --output ~/reports/compare_plan.json

# Processed-file and dual-mono reports
uv run sfx processed PATH --db ~/.sfxworkbench/index.db --output ~/reports/processed_files.json
uv run sfx audio dual-mono audit PATH --db ~/.sfxworkbench/index.db --output ~/reports/dual_mono_report.json
uv run sfx audio dual-mono plan ~/reports/dual_mono_report.json --output ~/reports/dual_mono_plan.json
uv run sfx audio dual-mono review ~/reports/dual_mono_plan.json --approve-all
uv run sfx audio dual-mono apply ~/reports/dual_mono_plan.json --require-reviewed --output-root ~/ConvertedMono --apply

# Permanent delete, only from quarantine logs
uv run sfx delete plan ~/reports/apply_logs/pack_quarantine_log_YYYYMMDD_HHMMSS.json --output ~/reports/delete_plan.json
uv run sfx delete review ~/reports/delete_plan.json --approve-all
uv run sfx delete apply ~/reports/delete_plan.json --require-reviewed --i-understand-permanent-delete --apply
```

## Similarity

Similarity is optional and report-only. It uses deterministic descriptors cached
in SQLite and skips unchanged files on later runs.

```bash
uv run sfx similarity crawl PATH --db ~/.sfxworkbench/index.db --cache ~/.sfxworkbench/similarity
uv run sfx similarity backends --json
uv run sfx similarity segments PATH --db ~/.sfxworkbench/index.db --limit 200 --json
uv run sfx similarity search --file query.wav --db ~/.sfxworkbench/index.db --limit 20 --json
uv run sfx similarity search --file query.wav --db ~/.sfxworkbench/index.db --scope segment --limit 20 --json
uv run sfx similarity audit PATH --db ~/.sfxworkbench/index.db --threshold 0.92 --output ~/reports/similarity_audit.json
uv run sfx similarity feedback set --left one.wav --right two.wav --state ignored --db ~/.sfxworkbench/index.db
uv run sfx similarity feedback list --db ~/.sfxworkbench/index.db --state ignored --json
```

See [`docs/SIMILARITY.md`](docs/SIMILARITY.md) for the longer roadmap.

## Standalone First-Look Audit

`audit.py` is a no-install, zero-dependency first-look script. It does not
import the `sfxworkbench` package.

```bash
python3 audit.py PATH --output-dir ~/reports
python3 audit.py PATH --no-hash
python3 audit.py PATH --json
```

## Development

```bash
uv sync --extra tui --extra metadata --extra dev
uv run sfx --help
uv run --extra dev poe check
```

Useful docs:

- [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md): first guided pass
- [`docs/WINDOWS.md`](docs/WINDOWS.md): Windows TUI setup and smoke tests
- [`docs/PHASES.md`](docs/PHASES.md): roadmap and safety model
- [`docs/PRODUCT_DIRECTION.md`](docs/PRODUCT_DIRECTION.md): product direction
- [`docs/METADATA_TAGGING.md`](docs/METADATA_TAGGING.md): metadata/tagging plan
- [`docs/PACK_DEDUPLICATION.md`](docs/PACK_DEDUPLICATION.md): pack duplicate plan
- [`docs/RELEASE.md`](docs/RELEASE.md): release checklist
- [`CONTRIBUTING.md`](CONTRIBUTING.md): contribution policy
- [`SECURITY.md`](SECURITY.md): private reporting guidance

## License

sfxworkbench is licensed under the MIT License. See [`LICENSE`](LICENSE).
