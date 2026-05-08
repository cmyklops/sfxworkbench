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
- Current indexed filename issues: 0.
- Metadata audit report: `/Users/mattwesdock/reports/metadata_audit_full_20260508.json`.
- Missing BWF/iXML metadata: 22,412 files.
- Unusual sample-rate files: 2,854 files.
- Related groups report: `/Users/mattwesdock/reports/related_groups_report_20260508.json`.
- Related group candidates: 15,331 groups covering 78,735 files.
- Related group mix: 15,163 numbered-sequence groups, 168 channel-set groups,
  147 groups with mixed sample-rate/bit-depth/channel formats.

Current audit focus:

- Scan errors: cleared with RIFF fallback reader for malformed side chunks.
- Filename issues: cleared.
- Metadata/sample-rate reporting: implemented as report-only.
- Related sound group reporting: implemented as report-only.

## Next

1. Move on from folder nesting unless you want a manual review flow for semantic wrappers.
2. Decide whether unusual sample rates are informational only or should become
   a reviewed `normalize` candidate report later.
3. Use related group evidence to shape future tag suggestions and TUI review.

## Later

- `sfx packs plan/apply` for reviewed folder consolidation.
- `sfx organize` for safe folder-structure cleanup.
- `sfx tag --from-filename` after rename/organize workflows stabilize.
- Textual TUI after CLI JSON contracts feel boring.

## Solo Workflow

- One active feature at a time.
- Prefer report-only first, then reviewed plan/apply.
- Commit small green slices.
- Use parallel agents for bounded codebase reads or external research, not for
  real-library filesystem actions.
