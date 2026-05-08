# Changelog

All notable changes to wavwarden will be documented in this file.

The format is based on Keep a Changelog, and this project uses semantic
versioning once public releases begin.

## Unreleased

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
