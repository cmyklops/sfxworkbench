# NEXT

Short current handoff for the active sfxworkbench sprint. Historical sprint
notes were archived to `docs/NEXT_ARCHIVE_2026-05-13.md` so this file stays
cheap to read in future coding sessions.

## Current Focus

- Stabilize and improve the Textual TUI against the real library index.
- Keep filesystem-changing commands plan-first, quarantine-first, reviewed, or
  undoable.
- Keep `sfx` as the user-facing command; `sfxworkbench` remains the
  project/package name.
- Run `uv run --extra dev poe check` before commits.

## Active Real-Library Context

- Test copy root: `/Users/mattwesdock/CommercialLibraries`
- Index: `/Users/mattwesdock/.sfxworkbench/index.db`
- Current indexed files: 120,716
- Current indexed metadata fields: 278,243
- Current filename issues: 0
- Current exact duplicate groups: 0
- Missing BWF/iXML metadata: 22,412 files
- Unusual sample-rate files: 2,854 files
- Active metadata plan: `/Users/mattwesdock/reports/metadata_tag_plan.json`
- Active metadata plan size: about 224 MB
- Active metadata plan summary: 324,078 total entries, 139,448 pending add
  entries, 184,630 skipped-existing entries

## Immediate Work

See `docs/TUI_FOLLOWUP.md` for the detailed investigation and implementation
checklist. Current priorities:

1. Fix documented review bugs:
   - `clean --apply` cancellation over-reports completed removals.
   - Config `db_path` precedence is partial across CLI commands.
   - Tag-suggestion progress skips files with no suggestions.
   - Metadata review skip can drift in-screen counters.
2. Make tab loading cheap:
   - Cache status/review/report summaries.
   - Move expensive fills off the Textual event loop.
   - Stop re-reading large JSON plans during routine tab switches.
3. Finish History polish:
   - The duplicated per-tab panes are now one top-level History tab.
   - Next: replace free-text filters with proper controls and move large detail
     loads off the event loop.
4. Fix Metadata tab headline counts so they use whole-plan counts, not the
   first 500 prioritized rows.
5. Build a real metadata review pane:
   - Paged or virtualized files list.
   - Per-file metadata table with embedded, planned, accepted, and technical
     origins.
   - Filters/sorts for status, field, source, origin, confidence, and text.
   - Long-value/evidence detail drawer.

## Useful References

- `docs/TUI_FOLLOWUP.md` - active TUI bugs, performance measurements, history
  consolidation plan, metadata-review direction.
- `docs/NEXT_ARCHIVE_2026-05-13.md` - archived full `NEXT.md` history before
  this cleanup.
- `docs/FINISH_PLAN.md` - durable milestone status and product finish plan.
- `docs/APP_UI_DIRECTION.md` - visual and interaction direction for the app.
- `docs/METADATA_TAGGING.md` - metadata/tagging product rules and workflows.

## Validation Notes

Most recent full local validation:

- `uv run --extra dev poe check`
- Result: ruff clean, format clean, pytest `605 passed, 3 skipped`

Docs-only edits do not require a full suite, but any code change should run the
focused tests plus `uv run --extra dev poe check`.

## Solo Workflow

- One active feature at a time.
- Work directly on `main` for solo-dev slices unless a branch is explicitly
  useful.
- Prefer report-only first, then reviewed plan/apply.
- Commit small green slices.
- Use parallel agents for bounded codebase reads or external research, not for
  real-library filesystem actions.
