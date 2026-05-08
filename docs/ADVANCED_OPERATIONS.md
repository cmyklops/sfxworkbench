# Advanced Operations Plan

wavwarden's default product posture stays conservative: report first, review
second, quarantine or undoable apply last. Some studios still need deeper tools
for duplicate-heavy databases, processed files, dual-mono assets, and permanent
cleanup. Those workflows belong behind explicit advanced flags, reviewed plans,
and stronger recovery requirements.

This plan captures product lessons from SMDB Companion and similar professional
sound-library maintenance tools while keeping wavwarden's filesystem-first,
JSON-first safety model.

## Product Lessons To Adopt

### Sononym-Inspired Review Ideas

Sononym is a strong reference for similarity-heavy sample browsing and duplicate
review, but wavwarden should translate those ideas into explicit JSON plans
rather than a hidden browser database.

Useful lessons to adopt:

- duplicate review actions should distinguish keep, hide/ignore, link, delete,
  and quarantine rather than treating every duplicate as a removal
- prefer-folder and prefer-extension rules should be first-class keep
  recommendations, with evidence stored in the plan
- near-duplicate and similarity matching should remain report-only until false
  positives are well understood, especially swapped channels and mono mixdowns
- descriptor filters such as length, channels, bit depth, peak, RMS, crest
  factor, and rough brightness can become useful audit/search columns before
  full ML tagging is introduced
- auto-tags, manual tags, hidden tags, UCS tags, aliases, and accepted/rejected
  suggestions should be represented separately in future tag tables
- embedded metadata browsing should include an "actually used fields" view so
  sparse libraries do not drown users in empty metadata columns

### Soundminer-Inspired Similarity Crawler

Soundminer's similarity crawler points to a practical backend shape for
Sononym-like discovery without making wavwarden browser-first. Heavy
audio-content work should run as a separate crawler that can be resumed,
scheduled, CPU-limited, and cached.

Planned behavior:

- `sfx similarity crawl PATH --db DB --cache DIR` analyzes indexed files without
  changing audio or cleanup plans
- unchanged files are skipped using path, size, mtime, and hash anchors
- long files can produce multiple segment/event records
- descriptor and embedding data are stored outside the core `files` table
- `sfx similarity search` and future UI views consume crawler output
- near-duplicate reports stay review-only and clearly label false-positive risk

This belongs after the current beta-safe cleanup and tag-suggestion work. See
[`SIMILARITY.md`](SIMILARITY.md) for the dedicated Phase 2.5 roadmap.

### Safe Folders

Studios need a way to mark locations that should never be modified by automated
plans. Safe folders should apply across dedupe, packs, organize, rename, tag,
dual-mono, and delete workflows.

Planned behavior:

- config-backed safe path list
- CLI override such as `--safe-folder PATH`
- report entries that explain when a candidate was skipped because of a safe
  folder
- tests proving safe folders block quarantine, deletion, rename, and conversion

First implemented slice:

- `sfx dedupe --output PLAN --safe-folder PATH` records protected folders in
  the plan, prefers protected duplicate files as keep copies, and marks
  protected extra copies as ignored rather than remove candidates.
- `sfx dedupe --apply PLAN --safe-folder PATH` combines CLI overrides with
  plan-recorded safe folders and refuses to quarantine or delete protected
  files, including for older plans.
- `sfx packs plan --safe-folder PATH` records protected folders in the plan,
  prefers protected exact duplicates as keep folders, and marks protected
  sources as ignored rather than quarantine candidates.
- `sfx packs apply --safe-folder PATH` combines CLI overrides with plan-recorded
  safe folders and refuses to move protected source folders, including for older
  plans.

### Preservation Priority

When duplicates exist, wavwarden should explain which copy it recommends keeping
and why. The user should be able to tune these rules before plan generation.

Implemented initial CLI rule inputs:

- prefer safe folders
- prefer folders, inspired by Sononym's duplicate review workflow
- prefer file extensions for exact-file dedupe, inspired by Sononym's extension
  preference action

Potential later keep rules:

- prefer paths outside import/download/staging folders
- prefer higher sample rate or bit depth only as tie-breakers, not as a cleanup
  command
- prefer files with BWF/iXML/RIFF INFO metadata
- prefer UCS-valid or catalog-verified filenames
- prefer shorter/cleaner paths when all technical evidence is equal
- prefer newest or oldest mtime when a studio explicitly chooses that rule

Plans should store the ordered rule list, per-candidate scores, and the final
keep-folder/file rationale.

### Presets

Repeatable studio workflows should be named presets over existing commands, not
hidden all-in-one cleanup. Good initial presets:

- `internal-beta`: safe report bundle, no mutation
- `duplicate-review`: exact dedupe plus pack overlap evidence
- `import-review`: compare a new folder against an existing index
- `metadata-prep`: metadata coverage, UCS validation, tag suggestions
- `advanced-forensics`: optional format audit, audio similarity, dual-mono
  candidates

Each preset should still emit the underlying reports and plans.

### Database Compare

Support comparing a candidate import/show dump against a master index before
copying or organizing it.

Planned shape:

```bash
uv run sfx compare PATH --against-db ~/.wavwarden/index.db --output compare_report.json
uv run sfx compare plan compare_report.json --output compare_plan.json
```

The first version should use exact hashes and path/name evidence. Audio
fingerprints can come later as an optional capability.

### Processed-File Detection

Some libraries contain rendered AudioSuite/plugin variants such as normalized,
reverbed, stretched, denoised, or pitch-shifted files. wavwarden should report
these patterns before any cleanup.

Planned behavior:

- detect common suffix/token patterns
- group processed candidates with likely source files
- report method, confidence, and evidence
- never delete or replace processed files by default

## Permanent Disk Deletion

Permanent deletion is useful for copied/staging libraries and for studios that
have already validated quarantine workflows. It must remain advanced and
explicit.

Default deletion ladder:

1. report-only
2. reviewed plan
3. quarantine with undo log
4. quarantine aging report
5. permanent delete from an approved quarantine plan

Planned commands:

```bash
uv run sfx delete plan quarantine_log.json --output delete_plan.json
uv run sfx delete review delete_plan.json --approve-all
uv run sfx delete apply delete_plan.json --require-reviewed --i-understand-permanent-delete
```

Required safety rules:

- refuse direct deletion from live scan reports in the first implementation
- delete only files/folders already moved into a wavwarden quarantine
- require reviewed delete plans
- require a loud, explicit permanent-delete flag
- record immutable delete logs with path, size, hash, source quarantine log, and
  timestamp
- never make permanent deletion part of `internal-beta`

Later, direct disk deletion for exact duplicates can exist only after quarantine
delete is proven and should remain opt-in.

## Dual-Mono Detection And Conversion

Dual-mono handling is audio-content mutation, so it belongs outside the main
beta safety promise. The first implementation should detect candidates only.

### Phase 1: Report

Detect stereo files whose left and right channels are identical or nearly
identical.

Report evidence:

- path, size, mtime, hash
- sample rate, bit depth, duration
- channel count
- exact channel hash when possible
- peak/null-difference metrics for near-identical cases
- confidence: `exact`, `near_exact`, or `review`

Suggested command:

```bash
uv run sfx audio dual-mono audit PATH --db ~/.wavwarden/index.db --output dual_mono_report.json
```

### Phase 2: Plan

Create a reviewed conversion plan. The plan should default to copy-output, not
in-place mutation.

```bash
uv run sfx audio dual-mono plan dual_mono_report.json --output dual_mono_plan.json
uv run sfx audio dual-mono review dual_mono_plan.json --approve-group 1
```

Plan entries should include output path, output format, target channel count,
original file anchors, and rollback/recovery expectations.

### Phase 3: Convert

Conversion should be opt-in and conservative:

```bash
uv run sfx audio dual-mono apply dual_mono_plan.json --require-reviewed --output-root ~/ConvertedMono
```

Initial apply rules:

- write converted mono files to a separate output root by default
- never overwrite existing files
- preserve original files
- write conversion logs with tool versions and technical parameters
- require explicit `--replace-with-backup` before any in-place replacement mode
- update SQLite only for files actually written or moved by wavwarden

In-place replacement, source quarantine, and permanent deletion of originals
should come only after copy-output conversion is well tested on fixtures and
copied real libraries.

## Optional Audio Fingerprints

Exact MD5 dedupe remains the core duplicate signal. Optional fingerprints can
help with re-exported files, metadata-mutated files, and near-duplicates, but
they introduce false positives and extra runtime dependencies.

Planned behavior:

- cache fingerprints in SQLite or sidecar cache
- capture tool name/version
- keep fingerprint matches review-only at first
- never use fingerprint matches for automatic deletion

## Review UI Implications

The Textual UI should make advanced decisions visible rather than hiding them:

- safe-folder badges
- preservation-priority scores and rationale
- side-by-side duplicate candidates
- quarantine age and delete eligibility
- dual-mono evidence preview
- source vs processed-file grouping
- clear separation between report, quarantine, conversion, and permanent delete
