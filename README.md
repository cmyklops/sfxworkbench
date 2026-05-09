# wavwarden

wavwarden helps sound designers clean up large SFX libraries without guessing
what will happen to their files.

It is built for commercial audio collections: Sound Ideas, GDC/Soniss bundles,
vendor packs, downloaded freebies, personal recordings, and years of folders
that have slowly become hard to search.

wavwarden is currently an **Internal Studio Beta**. The goal is practical,
reviewable library cleanup for real studio copies before public v1.0 polish.

## What It Helps With

- Remove junk files such as `.DS_Store`, AppleDouble files, waveform caches, and
  other non-audio clutter.
- Scan a library into a local SQLite index for search, audits, duplicate checks,
  and future UI workflows.
- Find exact duplicate audio files and quarantine extras instead of deleting
  them permanently.
- Clean risky filenames and folder names so libraries are more portable across
  macOS, Windows, DAWs, sync tools, and external drives.
- Organize obvious folder patterns, such as numbered Sound Ideas series folders,
  vendor/product folders, and sibling bundle groups.
- Report metadata, sample-rate, channel-layout, and related-take issues without
  changing the audio.
- Suggest tags from filenames, folders, UCS names, and related file groups.

wavwarden does **not** change audio content. Loudness normalization and sample
rate conversion are out of scope for the beta safety promise.

## Safety Promise

Filesystem-changing commands are designed to be boring and reversible:

- preview first
- never overwrite existing files
- require an explicit apply step
- write JSON reports or logs
- update the SQLite index after successful moves
- prefer quarantine or undo logs over permanent deletion

When in doubt, run the preview command and inspect the report before applying.

## Install

For development or internal beta use from a cloned repo:

```bash
uv sync --extra dev
uv run sfx --help
uv run --extra dev poe beta-audit PATH --output-dir ~/reports/wavwarden_beta_audit --include-similarity
```

Optional richer WAV metadata reads:

```bash
uv sync --extra metadata --extra dev
```

Single-command installs from GitHub or PyPI are planned, but should be tested
from clean machines before they are documented as the recommended path.

## Common Workflow

Replace `PATH` with your copied library folder. Do not start on your only copy.

```bash
# 1. Remove obvious junk. Dry-run first.
uv run sfx clean PATH
uv run sfx clean PATH --apply

# 2. Build or refresh the local index.
uv run sfx scan PATH

# 3. Check library health.
uv run sfx audit

# 4. Find exact duplicates.
uv run sfx dedupe --summary-only
uv run sfx dedupe --output ~/reports/dedupe_plan.json
uv run sfx dedupe --output ~/reports/dedupe_plan.json --safe-folder ~/CommercialLibraries/Master
uv run sfx dedupe --output ~/reports/dedupe_plan.json --prefer-folder ~/CommercialLibraries/Master --prefer-extension wav
uv run sfx dedupe --review ~/reports/dedupe_plan.json --approve-all
uv run sfx dedupe --apply ~/reports/dedupe_plan.json --require-reviewed
uv run sfx dedupe --apply ~/reports/dedupe_plan.json --safe-folder ~/CommercialLibraries/Master --require-reviewed

# 5. Preview portable filename cleanup.
uv run sfx rename PATH --pattern portable
uv run sfx rename PATH --pattern portable --apply --log ~/reports/portable_rename_log.json

# 6. Search indexed filenames.
uv run sfx search "gunshot exterior"
```

Default database:

```text
~/.wavwarden/index.db
```

Override it with `--db` when needed.

## Folder Organization

Folder organization is report-first. Preview, review, then apply.

```bash
# Remove simple numeric prefixes such as "01 Pack Name".
uv run sfx organize audit PATH --depth 1 --output ~/reports/organize_report.json

# Group known vendor/product folders.
uv run sfx organize audit PATH --pattern vendor-product-folders --output ~/reports/vendor_folders.json

# Group sibling families such as GDC 2015, GDC 2016, GDC2023.
uv run sfx organize audit PATH --pattern common-prefix-folders --output ~/reports/common_prefix_folders.json

# Group strict numeric library folders such as Sound Ideas 6000/7000/9000.
uv run sfx organize audit PATH --pattern numeric-series-folders --output ~/reports/numeric_series_folders.json

# Apply an approved organization report.
uv run sfx organize review ~/reports/organize_report.json --approve-all
uv run sfx organize apply ~/reports/organize_report.json --require-reviewed --log ~/reports/organize_log.json
```

Examples:

```text
6000 -> Sound Ideas/The General Series 6000
9000 -> Sound Ideas/Series 9000 Open and Close
SoundMorph - Energy -> SoundMorph/Energy
GDC 2015 - Soniss -> GDC/2015 - Soniss
CreaturesCK_1 -> CreaturesCK/1
```

## Portable Rename Mode

Use portable rename when a library needs safer names for drives, DAWs, shells,
CSV exports, and cross-platform collaboration.

```bash
uv run sfx rename PATH --pattern portable
uv run sfx rename PATH --pattern portable --apply --log ~/reports/portable_rename_log.json
```

Examples:

```text
Series 9000 Open & Close -> Series 9000 Open and Close
100_C#_Flesh & Bones!.wav -> 100_CSharp_Flesh and Bones_.wav
Bad:Name.wav -> Bad_Name.wav
```

Portable mode handles Unicode normalization, risky punctuation, non-ASCII
characters, illegal filename characters, and conservative long-path shortening.

## Reports And Metadata

These commands are report-only today:

```bash
uv run sfx metadata audit --output ~/reports/metadata_report.json
uv run sfx metadata backends --json
uv run sfx groups audit PATH --output ~/reports/related_groups_report.json
uv run sfx format audit PATH --output ~/reports/format_report.json
uv run sfx packs audit PATH --output ~/reports/pack_overlap_report.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --output ~/reports/pack_consolidation_plan.json
uv run sfx packs review ~/reports/pack_consolidation_plan.json --approve-all
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --require-reviewed
uv run sfx tag suggest PATH --use-ucs-catalog --min-confidence 0.8 --output ~/reports/tag_suggestions.json
uv run sfx tag plan PATH --from-suggestions ~/reports/tag_suggestions.json --output ~/reports/tag_plan.json
uv run sfx tag review ~/reports/tag_plan.json --approve-all
uv run sfx tag apply ~/reports/tag_plan.json --require-reviewed --apply --log ~/reports/tag_apply_log.json
uv run sfx tag sidecar-export ~/reports/accepted_tags.sidecar.json --path PATH
uv run sfx tag sidecar-import ~/reports/accepted_tags.sidecar.json --db ~/.wavwarden/index.db
uv run sfx metadata write-plan ~/reports/metadata_write_plan.json --path PATH --bwfmetaedit /path/to/bwfmetaedit
uv run sfx metadata write-review ~/reports/metadata_write_plan.json --approve-all
uv run sfx metadata write-preview ~/reports/metadata_write_plan.json --require-reviewed
uv run sfx metadata write-fixtures ~/reports/metadata_write_plan.json ~/reports/metadata_fixtures
uv run sfx metadata write-readback ~/reports/metadata_fixtures
```

UCS catalog support:

```bash
uv run sfx ucs import ~/Desktop/_categorylist.csv --release-version v8.2.1
uv run sfx ucs info
uv run sfx ucs categories --cat-short AMB
uv run sfx ucs validate PATH --json
```

Experimental similarity work starts with an optional descriptor crawler, not
with the default scan:

```bash
uv run sfx similarity crawl PATH --db ~/.wavwarden/index.db --cache ~/.wavwarden/similarity
uv run sfx similarity segments PATH --db ~/.wavwarden/index.db --limit 200 --json
uv run sfx similarity search --file query.wav --db ~/.wavwarden/index.db --limit 20 --json
uv run sfx similarity search --file query.wav --db ~/.wavwarden/index.db --scope segment --limit 20 --json
uv run sfx similarity audit PATH --db ~/.wavwarden/index.db --threshold 0.92 --output ~/reports/similarity_audit.json
uv run sfx similarity audit PATH --db ~/.wavwarden/index.db --scope segment --threshold 0.95 --json
uv run sfx similarity feedback set --left one.wav --right two.wav --state ignored --db ~/.wavwarden/index.db
uv run sfx similarity feedback list --db ~/.wavwarden/index.db --state ignored --json
```

This first slice stores deterministic descriptors in SQLite and skips unchanged
files on later runs. It captures loudness, silence, transient, zero-crossing,
basic spectral-shape evidence, and RMS-based event windows, then can rank
cached whole-file or segment descriptors against a query file and produce
report-only near-duplicate groups at either whole-file or event-window scope.
Segment audit uses coarse descriptor buckets to keep comparisons bounded and
reports how many candidate comparisons were evaluated. Review feedback such as
favorite, hidden, ignored, accepted, and rejected is stored only in SQLite.
The larger roadmap folds Sononym-style descriptor discovery together with a
Soundminer-style resumable cache builder. See
[`docs/SIMILARITY.md`](docs/SIMILARITY.md).

## Standalone First-Look Audit

`audit.py` is a no-install, zero-dependency script for a first look at a library.
It does not import the `wavwarden` package.

```bash
python3 audit.py PATH --output-dir ~/reports
python3 audit.py PATH --no-hash
python3 audit.py PATH --json
```

## Project Docs

- [`NEXT.md`](NEXT.md): current solo-dev sprint note
- [`docs/PHASES.md`](docs/PHASES.md): roadmap, safety model, JSON contracts
- [`docs/UCS.md`](docs/UCS.md): UCS data and category integration plan
- [`docs/METADATA_TAGGING.md`](docs/METADATA_TAGGING.md): metadata writing and audio-suggestion plan
- [`docs/SIMILARITY.md`](docs/SIMILARITY.md): optional audio similarity crawler roadmap
- [`docs/PACK_DEDUPLICATION.md`](docs/PACK_DEDUPLICATION.md): pack/folder duplicate detection plan
- [`CONTRIBUTING.md`](CONTRIBUTING.md): contribution policy during internal beta
- [`SECURITY.md`](SECURITY.md): private reporting guidance

## Development

```bash
uv run --extra dev poe test
uv run --extra dev poe lint
uv run --extra dev poe fmt-check
uv run --extra dev poe check
```

Run the full check before committing:

```bash
uv run --extra dev poe check
```

## License

wavwarden is licensed under the MIT License. See [`LICENSE`](LICENSE).
