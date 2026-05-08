# Pack And Folder Duplicate Detection

wavwarden's exact `sfx dedupe` workflow catches byte-identical files across a
library. Professional studio libraries also need a higher-level workflow for
duplicated or overlapping packs, bundles, vendor folders, and import dumps.

Pack duplicate detection is a review workflow, not an automatic delete
workflow. The default action should be report or quarantine, with merge behavior
reserved for explicitly reviewed plans.

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
```

Planned:

```bash
uv run sfx packs plan --report ~/reports/pack_overlap_report.json --output ~/reports/pack_consolidation_plan.json
uv run sfx packs review ~/reports/pack_consolidation_plan.json --approve-group 1
uv run sfx packs apply ~/reports/pack_consolidation_plan.json --require-reviewed
```

Plan/apply command names may change before implementation, but the workflow
should remain: audit first, plan second, reviewed apply last.

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

Pack consolidation plans should be versioned JSON and include:

- `schema_version`
- `generated_at`
- `tool_version`
- `root`
- `db_path`
- candidate group id
- source folder path
- recommended keep folder path
- overlap metrics
- action: `report`, `quarantine_folder`, `merge_unique_files`, or `ignore`
- per-file evidence for matching and unique files
- review status and reviewer note

## Apply Rules

Default apply behavior:

- Refuse unreviewed groups when `--require-reviewed` is set.
- Validate every planned path still exists.
- Recheck file count, size, and hashes before moving anything.
- Quarantine redundant folders by default.
- Never permanently delete folders by default.
- Never overwrite files when merging unique files.
- Update SQLite rows after successful folder moves.
- Write an undo log for folder moves and merge operations.

Permanent deletion should remain an advanced, explicit action after the
quarantine workflow is proven on copied libraries.

## TUI Direction

The future Textual review UI should make pack overlap understandable:

- side-by-side folder cards
- overlap percent by files and bytes
- same/unique/missing file tabs
- keep-folder recommendation with rationale
- approve, ignore, or quarantine controls
- exportable JSON report for team review

## Acceptance Criteria

Pack/folder duplicate detection is beta-ready when:

- exact duplicate folders can be reported without filesystem changes
- overlapping packs produce stable JSON evidence
- reviewed plans can quarantine redundant folders safely
- merge operations never overwrite existing files
- SQLite paths remain accurate after apply
- undo logs can restore quarantined folder moves
- tests cover exact match, partial overlap, missing files, changed hashes,
  sidecars, collisions, quarantine, undo, and JSON contracts
