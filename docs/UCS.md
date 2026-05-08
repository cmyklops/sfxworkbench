# UCS Data Plan

wavwarden currently detects UCS-looking names with a heuristic regex and does
not ship official UCS category data.

## Current Behavior

- `wavwarden/ucs.py` is the shared home for current UCS stem parsing.
- `scan` stores `files.is_ucs` using the heuristic `^[A-Z]{2,5}_[A-Z]{2,8}(_|$)`.
- `rename --pattern ucs` safely sanitizes filenames and falls back to `SFX_MISC_...`.
- There is no category catalog, synonym list, or official UCS spreadsheet in the repo.

## License Posture

The Universal Category System website describes UCS as a public-domain
initiative and points users to a Dropbox repository for resources. Before
bundling official spreadsheets or derived JSON, verify the redistribution terms
of the exact resource file and version.

Until that is verified, wavwarden should support user-supplied UCS data rather
than vendoring the official catalog.

## Integration Plan

Keep expanding the dedicated `wavwarden/ucs.py` module so UCS parsing does not
live separately in feature modules.

Implemented API:

- `looks_ucs(stem: str) -> bool`
- `parse_ucs_stem(stem: str) -> UcsParseResult`

Suggested API:

- `load_ucs_catalog(path: Path | None = None) -> UcsCatalog`
- `suggest_category(filename: str, folders: list[str]) -> UcsSuggestion`

Suggested CLI:

```bash
uv run sfx ucs validate --db ~/.wavwarden/index.db --json
uv run sfx ucs import ~/Downloads/ucs.csv --json
uv run sfx rename PATH --pattern ucs --ucs-data ~/Downloads/ucs.csv
```

Suggested data behavior:

- Prefer user-supplied UCS CSV/JSON via `--ucs-data` or `WAVWARDEN_UCS_DATA`.
- Cache imported catalogs under `~/.wavwarden/` or in SQLite.
- If redistribution is allowed, add a normalized `wavwarden/data/ucs_categories.json`.
- If redistribution is not allowed, ship only schema/docs and keep the importer.

Suggested DB additions:

- keep `files.is_ucs` for compatibility
- add nullable UCS fields or a linked `file_ucs` table later
- store source as `heuristic`, `user_catalog`, or `official_catalog`

## Rename Behavior

Data-backed rename should remain preview-first:

- use catalog category when confidence is high
- show confidence and evidence in the rename plan
- fall back to `SFX_MISC_...` when uncertain
- never overwrite and always write undo logs

## References

- Universal Category System: https://universalcategorysystem.com/
- Example third-party UCS tooling pattern: https://pkg.go.dev/github.com/brettbuddin/ucsrename/ucs
