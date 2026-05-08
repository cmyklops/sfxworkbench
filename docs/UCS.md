# UCS Data Plan

wavwarden currently detects UCS-looking names with a heuristic regex and does
not yet ship official UCS category data.

## Current Behavior

- `wavwarden/ucs.py` is the shared home for current UCS stem parsing.
- `scan` stores `files.is_ucs` using the heuristic `^[A-Z]{2,5}_[A-Z]{2,8}(_|$)`.
- `rename --pattern ucs` safely sanitizes filenames and falls back to `SFX_MISC_...`.
- There is no category catalog, synonym list, or official UCS spreadsheet in the repo yet.

## License Posture

The Universal Category System website describes UCS as a public-domain
initiative and points users to a Dropbox repository for resources. wavwarden
will treat the official UCS category list as usable project data, while keeping
source provenance and attribution visible.

Research note from May 8, 2026:

- The official site says UCS is a "public domain initiative" and says all UCS
  resources are available from its Dropbox-backed repository.
- The official resource download redirects to `UCS Release.zip`.
- That zip includes `UCS v8.2.1 Full List.xlsx`,
  `UCS v8.2.1 Top Level Categories.xlsx`, `Soundminer/_categorylist.csv`,
  category-folder templates, logos, and tool resources.
- The zip listing did not show a dedicated `LICENSE`, `COPYING`, `TERMS`, or
  equivalent legal file.
- The XLSX metadata and shared strings checked locally did not expose a more
  specific license grant than the public-domain language on the official site.

Conclusion: use the official UCS data, but credit it carefully. The repo should
prefer a normalized derived catalog over copying the full upstream release
bundle. Any bundled catalog must include source URL, UCS release version,
generated timestamp, and an attribution note such as:

> Category data derived from the Universal Category System (UCS), a public
> domain initiative. See https://universalcategorysystem.com/.

Keep user-supplied imports as a supported path so studios can update or replace
the catalog without waiting for a wavwarden release.

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

- Support user-supplied UCS CSV/JSON via `--ucs-data` or `WAVWARDEN_UCS_DATA`.
- Cache imported catalogs under `~/.wavwarden/` or in SQLite.
- Add an importer for the official `Soundminer/_categorylist.csv` and
  `UCS v8.2.1 Full List.xlsx` layouts.
- Add a normalized `wavwarden/data/ucs_categories.json` generated from a pinned
  UCS release, with source URL, release version, import timestamp, and
  attribution.
- Do not vendor the full upstream zip, app binaries, logos, videos, or tool
  bundles unless there is a specific product need. The category catalog is the
  useful runtime asset.

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
