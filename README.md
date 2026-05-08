# wavwarden

Sound library hygiene tools for commercial audio libraries. wavwarden is aimed
at an **Internal Studio Beta** first: safe, reviewable CLI workflows for real
libraries before broader public-product polish.

See [`docs/PHASES.md`](docs/PHASES.md) for the roadmap.

## Install

```bash
uv pip install -e ".[dev]"
```

## Current CLI

Every filesystem-changing command defaults to dry-run or review-first behavior.
Use `--json` on core commands for machine-readable output.

```bash
uv run sfx clean PATH                 # dry-run junk cleanup
uv run sfx clean PATH --apply         # remove junk after review
uv run sfx scan PATH                  # index audio files into SQLite
uv run sfx audit                      # report index health
uv run sfx search QUERY               # FTS filename search
uv run sfx export --output library.csv
uv run sfx dedupe                     # write reviewed duplicate plan
uv run sfx dedupe --apply PLAN.json   # quarantine duplicates by default
uv run sfx rename PATH --pattern ucs  # dry-run UCS-oriented rename preview
uv run sfx rename PATH --pattern ucs --apply --log rename_log.json
uv run sfx rename --undo rename_log.json --apply
```

Default database: `~/.wavwarden/index.db`. Override with `--db`.

## Standalone Phase 0 Audit

`audit.py` is a no-install, zero-dependency auditor for first looks at a library.
It does not import the `wavwarden` package.

```bash
python3 audit.py ~/CommercialLibraries --output-dir ~/reports
python3 audit.py ~/CommercialLibraries --no-hash
python3 audit.py ~/CommercialLibraries --json
```

## Safety Model

- `clean` is dry-run by default and can write a JSON log.
- `dedupe` writes a plan first; `--apply` quarantines by default.
- `rename` previews first, refuses collisions, writes an undo log on apply, and
  can restore from that log.
- `normalize` is intentionally not part of the beta safety promise yet because
  it modifies audio content.

## Tests

```bash
uv run pytest tests/ -v
```

## Development Workflow

Canonical local tasks live in `pyproject.toml` via Poe:

```bash
uv run --extra dev poe test
uv run --extra dev poe lint
uv run --extra dev poe fmt-check
uv run --extra dev poe check
uv run --extra dev poe json-smoke
uv run --extra dev poe bench-scan --files 1000 --no-hash
```

There is also a thin `Makefile` for muscle-memory aliases:

```bash
make test
make lint
make json-smoke
make bench-scan BENCH_LIMIT=1000
```

JSON output contracts are documented in [`docs/json-contracts.md`](docs/json-contracts.md).
