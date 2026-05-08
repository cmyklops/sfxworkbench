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
uv run sfx search QUERY
uv run sfx export --output library.csv
uv run sfx dedupe
uv run sfx dedupe --apply dedupe_plan.json
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
- `dedupe`: finds exact MD5 duplicate groups and writes a reviewed plan.
- `dedupe --apply`: validates size/hash and quarantines by default.
- `rename`: previews UCS-oriented names, refuses collisions, applies with undo log.

## Phase 2 — Cleanup Tooling

First priority is `sfx rename --pattern ucs`, with preview/apply/undo behavior.
Metadata writing follows after rename stabilizes:

- `sfx tag --from-filename`
- `sfx tag --from-csv`

Both should use mature libraries/tools for BWAV/iXML writes rather than
hand-rolled binary mutation.

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

The JSON automation surface is documented in [`json-contracts.md`](json-contracts.md).
Synthetic scan benchmarking lives in `scripts/bench_large_library.py`; real-library
sampling lives in `scripts/bench_scan.py`.
