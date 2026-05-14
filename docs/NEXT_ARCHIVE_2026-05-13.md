# NEXT

Solo-dev working note for the current sfxworkbench sprint. Keep this short; move
durable decisions into `docs/PHASES.md` only when they survive real-library use.

## Now

- Work from real library findings into reusable, tested CLI workflows.
- Keep filesystem-changing commands plan-first, quarantine-first, or undoable.
- Keep `sfx` as the user-facing command for now; `sfxworkbench` is the project/package name.
- Use `uv run --extra dev poe check` before every commit.
- Current TUI bug/performance follow-up is tracked in `docs/TUI_FOLLOWUP.md`.

## Current Library State

- Test copy root: `/Users/mattwesdock/CommercialLibraries`
- Index: `/Users/mattwesdock/.sfxworkbench/index.db`
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
  `/Users/mattwesdock/.sfxworkbench/ucs_catalog.json` with full provenance.
- UCS catalog-aware tag suggestions implemented. `sfx tag suggest --use-ucs-catalog`
  or `--ucs-catalog PATH` boosts verified `(CatShort, SubCategory)` matches
  from 0.75 heuristic confidence to 0.95 catalog-backed confidence.
- UCS-derived category fields are now provenance fields: `ucs_category` and
  `ucs_subcategory`. They record the filename/catalog claim, not a final
  semantic tag, because terms such as `FIRE/BURST` can mean real fire, guns, or
  magic depending on context.
- UCS validation implemented: `sfx ucs validate [PATH] --db ~/.sfxworkbench/index.db`
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
  `/private/tmp/sfxworkbench_bwf_slice_20260509_113309/missing_bext_library`.
  Four copied WAV files with no BEXT/iXML were given reviewed `description`
  tags in a slice-only DB, then plan/review/preview/fixture-write/readback/apply
  and undo were exercised successfully. Details are in
  `docs/REAL_LIBRARY_SLICES.md`.
- Existing-BWF originator fill slice defined and run:
  `/private/tmp/sfxworkbench_bwf_originator_slice_20260509_214926/library`.
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
- Synonym keyword suggestions now support `--synonym-limit` and
  `--synonym-depth` on `sfx tag suggest` and `sfx tag plan`, so terminal tests
  can choose how many terms to add and how far down the ordered synonym lists to
  go.

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

Progress: 6/6 complete for the Internal Beta Baseline sprint.

1. Done: remove ignored root-level generated apply logs and keep
   `metadata_write_apply_log_*.json` / `tag_apply_log_*.json` ignored.
2. Done: add CI coverage for Python 3.10 and 3.11.
3. Done: tighten metadata write safety so apply validates current on-disk file
   anchors, not only stale SQLite rows.
4. Done: tighten metadata write undo so logs record pre/post anchors and undo
   refuses targets changed after apply.
5. Done: refresh README/PHASES drift around RIFF INFO `IKEY` metadata writes
   and embedded metadata apply/undo audit coverage.
6. Done: run clean install checks, full local validation, JSON smoke, and one
   real-library beta audit bundle.

Internal Beta Baseline validation:

- Clean install checks:
  - `uv sync --extra dev`
  - `uv sync --extra metadata --extra dev`
  - `uv run sfx --help`
- Local validation:
  - `uv run pytest tests/test_metadata_write.py tests/test_json_contracts.py -v`
    passed: 42 tests.
  - `uv run --extra dev poe check` passed: 317 tests plus lint/format.
  - `uv run --extra dev poe json-smoke` passed: 26 tests.
- Real-library beta audit:
  - Output dir:
    `/private/tmp/sfxworkbench_beta_audit_sprint_20260510`.
  - Command:
    `uv run --extra dev poe beta-audit /Users/mattwesdock/CommercialLibraries --output-dir /private/tmp/sfxworkbench_beta_audit_sprint_20260510`
  - Summary: 120,716 files scanned; 0 scan errors; 0 filename issues; 22,412
    missing metadata rows; 2,854 unusual sample-rate files; 15,331 related
    groups; 0 pack overlap candidates; pack apply dry-run planned 0 moves.

Tag Proposal Precision sprint: 5/5 complete.

1. Done: tighten `tag propose` candidate-opening rules for noisy embedded/path
   subcategory terms such as `metal` and `tonal`.
2. Done: add regression coverage for embedded metadata that has category +
   subcategory context, embedded-only noisy terms, and ambiguous path fan-out
   such as `Cinematic Metal Impacts`.
3. Done: add BWF-focused CLI JSON contract coverage for
   `metadata write-apply --json`, including BWF MetaEdit `write_results`, BEXT
   readback, and RIFF INFO `IKEY` keyword readback.
4. Done: add a dedicated Python 3.11 CI job for optional `metadata` extras
   without expanding the full Python matrix.
5. Done: run real-library `tag propose` calibration and record before/after
   totals.

Tag proposal calibration:

- Baseline report:
  `/Users/mattwesdock/reports/tag_proposals_embedded_20260509_232710.json`.
- New report:
  `/private/tmp/tag_proposals_precision_20260510.json`.
- Command:
  `uv run sfx tag propose /Users/mattwesdock/CommercialLibraries --db /Users/mattwesdock/.sfxworkbench/index.db --catalog /Users/mattwesdock/.sfxworkbench/ucs_catalog.json --min-confidence 0.6 --limit 500 --output /private/tmp/tag_proposals_precision_20260510.json --json`
- Before: 178,400 proposals across 46,756 files; 16,791 strong and 161,609
  review.
- After: 79,674 proposals across 41,699 files; 13,201 strong and 66,473 review.
- Delta: -98,726 total proposals, -95,136 review proposals, -3,590 strong
  proposals, and -5,057 files with proposals.
- Spot-check finding: the obvious `metal` fan-out into unrelated
  DOORS/DRAWERS/RAIN/WINDOWS candidates is removed from the early sample, while
  useful METAL/TONAL, UI/CLICK, AMBIENCE/ROOM TONE, and similar corroborated
  candidates remain. Remaining noisy examples include generic `tone`, `walla`,
  `sea`, and `loop` cases that should be calibrated separately.

Validation:

- `uv run pytest tests/test_tag_propose.py tests/test_json_contracts.py -v`
  passed: 21 tests.
- `uv run --extra dev poe check` passed: 321 tests plus lint/format.
- `uv run --extra dev poe json-smoke` passed: 27 tests.
- `uv sync --extra metadata --extra dev` passed.
- `uv run pytest tests/test_audio.py tests/test_metadata_backends.py tests/test_metadata_write.py -v`
  passed: 38 tests.

Metadata Write Proof sprint: 4/4 complete.

1. Done: make Mutagen embedded-write planning container-specific instead of
   assuming every easy tag key works for every tagged format.
2. Done: add existing Mutagen target-value checks so non-empty fields default
   to `skip_existing`, with explicit `replace_tag` entries only under
   `--replace-existing`.
3. Done: add generated real-format fixture coverage for FLAC, Ogg/Vorbis,
   Ogg/Opus, MP3, M4A when local encoders are available, plus AIFF/AIF
   unsupported-plan coverage.
4. Done: add a real FLAC apply/readback/undo test with pre/post MD5 anchors.

Validation:

- `uv run pytest tests/test_metadata_write.py -v` passed: 29 tests.
- `uv run --extra dev poe json-smoke` passed: 27 tests.
- `uv run --extra dev poe check` passed: 325 tests plus lint/format.

Tag Proposal Diagnostics sprint: 5/5 complete.

1. Done: calibrate remaining broad proposal terms: `tone`, `room`, `walla`,
   `sea`, `loop`, and high-volume material terms now require category context
   before opening UCS candidates from filename/path/semantic evidence.
2. Done: add proposal summary diagnostics for top opening tokens and fan-out
   counts, plus prune newly visible low-value tokens: `general`, `sample`,
   `of`, and `by`.
3. Done: design and start shared safe-folder config across dedupe, packs,
   organize, rename, and metadata workflows. Dedupe and packs now accept
   `--config PATH` and merge config-backed safe folders with CLI overrides;
   organize, rename, and metadata-write remain the next rollout surfaces.
4. Done: decide similarity validation should run as a manual beta-audit option
   for now, not as overnight automation by default.
5. Done: review CI runtime after the metadata-extras job lands on GitHub, and
   fix the Linux-only similarity feedback test ordering assumption found during
   that review.

CI runtime review:

- Latest inspected run: GitHub Actions run `25620643129`, "Prove metadata write
  format support", created `2026-05-10T05:19:51Z`.
- `metadata-extras` succeeded. Total job wall time was about 14 seconds; the
  metadata test step itself ran in about 4 seconds after
  `uv sync --extra metadata --extra dev`.
- The main `pytest (3.11)` job failed after about 28 seconds, not because of
  metadata extras. Failure was
  `tests/test_similarity.py::test_similarity_feedback_tracks_segment_relationships`.
- Root cause: similarity feedback intentionally canonicalizes pair ordering so
  `A/B` and `B/A` are a single relationship, but the test expected input
  left/right segment orientation. Linux scan/order exposed the assumption.
- Fixed the test to assert the stored segment relationship as a set of
  `(path, segment_index)` pairs instead of incidental left/right orientation.

Validation:

- `uv run pytest tests/test_similarity.py::test_similarity_feedback_tracks_segment_relationships -v`
  passed: 1 test.
- `uv run pytest tests/test_audio.py tests/test_metadata_backends.py tests/test_metadata_write.py -v`
  passed: 42 tests.
- `uv run --extra dev poe check` passed: 335 tests plus lint/format.
- `uv run --extra dev poe json-smoke` passed: 27 tests.

Similarity validation decision:

- Added `--similarity-validation` to the internal beta-audit harness as the
  explicit validation entrypoint; `--include-similarity` remains supported.
- Beta-audit manifests now record `similarity_validation_mode:
  manual_beta_audit` and `similarity_automation_recommendation:
  defer_overnight_automation_until_manual_validation_passes`.
- Documented the decision in `docs/SIMILARITY.md`: collect manual real-library
  runtime, cache-size, segment-count, and false-positive evidence before adding
  scheduled overnight automation.

Validation:

- `uv run pytest tests/test_internal_beta_audit.py -v` passed: 4 tests.
- `uv run --extra dev poe check` passed: 335 tests plus lint/format.
- `uv run --extra dev poe json-smoke` passed: 27 tests.

Safe-folder config slice:

- Added shared preservation config loading in `sfxworkbench/preservation.py`.
- Supported JSON shape:
  `{"safe_folders": ["~/CommercialLibraries/Master"], "preservation": {"prefer_folders": [], "prefer_extensions": ["wav"]}}`.
- Wired config rules into `sfx dedupe --config`, `sfx dedupe --apply --config`,
  `sfx packs plan --config`, and `sfx packs apply --config`.
- Pack planning intentionally ignores config extension preferences because pack
  decisions are folder-level.
- Completed the shared safe-folder rollout for remaining beta mutation
  surfaces: `sfx organize audit/apply`, `sfx organize nesting-plan/nesting-apply`,
  `sfx rename`, and `sfx metadata write-apply` now accept `--config` and block
  protected move/rename/flatten/write entries. Apply paths re-check config-backed
  safe folders so older reports and plans cannot mutate protected audio.

Validation:

- `uv run pytest tests/test_preservation.py tests/test_dedupe.py tests/test_packs.py tests/test_json_contracts.py -v`
  passed: 64 tests.
- `uv run --extra dev pytest tests/test_preservation.py tests/test_rename.py tests/test_organize.py tests/test_metadata_write.py -v`
  passed: 85 tests, 3 skipped.
- `uv run --extra dev poe check` passed: 344 tests plus lint/format.
- `uv run --extra dev poe json-smoke` passed: 30 tests.

Proposal diagnostics calibration:

- Previous report:
  `/private/tmp/tag_proposals_precision_20260510.json`.
- New report:
  `/private/tmp/tag_proposals_broad_token_sprint_final_20260510.json`.
- Command:
  `uv run sfx tag propose /Users/mattwesdock/CommercialLibraries --db /Users/mattwesdock/.sfxworkbench/index.db --catalog /Users/mattwesdock/.sfxworkbench/ucs_catalog.json --min-confidence 0.6 --limit 500 --output /private/tmp/tag_proposals_broad_token_sprint_final_20260510.json --json`
- Before: 79,674 proposals across 41,699 files; 13,201 strong and 66,473
  review.
- After: 75,974 proposals across 40,744 files; 12,982 strong and 62,992
  review.
- Delta: -3,700 total proposals, -3,481 review proposals, -219 strong
  proposals, and -955 files with proposals.
- New diagnostics show the next calibration hotspots without manual JSON
  spelunking: `whoosh` from filename/path, `construction` from path, and
  high-fanout `impact`/`movement` candidates that are now partly blocked but
  still worth reviewing.

Validation:

- `uv run pytest tests/test_tag_propose.py tests/test_json_contracts.py -v`
  passed: 24 tests.
- `uv run --extra dev poe check` passed: 327 tests plus lint/format.
- `uv run --extra dev poe json-smoke` passed: 27 tests.

Terminal-test calibration:

- Report:
  `/Users/mattwesdock/reports/tag_proposals_embedded_20260509_232710.json`.
- Command:
  `uv run sfx tag propose /Users/mattwesdock/CommercialLibraries --db /Users/mattwesdock/.sfxworkbench/index.db --catalog /Users/mattwesdock/.sfxworkbench/ucs_catalog.json --min-confidence 0.6 --limit 500 --output /Users/mattwesdock/reports/tag_proposals_embedded_20260509_232710.json`
- Summary: 120,716 files considered; 178,400 proposals across 46,756 files;
  16,791 strong and 161,609 review.
- Compared with the pre-embedded report
  `/Users/mattwesdock/reports/tag_proposals_evidence_20260509.json`, proposals
  rose from 38,025 to 178,400 and files with proposals rose from 15,754 to
  46,756.
- In the saved 500-entry sample, 802 proposals included `embedded_metadata`
  evidence: 174 strong and 628 review.
- Spot-check finding: embedded BEXT/RIFF INFO helps real matches such as
  ambience/traffic and rain/vegetation, but it also broadens noisy generic
  terms such as `metal` and `tonal` into too many review candidates.
- Terminal testing guidance: start with high-confidence proposal review
  (`--min-confidence 0.8`) and treat the broad `review` bucket as diagnostic
  until candidate opening is tightened further.

Textual TUI Alpha 0:

- Added optional `tui` extra with Textual.
- Added `sfx tui` as a read-only alpha review workbench.
- Added `sfxworkbench/tui_data.py` adapters for dashboard signals, review queue
  counts, indexed-file rows, safe-folder firewall visibility, and JSON
  report/plan/log summaries.
- Added `sfxworkbench/tui_app.py` with Dashboard, Queues, Files, Plans, and
  Firewall tabs.
- Current scope is intentionally read-only; approve/apply/undo workflows should
  wait until the review model has been tested against real indexed libraries.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed: 4 tests.
- `uv run --extra tui --extra dev sfx tui --help` passed.
- `uv run --extra tui --extra dev python -c "from sfxworkbench.tui_app import run_tui; from sfxworkbench.tui_data import dashboard_metrics; print(run_tui.__name__, len(dashboard_metrics()))"` passed.
- `uv run --extra tui --extra dev poe check` passed: 348 tests plus lint/format.
- `uv run --extra tui --extra dev poe json-smoke` passed: 30 tests.

Textual TUI Alpha 1:

- Added file search to the Files tab with FTS search and literal path fallback.
- Added a selected-file detail pane with indexed facts, filename issues,
  accepted DB-only tags, duplicate count, and similarity segment count.
- Added queue item browsing for scan errors, filename issues, long paths,
  Unicode normalization, missing metadata, unusual sample rates, duplicate
  groups, UCS-looking filenames, DB-only tags, and similarity feedback.
- Added plan-detail rows beneath JSON report/plan/log summaries for entries,
  groups, errors, and candidates.
- Kept the TUI read-only; queue item selection only pivots the file browser to
  the selected path.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed: 7 tests.
- `uv run --extra tui --extra dev poe check` passed: 351 tests plus lint/format.

Textual TUI Alpha 2:

- Added queue-item filtering on the selected queue, with queue-specific helper
  text for metadata gaps, duplicates, tags, and similarity feedback.
- Expanded metadata queue rows with sample rate, bit depth, channel count, and
  duration so missing-metadata triage has useful context before opening detail.
- Added keyboard shortcuts for file search, queue filter, reset filters, and
  focusing the queues/items/files/plans panes.
- Compacted long paths in file, queue, and plan tables while keeping full paths
  in the underlying selected rows and detail pane.
- Kept the TUI read-only; no approve/apply/undo controls were added.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed: 8 tests.
- `uv run --extra tui --extra dev poe check` passed: 352 tests plus lint/format.

Textual TUI visual identity audit:

- Standardized the alpha TUI on Textual's default dark theme with explicit
  sfxworkbench dark surface, border, and foreground colors.
- Restyled table headers, alternating rows, hover state, and selected-row cursor
  for high contrast during dense review sessions.
- Restyled inputs, detail panes, notes, and pane titles so search/filter states
  remain legible against the dark background.
- Restyled the footer keybind HUD explicitly so changing theme state does not
  make shortcut labels disappear.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed: 8 tests.
- `uv run --extra tui --extra dev poe check` passed: 352 tests plus lint/format.

Textual TUI first-run information architecture pass:

- Added a `Start` tab that turns library state into a suggested first-pass
  order: import health, exact duplicates, metadata gaps, UCS provenance,
  accepted tags, then generated reports/logs.
- Renamed top-level surfaces from internal implementation language to user
  tasks: `Dashboard` -> `Start`, `Queues` -> `Review`, `Plans` -> `Reports`.
- Consolidated the old `Firewall` page into `Start` as `Protected Folders`,
  since it is a guardrail users should see early rather than a separate place
  to operate.
- Renamed review-table labels from `Queue`/`Queue Items` to `Review List` and
  `Items to Inspect`.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed: 9 tests.
- `uv run --extra tui --extra dev poe check` passed: 353 tests plus lint/format.

Textual TUI guided workbench pass:

- Start rows are now actionable: selecting a first-pass step jumps to the
  relevant Review list or to Reports.
- Review lists now carry lifecycle lanes: Health, Cleanup, Metadata, Naming,
  and Decisions.
- Selecting a Review item now opens that file in Files and seeds Reports with
  the selected filename as context.
- Reports can filter JSON reports/plans/logs by context text, and reset filters
  restores the full report list.
- Clear/empty Review states now explain what a zero means instead of showing a
  generic empty row.
- The Start table receives initial keyboard focus so a first-time user can move
  directly from the suggested order into the workbench.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed: 9 tests.
- `uv run --extra tui --extra dev poe check` passed: 353 tests plus lint/format.
- Real-library TUI launch smoke passed against
  `/Users/mattwesdock/reports/sfxworkbench_beta_audit/index.db`.

Textual TUI payoff ranking pass:

- Reframed the Start tab as a payoff-ranked worklist instead of a procedural
  checklist.
- Added explicit payoff levels and "why it matters" text so users can start
  with the highest-impact review/change lanes: import health, exact duplicates,
  metadata gaps, UCS provenance, accepted tags, then reports/logs.
- Kept the TUI read-only; selecting a row still jumps to the relevant review
  surface without creating a hidden mutation path.

Validation:

- `.venv/bin/python -m pytest tests/test_tui_data.py -v` passed: 9 tests.
- `.venv/bin/python -m ruff check sfxworkbench/tui_data.py sfxworkbench/tui_app.py tests/test_tui_data.py` passed.
- `.venv/bin/python -m ruff format --check sfxworkbench/tui_data.py sfxworkbench/tui_app.py tests/test_tui_data.py` passed.

Textual TUI actionable workbench pass:

- Added CLI next actions to the payoff-ranked Start rows, so each first-pass
  item points to the exact command or report path to create next.
- Added queue-specific next steps to the Review table for scan errors,
  filename cleanup, duplicates, metadata gaps, UCS validation, accepted tags,
  and similarity decisions.
- Split JSON summaries in Reports into `Report`, `Plan`, and `Log` categories.
- Expanded file detail with stem/extension facts and file-specific next actions
  for scan errors, unsafe names, duplicates, metadata gaps, UCS-looking names,
  and accepted DB-only tags.
- Kept the TUI read-only; no approve/apply/undo controls were added.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed: 9 tests.
- `uv run --extra dev poe json-smoke` passed: 30 tests.
- `uv run --extra dev poe check` passed: 350 tests plus lint/format.

sfxworkbench packaging/install validation:

- Replaced deprecated `typer[all]` dependency with explicit `typer>=0.12` and
  `rich>=13.0`, removing the Typer extra warning during editable installs.
- Refreshed `uv.lock` after the dependency declaration change.
- Validated core, TUI, and metadata install paths after the rename.
- Confirmed the `sfx` console entry point resolves to `sfxworkbench.cli`.

Validation:

- `uv sync --extra dev` passed.
- `uv sync --extra tui --extra dev` passed.
- `uv sync --extra metadata --extra dev` passed.
- `uv run sfx --version` returned `sfxworkbench 0.1.0`.
- `uv run --extra dev python - <<'PY' ...` imported `sfxworkbench` and loaded
  the Typer app named `sfx`.
- `uv run --extra dev poe json-smoke` passed: 30 tests.
- `uv run --extra dev poe check` passed: 350 tests plus lint/format.

Textual TUI Alpha 3:

- Added built-in queue-specific saved views to the Review tab, so common real
  library slices such as WAV metadata gaps, 48k/96k WAV gaps, duplicate WAVs,
  UCS provenance tags, and similarity decision states can be applied without
  retyping filters.
- Expanded selected-file detail into grouped sections: Identity, Audio,
  Embedded Metadata, and Review State. The detail pane now exposes ADM, cue
  marker, sampler, and metadata-source flags alongside the existing BEXT/iXML,
  duplicate, segment, issue, tag, and next-action context.
- Kept the TUI read-only; saved views only set queue filters and do not create
  approve/apply/undo paths.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed:
  10 tests.
- `uv run --extra dev poe json-smoke` passed: 30 tests.
- `uv run --extra tui --extra dev poe check` passed: 354 tests plus
  lint/format.

Textual TUI Alpha 4:

- Added built-in saved views to the Reports tab for Everything, Reports,
  Plans, Logs, Protected, Conflicts, Metadata, and Dedupe evidence.
- Added category-aware JSON discovery so report browsing can filter by
  `Report`, `Plan`, or `Log` without relying only on text matches.
- Kept report browsing read-only; saved views only filter discovered JSON
  summaries and detail rows.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed:
  11 tests.
- `uv run ruff check sfxworkbench/tui_data.py sfxworkbench/tui_app.py tests/test_tui_data.py`
  passed.
- `uv run ruff format --check sfxworkbench/tui_data.py sfxworkbench/tui_app.py tests/test_tui_data.py`
  passed.

Textual TUI Alpha 5:

- Report detail rows now include top-level JSON `summary` metrics, so generated
  reports with sparse or empty entry lists still show useful counts in the
  Reports tab.
- Kept summary display read-only; it only renders existing JSON evidence.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py -v` passed:
  11 tests.
- `uv run ruff check sfxworkbench/tui_data.py tests/test_tui_data.py` passed.
- `uv run ruff format --check sfxworkbench/tui_data.py tests/test_tui_data.py`
  passed.

Textual TUI alpha iteration closeout:

- Milestone complete for this pass: real-library terminal smoke, queue saved
  views, report saved views, richer file detail sections, summary report rows,
  and dense read-only review polish are in place.
- Read-only real-library data smoke passed against
  `/Users/mattwesdock/.sfxworkbench/index.db` and `/Users/mattwesdock/reports`:
  dashboard metrics, start steps, review queues, missing-metadata queue items,
  report presets, and plan discovery all loaded without error.

Validation:

- `uv run --extra tui --extra dev sfx tui --help` passed.
- `uv run --extra tui --extra dev python -c '...'` real-library adapter smoke
  passed.
- `uv run --extra dev poe json-smoke` passed: 30 tests.
- `uv run --extra tui --extra dev poe check` passed: 355 tests plus
  lint/format.

M0/M1/M2/M6 mini closeout:

- Mini milestone complete: all known unfinished stabilization, beta-freeze,
  current-scope metadata writing, and read-only TUI baseline work has been
  gathered into `docs/FINISH_PLAN.md` and closed.
- Full-library force-rescan similarity-validation attempt was stopped after
  755.56s before report generation. Treat this as performance evidence for M5:
  whole-library similarity validation needs job controls/resume clarity before
  it becomes a default path.
- Bounded copied real-library slice:
  `/private/tmp/sfxworkbench_mini_closeout_slice_20260511/library`, 200 copied
  audio files.
- Similarity-validation beta audit:
  `/private/tmp/sfxworkbench_mini_closeout_slice_20260511/audit`.
  Summary: 200 files scanned; 0 scan errors; 0 filename issues; 109 missing
  metadata rows; 0 unusual sample-rate files; 0 related groups; 0 pack overlap
  candidates; 200 similarity descriptors; 689 detected segments; 2 file-scope
  similarity groups; 11 segment-scope similarity groups. Full audit elapsed:
  7.55s.
- Performance captures on the same slice:
  - scan with hashes: 1.61s for 200 files.
  - pack audit: 0.17s.
  - metadata write-plan: 0.18s, with no accepted tags in the slice DB.
  - tag propose: 0.29s using a temporary mini UCS catalog.
  - similarity crawl: 5.74s for 200 descriptors and 689 segments.
- Mutation trust-language review completed across CLI/help and implementation
  surfaces. Current beta mutation paths surface dry-run/apply, reviewed plans,
  backup, quarantine, safe-folder refusal, collision refusal, readback, and undo
  language; no wording patch was needed.
- `docs/FINISH_PLAN.md` now marks M0, M1, M2 current scope, and the read-only
  M6 baseline complete, and moves the near-term sprint to M5 similarity
  expansion.

M4 closeout:

- Reconciled `docs/FINISH_PLAN.md` with the implemented advanced-maintenance
  surface: safe-folder guarded advanced workflows, preservation score
  explanations, exact-hash import comparison, processed-file reports, reviewed
  permanent-delete plans, and copy-output dual-mono conversion are now described
  as closed beta scope.
- Current M4 validation: `uv run pytest tests/test_m4_advanced.py -v` passed
  with 11 tests.
- Remaining advanced items are explicitly framed as post-M4 product polish, not
  active beta blockers.

M5 closeout:

- Added bounded similarity crawl job controls with `--max-files` and
  `--throttle-ms`; partial runs record `status=partial`,
  `stop_reason=max_files`, and pending/stale counts so the next crawl can
  resume stale work cleanly.
- Added backend/version/parameter anchoring to similarity analysis runs,
  descriptors, segments, and crawl JSON, plus a reserved `audio_embeddings`
  schema for future optional embedding backends.
- Added `sfx similarity backends` to report the available deterministic backend
  and explicitly deferred fingerprint/embedding backends.
- `sfx tag propose` now includes cached deterministic descriptor evidence as
  review-only support on existing proposals; it does not use descriptors as
  semantic proof.
- Updated `docs/FINISH_PLAN.md`, `docs/SIMILARITY.md`, and `README.md` so M5 is
  closed for the deterministic/report-only beta scope.
- Validation: `uv run pytest tests/test_similarity.py tests/test_tag_propose.py tests/test_cli_json.py::test_similarity_cli_json_smoke -v`
  passed with 25 tests.

M7 closeout:

- Added public release readiness docs: `docs/RELEASE.md`,
  `docs/MIGRATIONS.md`, and `docs/DEMO.md`.
- Updated README install guidance for GitHub release wheels, future PyPI,
  GitHub source installs, optional extras, and demo workflow references.
- Expanded `CHANGELOG.md`, `SECURITY.md`, and `SUPPORT.md` for public beta
  use, commercial-library privacy, generated SQLite/JSON artifacts, and
  optional analysis boundaries.
- Updated package metadata description and documentation URL.
- Built release artifacts with `uv build`: `dist/sfxworkbench-0.1.0.tar.gz`
  and `dist/sfxworkbench-0.1.0-py3-none-any.whl`.
- Verified a clean Python 3.11 wheel install in
  `/private/tmp/sfxworkbench_m7_smoke`, then ran installed `sfx --help`,
  `sfx scan tests/fixtures/library_basic --db /private/tmp/sfxworkbench_m7_smoke/index.db --json`,
  and `sfx audit --db /private/tmp/sfxworkbench_m7_smoke/index.db --json`.
- Validation: `uv sync --extra dev`, `uv sync --extra metadata --extra dev`,
  `uv run sfx --help`, and `uv run --extra dev poe check` passed.

M8 planned:

- New milestone: local validation and TUI improvement.
- Goal: run finished beta workflows against copied local data while improving
  the read-only Textual review surface around the friction found during those
  runs.
- Scope: local validation workspace, end-to-end report/review/apply/undo smoke
  paths, usability notes, TUI start checklist, report discovery, plan/log
  summaries, file detail, queue filtering, similarity feedback visibility,
  protected-folder visibility, and command copy/run affordances.
- Guardrail: keep TUI mutation actions out of scope until read-only review
  workflows are reliable and every action maps cleanly to existing CLI JSON
  plans/logs.
- Validation target: `uv run --extra tui --extra dev sfx tui --help`,
  targeted `tests/test_tui_data.py`, and `uv run --extra tui --extra dev poe check`.

## Later

- similarity-assisted tag proposals after the crawler has more real-library
  validation

## Solo Workflow

- One active feature at a time.
- Work directly on `main` for solo-dev slices; skip feature branches unless
  explicitly useful.
- Use simple sprint progress updates such as `3/6 complete`, especially at
  closeout or before switching context.
- Prefer report-only first, then reviewed plan/apply.
- Commit small green slices.
- Use parallel agents for bounded codebase reads or external research, not for
  real-library filesystem actions.
