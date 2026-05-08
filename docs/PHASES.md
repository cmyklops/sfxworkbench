# wavwarden — Internal Studio Beta Roadmap

wavwarden manages commercial sound-library hygiene: audit, junk cleanup,
indexing, duplicate review, search/export, and reversible renaming. The product
target is an **Internal Studio Beta** before public v1.0.

## Product Principles

- Destructive workflows are dry-run, reviewed, quarantined, or reversible.
- CLI behavior is the source of truth; future TUI/GUI layers consume CLI JSON.
- Reports, plans, and logs are plain JSON/Markdown.
- Audio-content mutation is high risk and stays experimental until proven.
- `sfx` stays the user-facing command for the Internal Studio Beta. `wavwarden`
  remains the project/package name; no `wavwarden` CLI alias is planned before
  beta unless user testing shows confusion.

## Current Phase — Hardened CLI Core

Implemented commands:

```bash
uv run sfx clean PATH
uv run sfx scan PATH
uv run sfx audit
uv run sfx scan-errors --output ~/reports/scan_error_plan.json
uv run sfx scan-errors --apply ~/reports/scan_error_plan.json
uv run sfx search QUERY
uv run sfx export --output library.csv
uv run sfx dedupe --summary-only
uv run sfx dedupe --output ~/reports/dedupe_plan.json
uv run sfx dedupe --review dedupe_plan.json --approve-all
uv run sfx dedupe --apply dedupe_plan.json --require-reviewed
uv run sfx packs audit PATH --output ~/reports/pack_overlap_report.json
uv run sfx organize audit PATH --depth 1 --output ~/reports/organize_report.json
uv run sfx organize audit PATH --pattern redundant-nesting --depth 8 --output ~/reports/nesting_report.json
uv run sfx organize nesting-plan ~/reports/nesting_report.json --output ~/reports/nesting_plan.json
uv run sfx organize review ~/reports/nesting_plan.json --approve-all
uv run sfx organize nesting-apply ~/reports/nesting_plan.json --require-reviewed
uv run sfx organize nesting-apply ~/reports/nesting_plan.json --apply --require-reviewed --log nesting_log.json
uv run sfx organize nesting-undo nesting_log.json --apply
uv run sfx organize review organize_report.json --approve-all
uv run sfx organize apply organize_report.json --require-reviewed --log organize_log.json
uv run sfx organize undo organize_log.json --apply
uv run sfx rename PATH --pattern ucs
uv run sfx rename PATH --pattern safe
uv run sfx rename PATH --pattern ucs --apply --log rename_log.json
uv run sfx rename PATH --pattern safe --apply --allow-partial --log safe_rename_log.json
uv run sfx rename --undo rename_log.json --apply
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
- `scan-errors`: writes a review plan for unreadable indexed files; quarantines
  only obvious artifacts/all-zero blobs by default.
- `dedupe --summary-only`: finds exact MD5 duplicate groups and prints counts without writing a plan.
- `dedupe --output PLAN.json`: writes a reviewed duplicate plan to an explicit path.
- `dedupe --review PLAN.json`: stamps all or selected duplicate groups as approved.
- `dedupe --apply`: validates size/hash and quarantines by default; use `--require-reviewed` to refuse unapproved plans.
- `packs audit`: report-only exact duplicate folder and pack-overlap detection; no filesystem or SQLite mutation.
- `organize audit/review/apply/undo`: safe folder-structure cleanup with review gate, SQLite path updates, and undo log.
- `organize audit --pattern redundant-nesting`: report-only folder-structure review for repeated names, one-child chains, and low-value wrappers.
- `organize nesting-plan/apply/undo`: reviewed flatten workflow for repeated folder names only; dry-run by default and never overwrites.
- `rename`: previews UCS-oriented or safe filename/path changes, refuses collisions, applies with undo log. `--allow-partial` can apply valid entries while keeping unresolved collisions visible in the result.

## Phase 2 — Cleanup Tooling

First priority is `sfx rename --pattern ucs`, with preview/apply/undo behavior.
Pack/folder duplicate detection is the next professional-grade safety layer
after exact file dedupe and filename/path cleanup. It should ship as a reviewed
report/plan/apply workflow before broad folder organization features:

- `sfx packs audit`: detect exact duplicate folders and high-overlap packs. Implemented as report-only.
- `sfx packs plan`: create a reviewed consolidation/quarantine plan.
- `sfx packs apply`: quarantine redundant folders by default, validate hashes
  before moving, update SQLite paths, and write an undo log.

Folder consolidation must not permanently delete by default. Merging unique
files is a later explicit action and must never overwrite existing files.

Folder organization follows the same safety model. First workflow:
`sfx organize audit PATH --depth 1 --pattern strip-leading-numbers`, reporting
top-level folder changes such as `01 Vendor Pack` -> `Vendor Pack` for
alphabetized browsing and easier bulk edits. Apply requires a reviewed report,
refuses collisions, updates SQLite paths, and writes an undo log.

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

One-child chains and low-value wrappers intentionally remain report-only because
they can require subjective merge choices.

Future organization audits should stay report-first:

- related sound groups/collections inferred from path tokens, filename stems,
  numbered takes, channel pairs, UCS categories, metadata, and exact/perceptual
  similarity

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
so large batch runs remain explainable and recoverable.

Metadata writing follows after rename and pack review workflows stabilize:

- `sfx tag --from-filename`
- `sfx tag --from-csv`

Both should use mature libraries/tools for BWAV/iXML writes rather than
hand-rolled binary mutation.

### Directly Useful Open-Source Tools

These projects are strong candidates for supporting wavwarden's planned feature
set without copying unclear or incompatible code into the repo:

| Tool | License posture | wavwarden use |
| --- | --- | --- |
| `wavinfo` | MIT | Richer WAV/RF64/BWF/iXML metadata reads for `scan`, `audit`, and tag planning. |
| BWF MetaEdit | Public domain project | Reference behavior or external backend for BWF metadata validation/writing. |
| `pyacoustid` | MIT | Optional perceptual duplicate candidate detection after exact MD5 dedupe. |
| Textual | MIT | First review UI: duplicate review, rename preview, audit drilldown, approval flows. |
| PANNs inference | MIT | Optional reviewed audio-listening tag suggestions. |
| `pyloudnorm` | MIT | Later loudness analysis for the experimental normalize track. |

Use Chromaprint via `pyacoustid`/`fpcalc` as an optional external capability
rather than vendoring Chromaprint code. Keep ML tagging review-only and outside
the Internal Studio Beta safety promise until privacy, model provenance, and
runtime cost controls are clear.

See [`UCS.md`](UCS.md) for the UCS data plan and
[`METADATA_TAGGING.md`](METADATA_TAGGING.md) for the metadata/audio-suggestion
roadmap. See [`PACK_DEDUPLICATION.md`](PACK_DEDUPLICATION.md) for the
pack/folder duplicate detection and consolidation plan.

`sfx normalize` is later/experimental because sample-rate and channel-layout
changes modify audio content.

## Phase 3 — Review UI

Build a Textual TUI before Tauri. The first TUI should focus on:

- duplicate review
- pack overlap/consolidation review
- rename preview/apply/undo
- audit drilldown
- team-friendly approval workflows

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

## Development Loop

Local and CI validation should use the same Poe tasks:

```bash
uv run --extra dev poe check
uv run --extra dev poe json-smoke
uv run --extra dev poe bench-scan --files 1000 --no-hash
```

The JSON automation surface is documented below. Synthetic scan benchmarking
lives in `scripts/bench_large_library.py`; real-library sampling lives in
`scripts/bench_scan.py`.

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
- `scan-errors --json`: includes a scan-error `plan` with classifications and actions.
- `scan-errors --apply PLAN --json`: includes quarantine `result`.
- `search QUERY --json`: includes `query`, `db_path`, and `results`.
- `export --json`: includes `db_path`, `output`, and exported row `count`.
- `dedupe --summary-only --json`: includes duplicate `summary`, `groups`, and no `plan_path`.
- `dedupe --output PLAN --json`: includes duplicate `summary`, `groups`, and explicit `plan_path`.
- `dedupe --review PLAN --json`: includes review counts and output path.
- `dedupe --apply PLAN --json`: includes `result`; default apply quarantines files.
- `packs audit PATH --json`: includes `root`, `db_path`, optional `report_path`, and a versioned report with summary counts, exact duplicate folder groups, and overlap candidates.
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

Compatibility rules:

- Add fields without removing existing fields when possible.
- Bump `schema_version` for breaking changes.
- Do not require consumers to parse Rich terminal output.
- Treat timestamps, absolute paths, mtime values, generated plan names, and quarantine/log directory names as volatile.
