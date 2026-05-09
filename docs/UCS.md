# UCS Data Plan

wavwarden can detect UCS-looking names with a heuristic regex and can import the
official UCS category list into a local cache. That data is useful evidence, but
it is not semantic proof. A filename stem like `FIRE_BURST` may be real fire, a
firearm burst, or a magic spell depending on folder context, embedded metadata,
and the audio.

## Current Behavior

- `wavwarden/ucs.py` is the shared home for current UCS stem parsing.
- `scan` stores `files.is_ucs` using the heuristic `^[A-Z]{2,5}_[A-Z]{2,8}(_|$)`.
- `rename --pattern ucs` safely sanitizes filenames and falls back to `SFX_MISC_...`.
- `sfx ucs import` can cache a user-supplied official UCS category CSV under
  `~/.wavwarden/ucs_catalog.json`.
- UCS-derived `ucs_category` and `ucs_subcategory` values are provenance fields.
  They record a filename/catalog claim and should not be treated as final
  `category` or `subcategory` tags without corroborating evidence.

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

Implemented API (heuristic, in `wavwarden/ucs.py`):

- `looks_ucs(stem: str) -> bool`
- `parse_ucs_stem(stem: str) -> UcsParseResult`

Implemented API (catalog import, in `wavwarden/ucs_catalog.py`):

- `parse_soundminer_csv(path, *, release_version=None) -> tuple[UcsCatalog, int]`
- `import_catalog(source_path, *, output_path=None, release_version=None) -> tuple[UcsImportResult, UcsCatalog]`
- `save_catalog(catalog, output_path) -> None`
- `load_catalog(path=None) -> UcsCatalog | None` — discovery chain:
  explicit path → `WAVWARDEN_UCS_DATA` env var → `~/.wavwarden/ucs_catalog.json`
  cache → `None`
- `resolve_catalog_path(path=None) -> Path | None` — resolves the same discovery
  chain without reading JSON.
- `lookup_entry(catalog, cat_short, subcategory) -> UcsEntry | None`
- `query_categories(catalog, *, category=None, cat_short=None) -> UcsCategoriesQuery`
- `default_cache_path() -> Path` — returns `~/.wavwarden/ucs_catalog.json`

Implemented API (catalog-aware suggestions/validation):

- `tag_suggest.suggest_from_ucs_stem(stem, catalog=None)` — when a catalog is
  supplied, verified `(CatShort, SubCategory)` matches emit `ucs_catalog`
  provenance suggestions for `ucs_category` and `ucs_subcategory`.
- `tag_propose.build_tag_proposal_report(...)` — fuses UCS catalog terms with
  filename, path, accepted provenance, and accepted semantic metadata into
  report-only candidate UCS proposals.
- `ucs_validate.build_ucs_validation_report(db_path, root=None, catalog_path=None)`
  counts indexed filenames whose parsed `(CatShort, SubCategory)` matches the
  loaded catalog.

Implemented CLI:

```bash
uv run sfx ucs import ~/Desktop/_categorylist.csv --release-version v8.2.1
uv run sfx ucs info
uv run sfx ucs categories --cat-short AMB
uv run sfx ucs categories --category AMBIENCE --json
uv run sfx ucs validate --db ~/.wavwarden/index.db --json
uv run sfx tag propose PATH --db ~/.wavwarden/index.db --min-confidence 0.6 --output ~/reports/tag_proposals.json
uv run sfx tag suggest PATH --use-ucs-catalog --min-confidence 0.8 --json
uv run sfx tag suggest PATH --ucs-catalog ~/.wavwarden/ucs_catalog.json --output ~/reports/tag_suggestions_ucs.json
```

Future data behavior:

- Support user-supplied UCS CSV/JSON via `--ucs-data` or `WAVWARDEN_UCS_DATA`.
- Cache imported catalogs under `~/.wavwarden/` or in SQLite.
- Add an importer for the official `UCS v8.2.1 Full List.xlsx` layout.
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

- preserve existing filenames unless the user asks for cleanup
- keep UCS catalog/category data as metadata evidence, not a reason to force
  UCS-looking filenames
- show confidence and evidence in any future metadata/rename plan
- fall back to `SFX_MISC_...` when uncertain
- never overwrite and always write undo logs

## References

- Universal Category System: https://universalcategorysystem.com/
- Example third-party UCS tooling pattern: https://pkg.go.dev/github.com/brettbuddin/ucsrename/ucs
