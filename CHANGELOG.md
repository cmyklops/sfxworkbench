# Changelog

All notable changes to wavwarden will be documented in this file.

The format is based on Keep a Changelog, and this project uses semantic
versioning once public releases begin.

## Unreleased

- Added `sfx similarity crawl` as an experimental deterministic audio
  descriptor crawler. It analyzes indexed files, skips unchanged descriptor
  rows by size/mtime/hash anchors, stores results in SQLite, writes an optional
  cache run report, and reports peak/RMS/crest/silence/clipping plus simple
  zero-crossing, transient-density, and spectral centroid/bandwidth/rolloff/
  flatness descriptors. Added `sfx similarity search --file QUERY` to rank
  cached descriptors against a query audio file, including `--scope segment`
  for event-window search. Added RMS-based event segment detection during crawl
  plus `sfx similarity segments` to inspect cached segment windows. Added `sfx
  similarity audit` to produce report-only near-duplicate groups from cached
  descriptor rows, excluding exact MD5 duplicate pairs by default.
- Added preservation-priority evidence for duplicate keep decisions. `sfx
  dedupe --output PLAN --prefer-folder PATH --prefer-extension EXT` and `sfx
  packs plan --prefer-folder PATH` store ordered rule evidence in generated
  plans and use those rules when choosing keep copies.
- Added exact dedupe safe-folder protection. `sfx dedupe --output PLAN
  --safe-folder PATH` records protected folders, prefers protected duplicate
  files as keep copies, and marks protected extra copies as ignored. `sfx
  dedupe --apply PLAN --safe-folder PATH` re-checks protections before
  quarantine or deletion.
- Added pack safe-folder protection. `sfx packs plan --safe-folder PATH`
  records protected folders, prefers protected exact-duplicate folders as keep
  copies, and marks protected sources as ignored. `sfx packs apply
  --safe-folder PATH` also re-checks protections before moving folders so older
  plans cannot quarantine newly protected paths.
- Added `sfx ucs` Typer app with `import`, `info`, and `categories`
  subcommands. Parses the official `Soundminer/_categorylist.csv` shipped in
  `UCS Release.zip`, normalizes 753 UCS v8.2.1 entries into a versioned JSON
  cache at `~/.wavwarden/ucs_catalog.json` with full provenance (source URL,
  release version, import timestamp, attribution). Discovery chain supports
  explicit `--catalog` path, `WAVWARDEN_UCS_DATA` environment variable, and
  the default cache. XLSX import deferred. Catalog data is not yet wired into
  rename or tag_suggest; those integrations follow in subsequent slices.
- Added `sfx tag suggest` report-only command. Composes UCS stem parsing,
  filename heuristics (abbreviation expansion, take-number extraction),
  parent-folder evidence, and related-group membership into versioned tag
  suggestion JSON plans. No filesystem or DB writes. Phase B of
  `docs/METADATA_TAGGING.md`.
- Prepared internal studio beta safety workflows.
- Restored standalone `audit.py`.
- Added JSON output contracts for CLI automation.
- Added quarantine-first dedupe apply behavior.
- Added UCS-oriented rename preview/apply/undo workflow.
- Added development tasks, Ruff checks, CI, and benchmark scripts.
- Added open-source hygiene docs and package metadata.
