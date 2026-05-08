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
- Long paths: fixed.
- Unicode normalization duplicates: quarantined.
- Pack overlap report: zero exact-hash pack candidates after dedupe.
- Top-level numeric sort-prefix folder organization: applied.
- Redundant nesting audit: report-only CLI pattern added and run.
- Redundant nesting report: `/Users/mattwesdock/reports/redundant_nesting_report_20260508.json`
  found 52 candidates: 30 one-child chains, 12 repeated folder names, 10 low-value wrappers.
- Repeated-folder-name flatten workflow: implemented; one-child chains and low-value
  wrappers remain report-only.
- Repeated-folder nesting plan: `/Users/mattwesdock/reports/repeated_folder_nesting_plan_20260508.json`
  is reviewed and dry-run clean: 12 folders, 240 child moves, 0 errors.
- Repeated-folder nesting apply: done, 12 folders flattened, 240 child moves,
  undo log at `/Users/mattwesdock/reports/repeated_folder_nesting_log_20260508.json`.
- Single-child nesting apply: done, 18 useful wrappers collapsed across two logs;
  generic child folders such as `Content`, `Designed`, `Source`, and `Sounds` stay report-only.
- Final redundant nesting report: `/Users/mattwesdock/reports/redundant_nesting_report_final_20260508.json`
  found 27 candidates: 23 low-value wrappers and 4 generic single-child chains.

Current audit focus:

- Scan errors: cleared with RIFF fallback reader for malformed side chunks.
- 1,910 risky-character filename issues remain.
- 17 non-ASCII filename issues remain.

## Next

1. Decide whether low-value wrapper folders should get a stricter reviewed plan/apply workflow.
2. Add report-only related sound groups/collections audit.
3. Review risky-character filename issues.

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
