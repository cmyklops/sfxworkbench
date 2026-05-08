# NEXT

Solo-dev working note for the current wavwarden sprint. Keep this short; move
durable decisions into `docs/PHASES.md` only when they survive real-library use.

## Now

- Work from real library findings into reusable, tested CLI workflows.
- Keep filesystem-changing commands plan-first, quarantine-first, or undoable.
- Use `uv run --extra dev poe check` before every commit.

## Current Library State

- Test copy root: `/Users/mattwesdock/CommercialLibraries`
- Index: `/Users/mattwesdock/.wavwarden/index.db`
- Exact file duplicates: quarantined.
- Safe filename/path cleanup: applied.
- Long paths: fixed.
- Unicode normalization duplicates: quarantined.
- Pack overlap report: zero exact-hash pack candidates after dedupe.

Current audit focus:

- Scan errors: cleared with RIFF fallback reader for malformed side chunks.
- 1,910 risky-character filename issues remain.
- 17 non-ASCII filename issues remain.

## Next

1. Add folder organization to the roadmap and then build a report-only preview.
2. Inspect top-level numbered folders before any organization apply.
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
