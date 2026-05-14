# TUI Follow-Up Notes

Captured: 2026-05-13

These notes preserve the current TUI review bugs and real-library scale findings
from the `/Users/mattwesdock/CommercialLibraries` index. Treat this as the next
implementation checklist before more TUI features are layered on top.

## Plan Audit - 2026-05-13

The original direction was mostly right, but the order needed tightening. The
best path is to fix the shared data/index layer before moving panes around:

1. Correct whole-plan metadata counts so the UI no longer reports page totals as
   library totals.
2. Cache report summaries and stop tab-history filters from full-text scanning
   large JSON plans on every tab activation.
3. Build the larger consolidated History surface on that shared history model.
4. Build the richer metadata review pane on an indexed plan-entry model instead
   of extending the current wide preview table.

Executed in this slice:

- Added whole-plan metadata tag counts for the Metadata findings strip.
- Switched TUI history discovery to cached summaries and summary-field matching,
  so tab switches do not read a 224 MB plan as raw text for every feature query.
- Added a lightweight tag-plan summary/count path that reads the plan `summary`
  block without parsing the full `entries` array during TUI history refreshes.
- Upgraded the dedicated metadata review screen's right pane from a planned-only
  candidates table into a selected-file metadata table with planned, embedded,
  accepted DB-only, and technical/indexed rows.
- Replaced duplicated per-feature history panes with one top-level History tab
  that lists reports, plans, logs, previews, and TUI action history in one
  filtered timeline.
- Kept full-content history search available for direct data-adapter callers;
  the interactive TUI uses the lighter summary search path.

## Fixed Bugs

The following bugs were fixed after this note was created; keep the details here
as regression context.

1. Fixed: `clean --apply` cancellation over-reported completed work.
   `sfxworkbench/clean.py` builds `CleanResult.removed_files`,
   `removed_dirs`, and `bytes_freed` from the full discovered junk set before
   deletion starts. If cancellation fires mid-apply, the TUI result and JSON log
   still say every planned item was removed. Track actually deleted paths and
   actual freed bytes during apply; keep planned paths for dry-run/preview only.

2. Fixed: config `db_path` precedence was partial.
   `sfxworkbench/cli/tag.py` documents CLI > config > package default as the
   standard DB precedence, but commands such as `audit`, `search`, `dedupe`, and
   `metadata audit` still use `DEFAULT_DB_PATH` directly. A configured user can
   scan one DB and then inspect another unless they repeat `--db`. Move every
   DB-taking command through `resolve_db_path`.

3. Fixed: tag-suggestion progress skipped files with no suggestions.
   `sfxworkbench/tag_suggest.py` continues before calling the progress callback
   when a file produces no surviving suggestions. On restrictive filters or
   sparse libraries, the TUI progress bar can stall or fail to hit 100%. Report
   progress at the bottom of the per-file loop regardless of suggestion count.

4. Fixed: metadata review skip could drift in-screen counters.
   `sfxworkbench/tui_screens/metadata_review.py` uses `setdefault()` when
   skipping a file. Already approved/rejected candidates keep their effective
   status, but counters are adjusted as though they became skipped. Only update
   counters when the effective status actually changes, and skip should not
   overwrite already decided candidates unless that behavior is made explicit.

## Why Tabs Feel Slow

The tab work is still synchronous on the Textual event loop. Recent lazy-fill
and smart-invalidation changes help, but opening or refreshing a tab can still
block while it parses JSON and builds derived models.

Measured against the current real-library state:

- Index: `/Users/mattwesdock/.sfxworkbench/index.db`
- Files: 120,716
- Indexed metadata fields: 278,243
- Active metadata plan: `/Users/mattwesdock/reports/metadata_tag_plan.json`
- Plan size: 224 MB
- Plan summary: 324,078 entries, 139,448 add entries, 184,630 skipped-existing
  entries

Timing sample from local adapters:

| Adapter | Time | Notes |
| --- | ---: | --- |
| `feature_pages()` for the status strip | 0.170s | Recomputes dashboard metrics and review queues. |
| `scan_findings()` | 0.061s | Mostly SQLite counts. |
| `clean_findings(scan_junk=False)` | 0.081s | Avoids filesystem junk walk. |
| `dedupe_findings()` | 0.188s | Calls `find_duplicates`; cheap here because there are no duplicate groups. |
| `metadata_findings(plan)` | 2.722s | Parses/iterates the large plan through `metadata_workbench_rows(limit=500)`. |
| `metadata_workbench_rows(limit=100)` | 1.674s | Still iterates all plan entries to build `pending_by_path`. |
| `discover_plan_files(metadata query)` | 2.128s | Reads matching JSON text to search report contents. |
| `plan_detail_rows(first metadata history)` | 1.369s | Parses the selected JSON detail synchronously. |

Primary causes:

- The Metadata tab does two plan-derived passes: `metadata_findings()` and
  `metadata_workbench_rows()`. The parsed JSON cache avoids repeated
  `json.loads`, but both paths still iterate the 324k-entry plan and build
  Python dictionaries/lists on the UI thread.
- `discover_plan_files()` scans every report directory for each tab-specific
  History pane. When a query is present, `_plan_matches_query()` reads entire
  JSON files as text. One 224 MB plan is enough to make tab switches visible.
- `_refresh_reports(feature)` runs on every tab activation, so even a tab whose
  primary table is clean can spend time rediscovering and summarizing history.
- The status strip recomputes several SQLite count groups every refresh. This is
  not the largest cost today, but it is repeated often and should become cached.
- Dedupe currently computes findings and group rows separately. It is fast on
  the current no-duplicate index, but it will become a repeated full duplicate
  pass when duplicates exist.

Recommended fixes:

- Done: cached report summaries keyed by JSON file mtime/size; lightweight
  summary matching for per-tab history queries; avoid full `entries` parsing
  for tag-plan history summaries when the plan summary block is available.
- Done: session-level adapter cache keyed by DB and plan `(path, mtime, size)`.
  Wraps `dashboard_metrics`, `feature_pages`, `scan_findings`, `dedupe_findings`,
  `dedupe_group_rows`, `metadata_findings`, `metadata_workbench_rows`, and
  `plan_detail_rows`. Cleared in the App's `_refresh()` after every action.
- Done: expensive tab fills moved to background threads. `_fill_metadata`
  paints a loading placeholder, then warms the adapter cache off-thread and
  re-renders via `call_from_thread`. Same pattern in `_fill_history_detail`.
- Done: split metadata plan summary/counting from paged row building. Counts
  now come from the plan summary block or a whole-plan adapter instead of
  `metadata_workbench_rows(limit=500)`.
- Done: duplicate-aware counts via the SQLite plan index. A new adapter
  `metadata_plan_duplicate_aware_counts` joins `plan_entries` against
  `accepted_tags` + `metadata_fields` and surfaces a "Truly pending (after
  dedup)" row in the Metadata findings strip.
- Done for the TUI: stop full-text reading of every JSON file during tab-history
  discovery. Summarize by filename plus parsed lightweight summary fields, cache
  summaries, and only parse/read detail for the selected history row.
- Done: large plans are loaded into an in-memory SQLite `plan_entries` index
  (`_metadata_plan_index`). The review screen, workbench paging, and the
  duplicate-aware counts all query this index instead of re-walking JSON.

## Consolidated History Tab

The feature tabs no longer embed their own `History` / `History Detail` pairs.
History now lives in one top-level tab after Advanced, with `7` as the keyboard
shortcut.

Implemented shape:

- Shared app state: `_history_rows`, `_history_query`,
  `_history_feature_filter`, `_history_category_filter`, and selected path.
- Top filters: text search, feature filter, and category filter.
- Timeline table columns: category, feature, kind, rows, errors, title, path.
- Detail table: existing `plan_detail_rows()` output for the selected JSON.
- Discovery: `discover_plan_files(..., content_query=False)` so routine History
  refreshes use lightweight summary search instead of full JSON text search.
- Refresh: any action with a `reports` refresh hint marks History dirty. If the
  History tab is active, the shared list refreshes and selection is preserved by
  path when possible.

Remaining follow-up:

- Done: feature and category filters are now Textual `Select` dropdowns
  (see ``HISTORY_FEATURE_OPTIONS`` / ``HISTORY_CATEGORY_OPTIONS``).
- Done: detail loading is workerized; selecting a row paints a "Loading…"
  placeholder and renders once the JSON parse returns.
- Deferred: persisted report-summary index. The in-memory cache plus the
  lightweight summary path handle the current 224 MB plan; persisting to disk
  isn't justified until report directories grow large enough to matter at
  process start.

## Why Metadata Suggestions Show 694 Pending Changes

Generation is not capped at 694. The active plan contains:

- 324,078 total entries
- 139,448 pending add entries
- 184,630 skipped-existing entries

The 694 number is a display/counting artifact in the Metadata tab:

- `metadata_findings()` calls `metadata_workbench_rows(..., limit=500)`.
- `metadata_workbench_rows()` builds rows for only the first 500 prioritized
  files and suppresses duplicates against already existing metadata/tags.
- `metadata_findings()` then sums `row.pending_changes` across those 500 rows.

Current measured values:

- First 100 workbench rows: 154 visible pending changes.
- First 500 workbench rows: 694 visible pending changes.
- Full duplicate-aware tag-change rows: 139,448 visible pending add entries.

Fix:

- Done: add a dedicated `metadata_plan_counts(plan_path)` adapter that returns
  whole-plan counts independent of table pagination and can use the plan summary
  block without parsing every entry.
- Done: use whole-plan add/review counts for fast headline numbers. The
  Metadata table remains a paged "first prioritized files" preview.
- Done: duplicate-aware counts are precomputed once per
  ``(plan_signature, db_signature)`` pair via
  ``metadata_plan_duplicate_aware_counts`` and cached in the session adapter
  cache.
- Done: the table heading says "First 500 Prioritized Files" and the findings
  row pulls from whole-plan counts, so the page is never used as a library
  total.

## Metadata Review Pane Direction

Users need to inspect all relevant metadata, not a single concatenated 180-column
cell. The current inline Metadata tab shows a useful preview, but it is not a
review surface for a 139k-entry plan.

Recommended review layout:

- Done: right pane shows planned + embedded + accepted DB-only + technical
  rows for the selected file.
- Done: left pane columns are now ``State, Filename, Pending, Approved,
  Rejected, Embedded, Accepted, Sources, Path``. Counts come from the cached
  ``FileReviewItem`` so approve/reject keystrokes update one row in place.
- Done: top filter bar with status / field / source inputs. A file passes if
  any of its candidates matches every active filter (case-folded substring).
- Done: header-click sorting on both panes via
  ``on_data_table_header_selected``; same column toggles direction.
- Deferred: detail drawer for long values and evidence. Today long values
  truncate at column width; surfacing a side drawer is a meaningful UI build
  that's better as its own pass.
- Deferred: "approve filtered slice" keyboard action. Wants to land after the
  filter UI matures (e.g. once filters can include confidence range and
  conflict checks). Single-row approve/reject/skip still works as expected.

Data model:

- Keep embedded metadata from `metadata_fields`.
- Keep accepted tags from `accepted_tags`.
- Load planned tags from the active plan into an indexed cache table or temp DB
  table. JSON remains the exchange format, but the UI should query SQL for
  review.
- Preserve `entry_id` so approve/reject can still call `review_tag_plan()` or a
  future plan-cache writer without losing compatibility with CLI plans.

Display policy:

- Search fields first: description/comment, keywords, title/name,
  category/subcategory, UCS provenance.
- Then accepted DB tags.
- Then planned additions.
- Then technical/provenance fields such as BEXT/iXML flags, MD5, channels,
  sample rate, source namespace, and scan error.
- Do not cap per-file metadata at the current `file_detail()` `LIMIT 24` in the
  review pane. Page or virtualize instead.
