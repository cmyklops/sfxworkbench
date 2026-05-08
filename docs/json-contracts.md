# wavwarden JSON Contracts

JSON output is the stable automation surface for future Textual/Tauri review
tools. Core commands use a common envelope:

```json
{
  "schema_version": 1,
  "command": "scan"
}
```

## Commands

- `clean --json`: includes `result.dry_run`, `removed_files`, `removed_dirs`, and `bytes_freed`.
- `scan --json`: includes `root`, `db_path`, and `result.total/scanned/skipped/errors`.
- `audit --json`: includes `db_path` and aggregate `AuditResult` fields.
- `search QUERY --json`: includes `query`, `db_path`, and `results`.
- `export --json`: includes `db_path`, `output`, and exported row `count`.
- `dedupe --json`: includes duplicate `groups` and the generated `plan_path`.
- `dedupe --apply PLAN --json`: includes `result`; default apply quarantines files.
- `rename PATH --json`: includes a dry-run `plan`.
- `rename PATH --apply --json`: includes `plan` and `result`.
- `rename --undo LOG --apply --json`: includes undo `result`.

## Compatibility Rules

- Add fields without removing existing fields when possible.
- Bump `schema_version` for breaking changes.
- Do not require consumers to parse Rich terminal output.
- Treat timestamps, absolute paths, mtime values, generated plan names, and
  quarantine/log directory names as volatile.
