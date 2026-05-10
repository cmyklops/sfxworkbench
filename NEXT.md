# NEXT

Solo-dev working note for the current wavwarden sprint. Keep this short; move
durable decisions into `docs/PHASES.md` only when they survive real-library use.

## Now

- Work from real library findings into reusable, tested CLI workflows.
- Keep filesystem-changing commands plan-first, quarantine-first, or undoable.
- Keep `sfx` as the user-facing command for now; `wavwarden` is the project/package name.
- Use `uv run --extra dev poe check` before every commit.

## Current Library State

- Test copy root: `/Users/mattwesdock/CommercialLibraries`
- Index: `/Users/mattwesdock/.wavwarden/index.db`
- Exact file duplicates: quarantined.
- Safe filename/path cleanup: applied.
- Portable filename/path cleanup: applied.
- Long paths: fixed with conservative path shortening.
- Unicode normalization duplicates: quarantined.
- Pack overlap report: zero exact-hash pack candidates after dedupe.
- Top-level numeric sort-prefix folder organization: applied.
- Numeric-series folder organization: applied for Sound Ideas series folders;
  `13000` is kept under `Vehicles/13000` as an inferred category.
- Vendor/product folder organization: applied for known `A Sound Effect`,
  `Ghosthack`, and `SoundMorph` folders.
- Common-prefix sibling organization: applied for `GDC...` and `CreaturesCK_...`
  folder families.
- Redundant nesting audit: report-only CLI pattern added and run.
- Redundant nesting report: `/Users/mattwesdock/reports/redundant_nesting_report_20260508.json`
  found 52 candidates: 30 one-child chains, 12 repeated folder names, 10 low-value wrappers.
- Repeated-folder-name flatten workflow: implemented and applied.
- Repeated-folder nesting plan: `/Users/mattwesdock/reports/repeated_folder_nesting_plan_20260508.json`
  is reviewed and dry-run clean: 12 folders, 240 child moves, 0 errors.
- Repeated-folder nesting apply: done, 12 folders flattened, 240 child moves,
  undo log at `/Users/mattwesdock/reports/repeated_folder_nesting_log_20260508.json`.
- Single-child nesting apply: done, 18 useful wrappers collapsed across two logs;
  generic child folders such as `Content`, `Designed`, `Source`, and `Sounds` stay report-only.
- Final redundant nesting report: `/Users/mattwesdock/reports/redundant_nesting_report_final_20260508.json`
  found 27 candidates: 23 low-value wrappers and 4 generic single-child chains.
- Strict low-value wrapper apply: done, 2 leaf `Samples` wrappers flattened,
  102 file moves, undo log at `/Users/mattwesdock/reports/low_value_wrapper_log_20260508.json`.
- Latest redundant nesting report: `/Users/mattwesdock/reports/redundant_nesting_report_after_wrappers_20260508.json`
  found 25 candidates: 21 low-value wrappers and 4 generic single-child chains.
- Portable rename apply: done, 832 risky/non-ASCII filename/path renames,
  undo log at `/Users/mattwesdock/reports/portable_rename_log_20260508.json`.
- Portable long-path shortening apply: done, 32 file renames,
  undo log at `/Users/mattwesdock/reports/portable_path_shortening_log_20260508.json`.
- Portable ampersand cleanup: done, `Sound Ideas/Series 9000 Open & Close` renamed
  to `Sound Ideas/Series 9000 Open and Close`, undo log at
  `/Users/mattwesdock/reports/open_and_close_portable_rename_20260508.json`.
- Current indexed filename issues: 0.
- Metadata audit report: `/Users/mattwesdock/reports/metadata_audit_full_20260508.json`.
- Missing BWF/iXML metadata: 22,412 files.
- Unusual sample-rate files: 2,854 files.
- Related groups report: `/Users/mattwesdock/reports/related_groups_report_20260508.json`.
- Related group candidates: 15,331 groups covering 78,735 files.
- Related group mix: 15,163 numbered-sequence groups, 168 channel-set groups,
  147 groups with mixed sample-rate/bit-depth/channel formats.
- Format consistency report: `/Users/mattwesdock/reports/format_audit_20260508.json`.
- Format consistency candidates: 147 related groups covering 3,080 files.
- Format inconsistency mix: 93 sample-rate groups, 32 bit-depth groups,
  61 channel-count groups.
- Tag suggestion (Phase B) report-only command: `sfx tag suggest` implemented.
- First tag suggestion run on full library: 502,735 suggestions across 120,716
  files. Sources: 207,850 path, 157,470 group, 108,091 filename, 29,324
  ucs_stem. Fields: 334,565 description, 149,124 take_number, 9,355
  legacy `category`, 9,355 legacy `subcategory`, 336 channel_position. 31% of suggestions in the high
  confidence bucket (>= 0.8), 69% mid (0.5–0.8). Sample report at
  `/Users/mattwesdock/reports/tag_suggestions_20260508.json` (limit=50 entries).
- UCS catalog import implemented (`sfx ucs import/info/categories`). Imported
  the official UCS v8.2.1 Soundminer CSV: 753 entries, 100 unique CatShort
  prefixes across 82 long-form categories. Cached at
  `/Users/mattwesdock/.wavwarden/ucs_catalog.json` with full provenance.
- UCS catalog-aware tag suggestions implemented. `sfx tag suggest --use-ucs-catalog`
  or `--ucs-catalog PATH` boosts verified `(CatShort, SubCategory)` matches
  from 0.75 heuristic confidence to 0.95 catalog-backed confidence.
- UCS-derived category fields are now provenance fields: `ucs_category` and
  `ucs_subcategory`. They record the filename/catalog claim, not a final
  semantic tag, because terms such as `FIRE/BURST` can mean real fire, guns, or
  magic depending on context.
- UCS validation implemented: `sfx ucs validate [PATH] --db ~/.wavwarden/index.db`
  counts indexed files whose UCS-looking stem matches or misses the catalog.
- UCS validation run on the copied library:
  `/Users/mattwesdock/reports/ucs_validation_20260508.json`. It considered
  120,716 indexed files; 9,355 look UCS-shaped; 197 match the official UCS
  v8.2.1 catalog and 9,158 miss. Misses are dominated by legacy/vendor prefixes
  under Sound Librarian, Sound Ideas, and Black Octopus, not safe catalog matches.
- High-confidence UCS-backed tag suggestion run:
  `/Users/mattwesdock/reports/tag_suggestions_ucs.json`. With
  `--min-confidence 0.8`, it produced 158,061 suggestions across 78,798 files:
  157,470 from related groups and 591 from true UCS catalog matches.
- Tag suggestion and tag plan filters added: `--source` and `--field` can be
  repeated or comma-separated, so review can start with trusted slices such as
  catalog-backed UCS provenance tags before broader group-derived tags.
- Superseded catalog-only semantic review slice generated:
  `/Users/mattwesdock/reports/tag_suggestions_ucs_catalog_fields_20260508.json`
  and `/Users/mattwesdock/reports/tag_plan_ucs_catalog_fields_20260508.json`.
  Do not apply this slice; it used semantic `category`/`subcategory` fields.
- Catalog-only provenance review slice generated:
  `/Users/mattwesdock/reports/tag_suggestions_ucs_provenance_fields_20260509.json`
  and `/Users/mattwesdock/reports/tag_plan_ucs_provenance_fields_20260509.json`.
  Reviewed and applied DB-only: 394 accepted tags covering 197 files, split
  between 197 `ucs_category` and 197 `ucs_subcategory` provenance tags.
  Apply log: `/Users/mattwesdock/reports/tag_apply_ucs_provenance_fields_20260509.json`.
  Sidecar backup:
  `/Users/mattwesdock/reports/accepted_tags_ucs_provenance_20260509.sidecar.json`.
- Lightweight per-file metadata view added: `sfx metadata view QUERY --db ...`.
  It shows indexed audio facts, embedded metadata presence flags, UCS
  parse/catalog match, and accepted DB-only tags for matching indexed files.
- Batch tag-plan review helpers added: `sfx tag summarize PLAN` rolls up a plan
  by field/source/status/value with sample filenames, and `sfx tag review PLAN`
  now supports field/source/value selectors such as `--approve-field`,
  `--reject-value`, and `--only-status pending`.
- Selector smoke check: reviewing
  `/Users/mattwesdock/reports/tag_plan_ucs_provenance_fields_20260509.json`
  with `--approve-field ucs_category --only-status pending --output
  /private/tmp/tag_plan_selector_smoke.json` approved 197 entries in the temp
  plan.
- Product direction shift: semantic UCS tagging should come from corroborated
  evidence, not from filename/UCS-shape heuristics alone. Intrinsic facts such
  as sample rate, bit depth, channels, take number, and channel position remain
  indexed/review facts unless they prove useful as search tags. UCS-looking
  filename claims are provenance (`ucs_*`), while final `category` and
  `subcategory` tags require review or stronger evidence.
- Evidence-fusion tag proposals started: `sfx tag propose PATH` is report-only
  and classifies candidate UCS tags as `strong`, `review`, `weak`, or `blocked`
  from filename, path, accepted UCS provenance, and accepted semantic metadata.
- First whole-library proposal report:
  `/Users/mattwesdock/reports/tag_proposals_evidence_20260509.json`. It
  considered 120,716 indexed files and emitted 38,025 proposals across 15,754
  files with `--min-confidence 0.6 --limit 500`: 5,501 strong and 32,524 review
  in the full summary. Early real-library checks forced a higher-precision
  candidate rule: exact UCS pairs and primary subcategory terms can open
  candidates; category terms only corroborate.
- BWF missing-metadata real-library slice defined and run:
  `/private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_library`.
  Four copied WAV files with no BEXT/iXML were given reviewed `description`
  tags in a slice-only DB, then plan/review/preview/fixture-write/readback/apply
  and undo were exercised successfully. Details are in
  `docs/REAL_LIBRARY_SLICES.md`.
- Existing-BWF originator fill slice defined and run:
  `/private/tmp/wavwarden_bwf_originator_slice_20260509_214926/library`.
  Four copied MAFX WAV files with populated BEXT descriptions and empty
  originator fields were given reviewed `description`, `originator`, and
  `originator_reference` tags in a slice-only DB. Planning skipped all existing
  descriptions, fixture write/readback passed, copied-slice apply verified 8
  written BEXT values, and undo restored the empty originator fields.
- Metadata write conflict detection added: plan/preview now mark conflicting
  accepted values for the same single-value embedded target as `conflict` and
  omit them from fixture/apply commands. Multi-value keyword targets still allow
  multiple values.
- `sfx tag propose` now reads indexed WAV/RF64 BEXT `Description` and RIFF INFO
  `IKEY` fields as report-only `embedded_metadata` evidence for UCS proposals.

Current audit focus:

- Scan errors: cleared with RIFF fallback reader for malformed side chunks.
- Filename issues: cleared.
- Metadata/sample-rate reporting: implemented as report-only.
- Related sound group reporting: implemented as report-only.
- Format consistency reporting: implemented as report-only.
- Tag suggestion (Phase B): implemented as report-only.
- UCS catalog validation: implemented as report-only.
- Vendor/product re-foldering preview/apply/undo: implemented for known vendor
  prefixes via `sfx organize audit --pattern vendor-product-folders`.
- Common-prefix sibling re-foldering preview/apply/undo: implemented for three
  or more sibling folders with the same parsed prefix, such as `GDC...` or
  `CreaturesCK_...`.
- Numeric-series folder preview/apply/undo: implemented for strict numeric
  folders, with built-in Sound Ideas series mappings and filename-token category
  fallback for unknown numeric folders.
- Redundant nesting guard: category parents such as `Vehicles/13000` are treated
  as meaningful and will not be collapsed by the single-child-chain planner.
- Current redundant nesting report:
  `/Users/mattwesdock/reports/redundant_nesting_current_after_guard_20260508.json`
  found 15 review candidates, 0 errors, and 0 safe applyable nesting plans.

## Next

1. Stabilize the metadata writing branch before more feature work.
2. Keep README, `docs/PHASES.md`, and `docs/METADATA_TAGGING.md` aligned with
   the current Mutagen apply/undo behavior.
3. Add JSON contract coverage for `metadata write-apply --json` and
   `metadata write-undo --json`.
4. Run `uv run --extra dev poe check` and `uv run --extra dev poe json-smoke`
   before committing this slice.
5. Continue broadening BWF metadata only through copied real-library slices that
   pass the same write/readback/apply/undo loop.
6. Keep audio conversion and loudness normalization out of scope.

## Later

- similarity-assisted tag proposals after the crawler has more real-library
  validation
- Textual TUI after CLI JSON contracts feel boring, using
  `docs/APP_UI_DIRECTION.md` and the local mockup in `docs/assets/`

## Solo Workflow

- One active feature at a time.
- Prefer report-only first, then reviewed plan/apply.
- Commit small green slices.
- Use parallel agents for bounded codebase reads or external research, not for
  real-library filesystem actions.
