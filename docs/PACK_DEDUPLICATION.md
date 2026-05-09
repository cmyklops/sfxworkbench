# Pack And Folder Duplicate Detection

wavwarden's exact `sfx dedupe` workflow catches byte-identical files across a
library. It supports repeated `--safe-folder PATH` options during plan and
apply so protected duplicate files are kept or ignored rather than removed, and
repeated `--prefer-folder PATH` / `--prefer-extension EXT` options during plan
generation so keep decisions are explainable.
Professional studio libraries also need a higher-level workflow for duplicated
or overlapping packs, bundles, vendor folders, and import dumps.

Pack duplicate detection is a review workflow, not an automatic delete
workflow. The default action should be report or quarantine, with merge behavior
reserved for explicitly reviewed plans. Future permanent deletion must be
advanced-only and should operate first on reviewed quarantine logs, not directly
on live library paths.

## Problem Shape

Common real-library cases:

- The same commercial pack appears in two import locations.
- A bundle folder contains a copy of a pack that also exists under its vendor.
- Two pack versions overlap heavily, but one has extra files.
- Audio files are identical but folder names, sidecars, or metadata differ.
- A pack is nested under redundant vendor/product folders.

Exact file dedupe can remove repeated files, but it cannot explain whether a
whole folder is redundant, partial, newer, or worth preserving.

## Commands

Implemented:

```bash
uv run sfx packs audit PATH --db ~/.wavwarden/index.db --output ~/reports/pack_overlap_report.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --output ~/reports/pack_consolidation_plan.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --safe-folder ~/CommercialLibraries/Master --output ~/reports/pack_consolidation_plan.json
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --prefer-folder ~/CommercialLibraries/Master --output ~/reports/pack_consolidation_plan.json
uv run sfx packs review ~/reports/pack_consolidation_plan.json --approve-group 1
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --require-reviewed
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --safe-folder ~/CommercialLibraries/Master --require-reviewed
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --apply --require-reviewed --log pack_quarantine_log.json
uv run sfx packs undo pack_quarantine_log.json --apply
```

Planned later:

```bash
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --merge-unique-files
uv run sfx delete plan pack_quarantine_log.json --output delete_plan.json
```

The workflow is intentionally staged: audit first, plan second, reviewed apply
last. Apply is dry-run by default; `--apply` is required before any folder is
moved.

## Detection Tiers

### Tier 1: Exact Folder Equivalence

Detect folders whose indexed audio children have the same file hashes. Compare:

- total audio file count
- total byte size
- sorted child MD5 set
- optional relative path/name set
- optional sidecar/document count

Output should distinguish:

- same hashes and same relative names
- same hashes but different relative names
- same hashes with extra/missing sidecars

### Tier 2: Pack Overlap

Detect likely duplicate or version-overlap folders. Compare:

- hash intersection count
- intersection bytes
- percent of smaller folder covered by larger folder
- files unique to each side
- strongest common path/vendor tokens

Suggested default candidate thresholds:

- `>= 95%` of smaller folder by bytes: likely duplicate pack
- `>= 80%` of smaller folder by bytes: likely overlapping pack/version
- below threshold: report only when explicitly requested

### Tier 3: Audio-Similar Candidates

Later/optional. Use perceptual fingerprints only after exact hash workflows are
stable. This can catch same audio with changed metadata or re-exported headers,
but it introduces false positives and external runtime requirements.

## Reviewed Plan Format

Pack consolidation plans are versioned JSON and include:

- `schema_version`
- `generated_at`
- `tool_version`
- `root`
- `db_path`
- source report path
- preservation-priority rules and per-entry evidence when preferences were used
- candidate group id and source type
- source folder path
- recommended keep folder path
- preservation-priority rule scores when configured
- overlap metrics when applicable
- action: `quarantine_folder`, `review`, or `ignore`
- per-file validation anchors: path, relative path, hash, and size
- review status after `sfx packs review`

## Apply Rules

Current apply behavior:

- Refuse unreviewed groups when `--require-reviewed` is set.
- Skip or mark candidates protected by safe folders. `packs plan` accepts
  repeated `--safe-folder PATH` options, prefers protected exact-duplicate
  folders as keep copies, records safe-folder evidence in the plan, and marks
  protected sources as `ignore` instead of quarantine candidates.
- Prefer folders when requested with repeated `--prefer-folder PATH` options and
  record the matching evidence in the generated plan.
- Re-check plan safe folders and any `packs apply --safe-folder PATH` overrides
  before moving a folder, so older plans cannot quarantine a now-protected path.
- Validate every planned path still exists.
- Recheck planned file size and hashes before moving anything.
- Refuse stale plans when the SQLite index now contains additional files under
  the source folder that were not present in the plan.
- Quarantine redundant folders by default.
- Never permanently delete folders by default.
- Never move partial-overlap unique files by default; partial overlaps stay
  review-only in the generated plan.
- Move non-indexed sidecars together with the quarantined folder, preserving the
  source folder as a whole while validating indexed audio anchors.
- Never overwrite existing quarantine targets.
- Update SQLite rows after successful folder moves.
- Write an undo log for folder moves and merge operations.

Permanent deletion should remain an advanced, explicit action after the
quarantine workflow is proven on copied libraries. The first deletion workflow
should delete only from wavwarden quarantine logs, require reviewed delete
plans, and write immutable delete logs with path, size, hash, quarantine source,
and timestamp.

## Preservation Priority

Future pack and duplicate plans should explain why a folder/file is recommended
as the keep copy. The rules should be configurable and stored in the plan.

Useful rule candidates:

- prefer safe folders
- prefer paths outside imports/downloads/staging folders
- prefer files with richer embedded metadata
- prefer higher sample rate or bit depth only as a tie-breaker
- prefer catalog-verified UCS provenance only as a tie-breaker, not as semantic
  truth
- prefer cleaner/shorter paths when technical evidence is otherwise equal

Every keep recommendation should include the winning rule evidence so reviewers
can override it confidently.

## Safe Folders

Safe folders are a cross-cutting protection layer. Pack plans should report when
a duplicate or overlap candidate was skipped because either source or keep path
is protected. Apply should refuse to move protected paths even if an older plan
attempts to do so.

## TUI Direction

The future Textual review UI should make pack overlap understandable:

- side-by-side folder cards
- overlap percent by files and bytes
- same/unique/missing file tabs
- keep-folder recommendation with rationale
- safe-folder badges
- preservation-priority score details
- approve, ignore, or quarantine controls
- quarantine age and permanent-delete eligibility controls
- exportable JSON report for team review

## Acceptance Criteria

Pack/folder duplicate detection is beta-ready when:

- exact duplicate folders can be reported without filesystem changes
- overlapping packs produce stable JSON evidence
- reviewed plans can quarantine redundant folders safely
- safe folders prevent protected paths from being planned or moved
- preservation-priority rules are stored in plans and visible in review output
- merge operations never overwrite existing files
- SQLite paths remain accurate after apply
- undo logs can restore quarantined folder moves
- tests cover exact match, partial overlap, missing files, changed hashes,
  stale indexed files, sidecars, collisions, partial approvals, quarantine,
  undo, and JSON contracts
