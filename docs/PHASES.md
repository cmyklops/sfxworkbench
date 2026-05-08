# wavwarden — Internal Studio Beta Roadmap

wavwarden manages commercial sound-library hygiene: audit, junk cleanup,
indexing, duplicate review, search/export, and reversible renaming. The product
target is an **Internal Studio Beta** before public v1.0.

## Product Principles

- Destructive workflows are dry-run, reviewed, quarantined, or reversible.
- CLI behavior is the source of truth; future TUI/GUI layers consume CLI JSON.
- Reports, plans, and logs are plain JSON/Markdown.
- Audio-content mutation is high risk and stays experimental until proven.

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
uv run sfx rename PATH --pattern ucs
uv run sfx rename PATH --pattern ucs --apply --log rename_log.json
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
- `rename`: previews UCS-oriented names, refuses collisions, applies with undo log.

## Phase 2 — Cleanup Tooling

First priority is `sfx rename --pattern ucs`, with preview/apply/undo behavior.
Metadata writing follows after rename stabilizes:

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
roadmap.

`sfx normalize` is later/experimental because sample-rate and channel-layout
changes modify audio content.

## Phase 3 — Review UI

Build a Textual TUI before Tauri. The first TUI should focus on:

- duplicate review
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
- `rename PATH --json`: includes a dry-run `plan`.
- `rename PATH --apply --json`: includes `plan` and `result`.
- `rename --undo LOG --apply --json`: includes undo `result`.

Compatibility rules:

- Add fields without removing existing fields when possible.
- Bump `schema_version` for breaking changes.
- Do not require consumers to parse Rich terminal output.
- Treat timestamps, absolute paths, mtime values, generated plan names, and quarantine/log directory names as volatile.
