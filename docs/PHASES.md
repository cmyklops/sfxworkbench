# sfxworkbench — Internal Studio Beta Roadmap

sfxworkbench manages commercial sound-library hygiene: audit, junk cleanup,
indexing, duplicate review, search/export, and reversible renaming. The product
target is an **Internal Studio Beta** before public v1.0.

## Product Principles

- Destructive workflows are dry-run, reviewed, quarantined, or reversible.
- CLI behavior is the source of truth; future TUI/GUI layers consume CLI JSON.
- Reports, plans, and logs are plain JSON/Markdown.
- Audio-content mutation is high risk and stays experimental until proven.
- Permanent disk deletion is advanced-only and should first operate on reviewed
  quarantine plans, not live libraries.
- `sfx` stays the user-facing command for the Internal Studio Beta. `sfxworkbench`
  remains the project/package name; no `sfxworkbench` CLI alias is planned before
  beta unless user testing shows confusion.

## Product Lessons From SMDB Companion

SMDB Companion is a useful reference point for professional duplicate-heavy
Soundminer workflows. sfxworkbench should learn from its practical trust controls
without copying its product shape. The main lessons to adopt are:

- safe folders that block automated cleanup plans
- preservation-priority rules that explain which duplicate copy should be kept
- repeatable presets for common review workflows
- database/import comparison before adding new libraries to a master index
- processed-file and AudioSuite-style pattern detection
- optional audio-content comparison with cached evidence
- advanced dual-mono detection/conversion
- permanent disk deletion for already-reviewed quarantine content

The sfxworkbench version of these features should remain filesystem-first,
JSON-first, and review-first. See `docs/ADVANCED_OPERATIONS.md` for the detailed
plan.

## Product Lessons From Sononym

Sononym is a useful reference for sample discovery, descriptor-driven browsing,
similarity search, duplicate review, and tagging. sfxworkbench should not copy its
browser-first product shape, but several ideas fit the CLI roadmap:

- duplicate keep choices should support prefer-folder and prefer-extension
  rules with plan evidence
- DB-only hide/ignore states are a useful non-destructive alternative before
  quarantine or deletion
- similarity and near-duplicate detection should be report-only at first, with
  explicit false-positive caveats
- audio descriptors such as peak, RMS, crest factor, rough brightness, length,
  channels, and bit depth are useful audit/search fields before ML workflows
- tag state should distinguish suggestions, accepted DB-only tags, manual tags,
  auto-tags, hidden/rejected tags, aliases, and UCS categories
- metadata browsing should highlight fields that are actually present in a
  selected library

## Product Lessons From Soundminer Similarity

Soundminer's upcoming similarity crawler reinforces the Sononym lessons with a
more CLI-friendly implementation pattern. The useful idea is not the exact UI;
it is the offline crawler that precomputes audio-content evidence into a small,
resumable cache.

sfxworkbench should adopt that architecture for future similarity work:

- keep `sfx scan` fast and metadata-oriented
- add a separate optional `sfx similarity crawl` command for heavier analysis
- skip unchanged files using path, size, mtime, and hash anchors
- resume interrupted crawls and support scheduled overnight runs
- support job/CPU limits so analysis can run in the background
- store per-file and per-segment descriptors or embeddings outside the core
  `files` table
- treat similarity as discovery evidence, not cleanup authority

This becomes the bridge from library hygiene into library discovery. See
[`SIMILARITY.md`](SIMILARITY.md) for the proposed Phase 2.5 crawler roadmap.

## Current Phase — Hardened CLI Core

Implemented commands:

```bash
uv run sfx clean PATH
uv run sfx scan PATH
uv run sfx audit
uv run sfx audit-bundle PATH --db ~/.sfxworkbench/index.db --output-dir ~/reports/sfxworkbench_audit --json
uv run sfx metadata audit --output ~/reports/metadata_report.json
uv run sfx metadata view QUERY --db ~/.sfxworkbench/index.db
uv run sfx metadata backends --json
uv run sfx metadata write-plan ~/reports/metadata_write_plan.json --path PATH --bwfmetaedit /path/to/bwfmetaedit
uv run sfx metadata write-review ~/reports/metadata_write_plan.json --approve-all
uv run sfx metadata write-preview ~/reports/metadata_write_plan.json --require-reviewed
uv run sfx metadata write-fixtures ~/reports/metadata_write_plan.json ~/reports/metadata_fixtures
uv run sfx metadata write-fixtures ~/reports/metadata_write_plan.json ~/reports/metadata_fixtures --write-fixture-metadata
uv run sfx metadata write-readback ~/reports/metadata_fixtures --json
uv run sfx metadata write-apply ~/reports/metadata_write_plan.json --require-reviewed
uv run sfx metadata write-apply ~/reports/metadata_write_plan.json --config ~/sfxworkbench.json --require-reviewed
uv run sfx metadata write-apply ~/reports/metadata_write_plan.json --require-reviewed --apply --log ~/reports/apply_logs/metadata_write_apply_log.json
uv run sfx metadata write-undo ~/reports/apply_logs/metadata_write_apply_log.json
uv run sfx metadata write-undo ~/reports/apply_logs/metadata_write_apply_log.json --apply
uv run sfx groups audit PATH --output ~/reports/related_groups_report.json
uv run sfx format audit PATH --output ~/reports/format_report.json
uv run sfx scan-errors --output ~/reports/scan_error_plan.json
uv run sfx scan-errors --apply ~/reports/scan_error_plan.json
uv run sfx search QUERY
uv run sfx export --output library.csv
uv run sfx similarity crawl PATH --db ~/.sfxworkbench/index.db --cache ~/.sfxworkbench/similarity
uv run sfx similarity segments PATH --db ~/.sfxworkbench/index.db --limit 200 --json
uv run sfx similarity search --file query.wav --db ~/.sfxworkbench/index.db --limit 20 --json
uv run sfx similarity search --file query.wav --db ~/.sfxworkbench/index.db --scope segment --limit 20 --json
uv run sfx similarity audit PATH --db ~/.sfxworkbench/index.db --threshold 0.92 --output ~/reports/similarity_audit.json
uv run sfx similarity audit PATH --db ~/.sfxworkbench/index.db --scope segment --threshold 0.95 --json
uv run sfx similarity feedback set --left one.wav --right two.wav --state ignored --db ~/.sfxworkbench/index.db
uv run sfx similarity feedback list --db ~/.sfxworkbench/index.db --state ignored --json
uv run sfx similarity feedback clear --left one.wav --right two.wav --db ~/.sfxworkbench/index.db
uv run sfx dedupe --summary-only
uv run sfx dedupe --output ~/reports/dedupe_plan.json
uv run sfx dedupe --output ~/reports/dedupe_plan.json --safe-folder ~/CommercialLibraries/Master
uv run sfx dedupe --output ~/reports/dedupe_plan.json --prefer-folder ~/CommercialLibraries/Master --prefer-extension wav
uv run sfx dedupe --review dedupe_plan.json --approve-all
uv run sfx dedupe --apply dedupe_plan.json --require-reviewed
uv run sfx dedupe --apply dedupe_plan.json --safe-folder ~/CommercialLibraries/Master --require-reviewed
uv run sfx packs audit PATH --output ~/reports/pack_overlap_report.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --output ~/reports/pack_consolidation_plan.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --safe-folder ~/CommercialLibraries/Master --output ~/reports/pack_consolidation_plan.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --prefer-folder ~/CommercialLibraries/Master --output ~/reports/pack_consolidation_plan.json
uv run sfx packs review ~/reports/pack_consolidation_plan.json --approve-all
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --require-reviewed
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --safe-folder ~/CommercialLibraries/Master --require-reviewed
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --apply --require-reviewed --log ~/reports/apply_logs/pack_quarantine_log.json
uv run sfx packs undo ~/reports/apply_logs/pack_quarantine_log.json --apply
uv run sfx organize audit PATH --depth 1 --output ~/reports/organize_report.json
uv run sfx organize audit PATH --depth 1 --config ~/sfxworkbench.json --output ~/reports/organize_report.json
uv run sfx organize audit PATH --pattern vendor-product-folders --output ~/reports/vendor_folders.json
uv run sfx organize audit PATH --pattern common-prefix-folders --output ~/reports/common_prefix_folders.json
uv run sfx organize audit PATH --pattern numeric-series-folders --output ~/reports/numeric_series_folders.json
uv run sfx organize audit PATH --pattern redundant-nesting --depth 8 --output ~/reports/nesting_report.json
uv run sfx organize nesting-plan ~/reports/nesting_report.json --output ~/reports/nesting_plan.json
uv run sfx organize nesting-plan ~/reports/nesting_report.json --kind single_child_chain --output ~/reports/single_child_plan.json
uv run sfx organize nesting-plan ~/reports/nesting_report.json --kind low_value_wrapper --output ~/reports/wrapper_plan.json
uv run sfx organize review ~/reports/nesting_plan.json --approve-all
uv run sfx organize nesting-apply ~/reports/nesting_plan.json --require-reviewed
uv run sfx organize nesting-apply ~/reports/nesting_plan.json --apply --require-reviewed --log ~/reports/apply_logs/nesting_log.json
uv run sfx organize nesting-undo ~/reports/apply_logs/nesting_log.json --apply
uv run sfx organize review organize_report.json --approve-all
uv run sfx organize apply organize_report.json --require-reviewed --log ~/reports/apply_logs/organize_log.json
uv run sfx organize apply organize_report.json --config ~/sfxworkbench.json --require-reviewed --log ~/reports/apply_logs/organize_log.json
uv run sfx organize undo ~/reports/apply_logs/organize_log.json --apply
uv run sfx rename PATH --pattern ucs
uv run sfx rename PATH --pattern safe
uv run sfx rename PATH --pattern portable
uv run sfx rename PATH --pattern portable --config ~/sfxworkbench.json
uv run sfx rename PATH --pattern ucs --apply --log ~/reports/apply_logs/rename_log.json
uv run sfx rename PATH --pattern safe --apply --allow-partial --log ~/reports/apply_logs/safe_rename_log.json
uv run sfx rename PATH --pattern portable --apply --log ~/reports/apply_logs/portable_rename_log.json
uv run sfx rename --undo ~/reports/apply_logs/rename_log.json --apply
uv run sfx tag propose PATH --db ~/.sfxworkbench/index.db --min-confidence 0.6 --output ~/reports/tag_proposals.json
uv run sfx tag suggest PATH --db ~/.sfxworkbench/index.db --output ~/reports/tag_suggestions.json
uv run sfx tag suggest PATH --db ~/.sfxworkbench/index.db --use-ucs-catalog --min-confidence 0.8 --source ucs_catalog --field ucs_category --field ucs_subcategory --json
uv run sfx tag plan PATH --db ~/.sfxworkbench/index.db --from-suggestions ~/reports/tag_suggestions.json --source ucs_catalog --field ucs_category --field ucs_subcategory --output ~/reports/tag_plan.json
uv run sfx tag summarize ~/reports/tag_plan.json --value-limit 20
uv run sfx tag review ~/reports/tag_plan.json --approve-field ucs_category --only-status pending
uv run sfx tag review ~/reports/tag_plan.json --approve-all
uv run sfx tag apply ~/reports/tag_plan.json --db ~/.sfxworkbench/index.db --require-reviewed
uv run sfx tag apply ~/reports/tag_plan.json --db ~/.sfxworkbench/index.db --require-reviewed --apply --log ~/reports/apply_logs/tag_apply_log.json
uv run sfx tag sidecar-export ~/reports/accepted_tags.sidecar.json --db ~/.sfxworkbench/index.db --path PATH
uv run sfx tag sidecar-import ~/reports/accepted_tags.sidecar.json --db ~/.sfxworkbench/index.db
uv run sfx ucs import ~/Desktop/_categorylist.csv --release-version v8.2.1
uv run sfx ucs info
uv run sfx ucs categories --cat-short AMB
uv run sfx ucs validate PATH --db ~/.sfxworkbench/index.db --json
```

Core command families support `--json` for automation and future UI work.

### Standalone Phase 0 Audit

`audit.py` remains a zero-dependency, Python 3.9+ first-look auditor:

```bash
python3 audit.py ~/CommercialLibraries --output-dir ~/reports
python3 audit.py ~/CommercialLibraries --no-hash
python3 audit.py ~/CommercialLibraries --json
```

## Safety Workflows

- `clean`: dry-run by default; `--apply` removes known junk only.
- `scan`: indexes audio files into SQLite and skips junk.
- `metadata audit`: report-only metadata coverage and unusual sample-rate review.
- `metadata view`: report-only per-file inspector for indexed audio facts,
  embedded metadata presence flags, UCS parse/catalog match, and accepted
  DB-only tags.
- `metadata backends`: report-only external metadata writer discovery. It
  captures BWF MetaEdit and Mutagen availability/capabilities without modifying
  audio.
- `metadata write-plan/review/preview/fixtures/readback`: reviewed embedded
  metadata write workflow. It consumes accepted tags, validates anchors, copies
  fixture bundles, can write Mutagen-backed tags or run BWF MetaEdit against
  copied fixtures, and compares BEXT, RIFF INFO, or Mutagen readback without
  modifying original audio.
- `metadata write-apply`: dry-run by default; with `--apply`, writes reviewed
  Mutagen-backed tags for proven fields in original FLAC, Ogg/Vorbis, Opus,
  MP3, and M4A files plus BWF MetaEdit-backed `bext` and RIFF INFO `IKEY`
  fields to original WAV/RF64 files after creating backups, then verifies
  readback and refreshes the index. `--config` safe folders block original-audio
  writes. AIFF/AIF and unsupported field/container combinations stay visible as
  unsupported plan entries.
- `metadata write-undo`: dry-run by default; with `--apply`, restores originals
  from a metadata write apply log's backups and refreshes indexed anchors.
- `groups audit`: report-only related sound groups inferred from numbered takes
  and channel-set filename patterns.
- `format audit`: report-only sample-rate, bit-depth, and channel-count consistency
  review within related groups. It does not recommend or perform conversion.
- `scan-errors`: writes a review plan for unreadable indexed files; quarantines
  only obvious artifacts/all-zero blobs by default.
- `similarity crawl`: experimental, optional deterministic descriptor crawler
  over indexed files. It stores SQLite descriptor rows, writes an optional cache
  run report, captures loudness/transient/spectral descriptors plus RMS-based
  event segments, and skips unchanged files by size/mtime/hash anchors.
- `similarity segments`: experimental report-only listing of cached event
  windows from the similarity crawler.
- `similarity search`: experimental nearest-neighbor search over cached
  deterministic whole-file descriptors or event segments using a query audio
  file.
- `similarity audit`: experimental report-only near-duplicate grouping over
  cached deterministic whole-file descriptors or event segments. Exact MD5
  duplicate pairs are excluded by default because `dedupe` owns exact duplicate
  cleanup. Segment audit uses coarse descriptor buckets to reduce candidate
  comparisons.
- `similarity feedback`: DB-only review states for similarity relationships
  such as favorite, hidden, ignored, accepted, and rejected.
- `tag propose`: report-only UCS tag proposals from corroborated evidence.
  Filename/UCS-looking stems are weak evidence, not semantic proof.
- `tag suggest`: report-only raw metadata suggestions from filename, path, UCS
  provenance, and related-group evidence. It is useful as a debugging/evidence
  feed, not the primary semantic tagging path.
- `tag summarize`: report-only tag plan rollup by field, source, review status,
  and proposed value with sample filenames for batch review.
- `tag plan/review/apply`: reviewed DB-only metadata writes to `accepted_tags`.
  Review supports entry IDs plus field/source/value selectors. Apply validates
  file anchors, writes `tag_apply_log`, and never mutates audio.
- `tag sidecar-export/import`: portable JSON sidecars for accepted DB-only tags.
- `dedupe --summary-only`: finds exact MD5 duplicate groups and prints counts without writing a plan.
- `dedupe --output PLAN.json`: writes a reviewed duplicate plan to an explicit path. Repeated `--safe-folder PATH` options and `--config CONFIG.json` safe folders prefer protected duplicate files as keep copies and mark protected extra copies as ignored. Repeated `--prefer-folder PATH` / `--prefer-extension EXT` options and matching config rules store preservation-priority evidence and choose keep copies accordingly.
- `dedupe --review PLAN.json`: stamps all or selected duplicate groups as approved.
- `dedupe --apply`: validates size/hash and quarantines by default; use `--require-reviewed` to refuse unapproved plans. Plan-recorded, CLI, and `--config` safe folders are re-checked before quarantine or deletion.
- `packs audit`: report-only exact duplicate folder and pack-overlap detection; no filesystem or SQLite mutation.
- `organize audit/review/apply/undo`: safe folder-structure cleanup with review gate, SQLite path updates, and undo log.
- `organize audit --pattern redundant-nesting`: report-only folder-structure review for repeated names, one-child chains, and low-value wrappers.
- `organize nesting-plan/apply/undo`: reviewed flatten workflow for repeated folder names, non-generic single-child chains, and strict leaf wrappers; dry-run by default and never overwrites.
- `rename`: previews UCS-oriented, safe, or portable filename/path changes, refuses collisions, applies with undo log. `--config` safe folders block protected rename entries during preview and apply validation. `--pattern portable` fixes Unicode normalization, risky cross-platform characters, non-ASCII names, and conservative long paths. `--allow-partial` can apply valid entries while keeping unresolved collisions visible in the result.

## Phase 2 — Cleanup Tooling

`sfx rename` now supports `ucs`, `safe`, and `portable` preview/apply/undo behavior.
Portable mode is the user-facing cross-platform cleanup path for studios that
want names to survive Windows/macOS drives, shells, DAWs, sync tools, and CSV
round-trips. It normalizes Unicode, replaces risky punctuation such as `&` with
word-safe equivalents where possible, strips or replaces illegal filename
characters, handles non-ASCII names conservatively, shortens long paths, renames
folders as well as files, updates SQLite rows, refuses collisions, and writes an
undo log.

```text
Series 9000 Open & Close -> Series 9000 Open and Close
100_C#_Flesh & Bones!.wav -> 100_CSharp_Flesh and Bones_.wav
```

Pack/folder duplicate detection is the next professional-grade safety layer
after exact file dedupe and filename/path cleanup. The reviewed report/plan/apply
workflow now exists for exact duplicate folders and fully-covered overlap
candidates:

- `sfx packs audit`: detect exact duplicate folders and high-overlap packs. Implemented as report-only.
- `sfx packs plan`: create a reviewed consolidation/quarantine plan. Exact
  duplicate folder groups plan all but the deterministic keep folder for
  quarantine. Fully-covered overlap candidates plan the smaller folder for
  quarantine. Partial overlaps stay review-only so unique files are not moved by
  default. Repeated `--safe-folder PATH` options prefer protected exact
  duplicates as keep folders and mark protected sources as ignored. Repeated
  `--prefer-folder PATH` options store preservation-priority evidence and choose
  pack keep folders accordingly.
- `sfx packs review`: approve all or selected 1-based plan groups.
- `sfx packs apply`: dry-run by default; with `--apply`, quarantine redundant
  folders, validate files and hashes before moving, re-check plan and CLI safe
  folders, update SQLite paths, and write an undo log.
- `sfx packs undo`: restore quarantined folders from the undo log and update
  SQLite paths.

Folder consolidation must not permanently delete by default. Merging unique
files is a later explicit action and must never overwrite existing files.
The next duplicate-planning layer should extend safe folders and preservation
priority beyond dedupe and packs, then add richer metadata/UCS scoring so
keep/quarantine recommendations are tunable and explainable.

Folder organization follows the same safety model. First workflow:
`sfx organize audit PATH --depth 1 --pattern strip-leading-numbers`, reporting
top-level folder changes such as `01 Vendor Pack` -> `Vendor Pack` for
alphabetized browsing and easier bulk edits. It also strips whole-name wrapper
brackets/parentheses such as `[99Sounds]` -> `99Sounds` or `(A Sound Effect)` ->
`A Sound Effect`. Apply requires a reviewed report, refuses collisions, updates
SQLite paths, and writes an undo log.

Vendor/product re-foldering is implemented as a conservative reviewed workflow:
`sfx organize audit PATH --pattern vendor-product-folders`. It detects known
vendor prefixes in sibling folders such as `SoundMorph - Energy`, `SoundMorph -
Sinematic 2`, `Ghosthack - Pack Name`, or `A Sound Effect - Pack Name` and
proposes:

```text
SoundMorph - Energy      -> SoundMorph/Energy
SoundMorph - Sinematic 2 -> SoundMorph/Sinematic 2
```

This workflow uses the existing report/review/apply/undo path, creates parent
folders only as planned, never overwrites existing files, reports collisions as
unresolved review items, and updates SQLite paths after successful moves.

Sibling family re-foldering is also implemented as a conservative reviewed
workflow: `sfx organize audit PATH --pattern common-prefix-folders`. It looks
for three or more sibling folders with the same parsed prefix and proposes a
shared parent while stripping the repeated prefix from child folders:

```text
GDC 2015 - Soniss       -> GDC/2015 - Soniss
GDC SFX 2017            -> GDC/SFX 2017
GDC+++Game+Audio+Bundle -> GDC/Game Audio Bundle
GDC2023                 -> GDC/2023
CreaturesCK_1           -> CreaturesCK/1
```

This pattern is intentionally separate from vendor/product matching. It is
useful for folder families, yearly bundles, and numbered series, but should
still be reviewed before applying because common prefixes can be semantic.

Strict numeric folder organization is implemented as:
`sfx organize audit PATH --pattern numeric-series-folders`. It first checks a
small built-in, sourced catalog of popular Sound Ideas series numbers, then
falls back to a fast filename-token category guess when there is no catalog hit.
Catalog hits produce vendor/product parents; inferred categories produce named
category parents:

```text
6000  -> Sound Ideas/The General Series 6000
9000  -> Sound Ideas/Series 9000 Open and Close
12000 -> Sound Ideas/Series 12000 Anchors Away
4242  -> Animals/4242       # inferred from child filenames, when confident
```

Unknown numeric folders remain review candidates instead of being moved. Future
versions should load a user-editable series catalog so studios can add
proprietary or legacy library number mappings without changing sfxworkbench code.

The next organization audit is implemented as report-only:
`sfx organize audit PATH --pattern redundant-nesting --depth 8`, flagging:

- redundant one-child folder chains
- repeated folder names such as `Vendor/Pack/Pack`
- low-value wrapper folders such as `WAV`, `Audio`, or `Files` when they add no
  meaningful category

Repeated folder names are promoted into the first reviewed flatten workflow:
`sfx organize nesting-plan REPORT --output PLAN`, then `sfx organize review PLAN`,
then `sfx organize nesting-apply PLAN --require-reviewed`. The apply command is
dry-run by default; `--apply` is required to move anything. It refuses collisions,
updates SQLite paths, removes the emptied repeated folder, and writes an undo log.

Single-child chains are also supported when the child folder name is not generic:
`sfx organize nesting-plan REPORT --kind single_child_chain --output PLAN`.
The planner orders nested wrappers deepest-first, skips generic child names such
as `Content`, `Designed`, `Source`, and `Sounds`, and uses the same review/apply/undo path.

Low-value wrappers can be planned only when they are leaf folders with low-risk
names such as `Samples`, `Audio`, `WAV`, or `Files`:
`sfx organize nesting-plan REPORT --kind low_value_wrapper --output PLAN`.
The planner skips semantic wrappers such as `Designed`, `Source`, `Content`, and
`Sounds`, and skips wrappers that contain subfolders. Broader wrapper flattening
remains report-only because it can require subjective merge choices.

Related group detection is implemented first as report-only:
`sfx groups audit PATH`, inferring numbered takes and channel sets from indexed
filenames. Future versions can layer in path tokens, accepted/proposed tags,
metadata, and exact/perceptual similarity. Take numbers and channel positions
are structural facts for grouping/review, not high-value library search tags by
default.

Format consistency is an advanced, report-only diagnostic:
`sfx format audit PATH`, flagging related groups where files differ in sample
rate, bit depth, or channel count. These differences are often intentional
vendor/source/design choices and should be treated as preservation evidence, not
cleanup instructions. Format audit is not a default Internal Studio Beta cleanup
gate. Automatic format conversion and loudness normalization are out of scope
for the Internal Studio Beta.

Physical folder cleanup is useful for browsing and bulk edits, but future
integrations should primarily consume indexed metadata and inferred group
relationships instead of depending on folder layout.

Workflow orchestration should be a later wrapper over existing commands, not a
hidden one-shot cleanup. Planned shape:

```bash
uv run sfx workflow audit PATH --preset internal-beta
uv run sfx workflow plan PATH --preset library-cleanup --output workflow_plan.json
uv run sfx workflow apply workflow_plan.json --require-reviewed
```

Each workflow step must preserve its own report, plan, quarantine, or undo log
so large batch runs remain explainable and recoverable. Default apply and undo
logs are grouped under `apply_logs/` beside the source report or plan.

A developer-facing dry-run harness now exercises the current beta-safe audit
path without modifying the library:

```bash
uv run --extra dev poe beta-audit ~/CommercialLibraries --output-dir ~/reports/sfxworkbench_beta_audit
python scripts/internal_beta_audit.py ~/CommercialLibraries --output-dir ~/reports/sfxworkbench_beta_audit
```

The harness runs `scan`, `audit`, `metadata audit`, `groups audit`,
`packs audit`, `packs plan`, and a dry-run pack apply preview. It writes a
self-contained report bundle plus `manifest.json`. By default the SQLite index
lives inside the output directory; pass `--db` to reuse another index
explicitly. Pass `--include-format` only when doing a deeper mixed-format
diagnostic pass.

Metadata writing follows the reviewed-plan model:

- `sfx metadata audit`
- `sfx metadata backends`, implemented as BWF MetaEdit and Mutagen availability/capability preflight
- `sfx metadata write-plan/review/preview/fixtures/readback`, implemented as embedded write planning, copied fixture bundles, optional Mutagen and BWF MetaEdit fixture writes, and BEXT/RIFF INFO/Mutagen readback comparison
- `sfx metadata write-apply`, implemented for reviewed Mutagen-backed original-file writes and BWF MetaEdit-backed WAV/RF64 `bext`/RIFF INFO writes with backups, readback verification, and index refresh
- `sfx metadata write-undo`, implemented for backup restores from apply logs
- `sfx tag propose`, implemented as report-only evidence-fusion UCS candidates
- `sfx tag suggest`, implemented as a raw filename/path/group/UCS provenance evidence feed
- `sfx tag plan/review/apply`, implemented for DB-only accepted tags
- `sfx tag sidecar-export/import`, implemented for portable JSON accepted tags
- future iXML and wider BWF field writes after fixture and real-library proof

Both should use mature libraries/tools for BWAV/iXML writes rather than
hand-rolled binary mutation.

Advanced operations planned after the beta-safe workflows stabilize:

- expand shared preservation config beyond safe folders into richer
  workflow-specific controls
- preservation-priority scoring for duplicate keep recommendations
- database/import compare workflows
- processed-file detection for rendered/plugin variants
- optional audio fingerprint matching
- dual-mono audit/plan/copy-output conversion
- permanent deletion from reviewed quarantine plans

Dual-mono conversion and permanent disk deletion are explicitly planned, but
they are not part of the default Internal Studio Beta path. Dual-mono starts as
report-only, then copy-output conversion, with in-place replacement only after
fixtures and copied-library tests prove the workflow. Permanent deletion starts
from reviewed quarantine logs and requires an explicit irreversible-delete flag.

## Phase 2.5 — Audio Analysis And Similarity

After the cleanup, organization, and tag-plan foundations settle, keep expanding
the optional audio-analysis lane. This lane should remain CLI-first and
JSON-first:

```bash
uv run sfx similarity crawl PATH --db ~/.sfxworkbench/index.db --cache ~/.sfxworkbench/similarity
uv run sfx similarity segments PATH --db ~/.sfxworkbench/index.db --limit 200 --json
uv run sfx similarity search --file query.wav --db ~/.sfxworkbench/index.db --limit 50 --json
uv run sfx similarity search --file query.wav --db ~/.sfxworkbench/index.db --scope segment --limit 50 --json
uv run sfx similarity audit PATH --db ~/.sfxworkbench/index.db --threshold 0.92 --output similarity_report.json
uv run sfx similarity audit PATH --db ~/.sfxworkbench/index.db --scope segment --threshold 0.95 --json
uv run sfx similarity feedback set --left one.wav --right two.wav --state favorite --db ~/.sfxworkbench/index.db
uv run sfx similarity feedback list --db ~/.sfxworkbench/index.db --json
```

First useful slice:

- cheap descriptors such as peak, RMS, crest factor, rough brightness,
  transient density, silence, clipping, duration, channels, sample rate, and
  bit depth. Initial deterministic crawler implemented.
- segment/event detection for long ambience and designed files, with cached
  segment descriptors and report-only segment listing implemented
- optional per-file and per-segment embeddings behind an extra dependency
- JSON nearest-neighbor results with explicit distance/confidence caveats,
  implemented for whole-file and segment search
- report-only whole-file and segment near-duplicate audits with coarse pruning
- DB-only feedback states such as favorite, hidden, ignored, accepted, or
  rejected similarity matches, implemented with `similarity feedback`

The crawler must never mutate audio or make cleanup decisions. At most, it can
feed later reviewed reports for near duplicates, audio-listening tag
suggestions, and discovery views.

### Directly Useful Open-Source Tools

These projects are strong candidates for supporting sfxworkbench's planned feature
set without copying unclear or incompatible code into the repo:

| Tool | License posture | sfxworkbench use |
| --- | --- | --- |
| `wavinfo` | MIT | Richer WAV/RF64/BWF/iXML metadata reads for `scan`, `audit`, and tag planning. |
| BWF MetaEdit | Public domain project | Reference behavior or external backend for BWF metadata validation/writing. |
| `pyacoustid` | MIT | Optional perceptual duplicate candidate detection after exact MD5 dedupe. |
| Textual | MIT | First review UI: duplicate review, rename preview, audit drilldown, approval flows. |
| PANNs inference | MIT | Optional reviewed audio-listening tag suggestions. |
| CLAP-style models | Varies by model | Optional audio/text embeddings for similarity and label ranking after license and runtime review. |

Use Chromaprint via `pyacoustid`/`fpcalc` as an optional external capability
rather than vendoring Chromaprint code. Keep ML tagging review-only and outside
the Internal Studio Beta safety promise until privacy, model provenance, and
runtime cost controls are clear.

See [`UCS.md`](UCS.md) for the UCS data plan and
[`METADATA_TAGGING.md`](METADATA_TAGGING.md) for the metadata/audio-suggestion
roadmap. See [`SIMILARITY.md`](SIMILARITY.md) for the optional similarity
crawler roadmap. See [`PACK_DEDUPLICATION.md`](PACK_DEDUPLICATION.md) for the
pack/folder duplicate detection and consolidation plan. See
[`ADVANCED_OPERATIONS.md`](ADVANCED_OPERATIONS.md) for safe folders,
preservation priority, dual-mono conversion, disk deletion, import compare, and
other advanced workflows.

Audio format conversion and loudness normalization are not part of the beta
roadmap because sfxworkbench should preserve original audio content.

## Phase 3 — Review UI

Build a Textual TUI before Tauri. The current alpha exists behind `sfx tui` as
a full-feature operations workbench with Scan, Files, Clean, Dedupe, Organize,
Metadata, Similarity, and Advanced pages. It uses the same CLI/package workflow
functions as the command line and keeps guarded operations visible without
creating hidden mutation paths. The product direction is captured in
[`PRODUCT_DIRECTION.md`](PRODUCT_DIRECTION.md); the visual/workbench direction
is captured in [`APP_UI_DIRECTION.md`](APP_UI_DIRECTION.md).

The TUI should continue to focus on:

- dashboard signals for indexed files, duplicates, missing metadata, filename
  issues, UCS issues, pack overlaps, pending review actions, and protected
  folders
- decision queues for unsafe filenames, long paths, Unicode normalization,
  missing metadata, UCS validation failures, obvious duplicates, possible
  duplicates, pack overlaps, format inconsistencies, tag proposals, and embedded
  metadata conflicts
- before/after cleanup plan viewing for rename, organize, dedupe, packs,
  metadata write, tag apply, sidecar, and later pack-intake plans
- metadata gap report drilldown
- safe-folder firewall and preservation-priority controls
- duplicate and pack overlap/consolidation review
- UCS migration review
- similarity group review
- apply/undo log review
- quarantine age and permanent-delete eligibility review
- future dual-mono candidate review
- future team-friendly approval workflows

Tauri remains a later option after CLI JSON contracts are stable.

## Professional-Grade Beta Bar

Internal Studio Beta is reached when:

- documented commands match the actual CLI
- CI runs `uv run pytest tests/ -v`
- scan/audit/dedupe/rename/export workflows have JSON output
- filesystem-changing workflows have logs, quarantine, or undo
- duplicated pack/folder detection can produce reviewed JSON evidence before
  any consolidation action
- tests cover the safety paths, not just happy paths

## Development Audit Track

Before Internal Studio Beta, run a focused audit pass over the workflows that
could affect a real commercial library. These audits are development gates, not
new user-facing cleanup commands unless a later workflow wrapper exposes them.

### Safety Audit

Verify every filesystem-changing command defaults to dry-run, quarantine,
review-first, or undoable behavior. Confirm apply paths refuse collisions,
validate planned files before moving anything, preserve originals by default,
write complete logs, and keep SQLite paths accurate after rename, quarantine, or
folder moves.

Target workflows:

- `clean --apply`
- `scan-errors --apply`
- `dedupe --apply`
- `rename --apply` and `rename --undo`
- `organize apply`, `organize undo`, `organize nesting-apply`, and
  `organize nesting-undo`
- `packs apply` and `packs undo`
- embedded metadata/tag apply and undo workflows
- future dual-mono conversion workflows
- future permanent-delete workflows

### JSON Contract Audit

Treat CLI JSON as the stable automation surface for Textual/Tauri and scripted
studio workflows. For each `--json` command, verify stable `schema_version`,
predictable field names, no Rich output mixed into machine-readable responses,
and backward-compatible additions where possible. Document intentional breaking
changes with a schema bump.

### Fixture Workflow Audit

Maintain realistic end-to-end fixture runs that exercise command sequences, not
just isolated functions:

```bash
scan -> audit -> dedupe -> review -> apply -> undo
scan -> rename preview -> apply -> undo
scan -> organize audit -> review -> apply -> undo
scan -> packs audit -> plan -> review -> apply -> undo
scan -> metadata write-plan -> review -> apply -> undo
```

These tests should cover collisions, missing files, changed hashes, stale plans,
sidecar files, Unicode normalization, long paths, scan errors, and DB path
updates.

### Real-Library Dry-Run Audit

Run report-only commands against a copied or read-only real library before beta.
Capture scan performance, junk false positives, rename and organization review
quality, pack-overlap usefulness, metadata coverage, similarity crawl runtime,
cache size, noisy matches, segment-audit thresholds, and edge cases from vendor
folder conventions. Do not apply changes during the first pass.

### SQLite Schema Audit

Verify schema creation and upgrades remain idempotent, existing indexes and FTS5
triggers stay correct, and older databases continue to open after additive
schema changes. New tables for tags, metadata, or pack plans should preserve the
existing `files` and `files_fts` contract.

### Dependency And Packaging Audit

Test a clean install from scratch, including optional extras such as
`.[metadata,dev]`. Confirm CLI startup remains fast, package metadata is
accurate, optional readers fail gracefully when absent, and no workflow depends
on undeclared local tools or files.

### Performance Audit

Benchmark large synthetic and sampled real libraries with hashing enabled and
disabled. Watch memory use, SQLite query plans, and accidental quadratic
comparisons in pack, group, and organize logic. Keep the benchmark loop aligned
with `uv run --extra dev poe bench-scan --files 1000 --no-hash` and expand it
when pack planning or metadata suggestions become heavier.

### Trust And Review UX Audit

Review command output as if the target library were irreplaceable. Previews
should explain what will change, apply commands should name risky operations
plainly, logs should be sufficient to recover, and report-only workflows should
make uncertainty visible instead of implying automatic cleanup.

## Development Loop

Local and CI validation should use the same Poe tasks:

```bash
uv run --extra dev poe check
uv run --extra dev poe json-smoke
uv run --extra dev poe bench-scan --files 1000 --no-hash
uv run --extra dev poe beta-audit PATH --output-dir ~/reports/sfxworkbench_beta_audit
uv run --extra dev poe beta-audit PATH --output-dir ~/reports/sfxworkbench_beta_audit --similarity-validation
```

The JSON automation surface is documented below. Synthetic scan benchmarking
lives in `scripts/bench_large_library.py`; real-library sampling lives in
`scripts/bench_scan.py`. The report-only Internal Studio Beta audit harness
lives in `scripts/internal_beta_audit.py`; use `--similarity-validation` when
manually validating crawler runtime, cache size, segment counts, and audit
thresholds on a copied or read-only real library. `--include-similarity` remains
supported as the older spelling, but overnight automation is deferred until
manual validation passes on representative libraries.

## JSON Contracts

JSON output is the stable automation surface for future Textual/Tauri review
tools. Core commands use a common envelope:

```json
{
  "schema_version": 1,
  "command": "scan"
}
```

Command contracts:

- `clean --json`: includes `result.dry_run`, `removed_files`, `removed_dirs`, and `bytes_freed`.
- `scan --json`: includes `root`, `db_path`, and `result.total/scanned/skipped/errors`.
- `audit --json`: includes `db_path` and aggregate `AuditResult` fields.
- `metadata audit --json`: includes `db_path`, optional `report_path`, and a versioned report with missing BWF/iXML metadata entries and unusual sample-rate entries.
- `metadata backends --json`: includes discovered external metadata writer
  backends, executable paths, version command output, and capability flags.
- `metadata write-plan/review/preview/fixtures/readback --json`: includes backend
  capture, accepted-tag-to-BWF/Mutagen mapping entries, review counts, dry-run
  validation counts, single-value metadata conflict errors, simulated BWF
  MetaEdit commands, internal Mutagen write intents, copied fixture manifests,
  optional copied-fixture write results, and readback reports.
- `metadata write-apply --json`: includes dry-run/apply mode, reviewed Mutagen
  and BWF MetaEdit write counts, backup/log paths, per-file external command
  results, verification status, and index refresh outcomes.
- `metadata write-undo --json`: includes dry-run/apply mode, source log path,
  restored/skipped/error counts, per-file restore results, and index refresh
  outcomes.
- `groups audit PATH --json`: includes `root`, `db_path`, optional `report_path`, and a versioned report of inferred related sound groups.
- `format audit PATH --json`: includes `root`, `db_path`, optional `report_path`, and a versioned report of format inconsistencies within related groups.
- `scan-errors --json`: includes a scan-error `plan` with classifications and actions.
- `scan-errors --apply PLAN --json`: includes quarantine `result`.
- `search QUERY --json`: includes `query`, `db_path`, and `results`.
- `export --json`: includes `db_path`, `output`, and exported row `count`.
- `dedupe --summary-only --json`: includes duplicate `summary`, `groups`, and no `plan_path`.
- `dedupe --output PLAN --json`: includes duplicate `summary`, `groups`, and explicit `plan_path`.
- `dedupe --review PLAN --json`: includes review counts and output path.
- `dedupe --apply PLAN --json`: includes `result`; default apply quarantines files.
- `packs audit PATH --json`: includes `root`, `db_path`, optional `report_path`, and a versioned report with summary counts, exact duplicate folder groups, and overlap candidates.
- `packs plan --report REPORT --json`: includes `report_path`, optional `plan_path`, and a versioned pack consolidation plan.
- `packs review PLAN --json`: includes review counts and output path.
- `packs apply PLAN --json`: includes dry-run/apply counts, quarantine directory, errors, and optional undo log path.
- `packs undo LOG --json`: includes restore counts, errors, and log path.
- `organize audit PATH --json`: includes `root`, optional `report_path`, and a versioned report with proposed folder renames, report-only nesting candidates, and collision errors.
- `organize review REPORT --json`: includes review counts and output path.
- `organize apply REPORT --json`: includes apply result and undo log path.
- `organize undo LOG --apply --json`: includes undo result.
- `organize nesting-plan REPORT --json`: includes `report_path`, `plan_path`, and a versioned repeated-folder flatten plan.
- `organize nesting-apply PLAN --json`: includes dry-run/apply counts, moved child count, errors, and optional undo log path.
- `organize nesting-undo LOG --apply --json`: includes restored entry and move counts.
- `rename PATH --json`: includes a dry-run `plan`.
- `rename PATH --apply --json`: includes `plan` and `result`.
- `rename --undo LOG --apply --json`: includes undo `result`.
- `similarity crawl PATH --json`: includes root/db/cache paths, run summary,
  descriptor samples, and segment counts.
- `similarity segments PATH --json`: includes cached segment-window summary and
  segment rows.
- `similarity search --file QUERY --json`: includes scope, query descriptor,
  candidate count, and ranked whole-file or segment results.
- `similarity audit PATH --json`: includes scope, threshold, comparison counts,
  and whole-file or segment candidate groups.
- `similarity feedback set/list/clear --json`: includes DB-only review-state
  changes or filtered feedback entries.
- `tag propose PATH --json`: includes candidate UCS proposals, confidence,
  strength/action classification, and per-source evidence from filenames,
  paths, accepted tags, and embedded WAV/RF64 BEXT/RIFF INFO metadata.
- `tag suggest PATH --json`: includes suggestion summary, per-file evidence,
  and optional synonym keyword limit/depth controls.
- `tag plan/review/apply --json`: includes reviewed plan entries, approval
  counts, DB-only apply result, and apply log path.
- `tag sidecar-export/import --json`: includes sidecar paths, exported entries,
  and dry-run/import/skip/error counts.
- `ucs import/info/categories/validate --json`: includes catalog provenance,
  filtered UCS categories, or validation report data.

Compatibility rules:

- Add fields without removing existing fields when possible.
- Bump `schema_version` for breaking changes.
- Do not require consumers to parse Rich terminal output.
- Treat timestamps, absolute paths, mtime values, generated plan names, and quarantine/log directory names as volatile.
