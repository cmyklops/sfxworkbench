# Changelog

All notable changes to sfxworkbench will be documented in this file.

The format is based on Keep a Changelog, and this project uses semantic
versioning once public releases begin.

## Unreleased

### Tier 3.7 — In-Table Filters (Metadata + Dedupe)

- **Filter the Metadata prioritized-files table by typing.** A new
  ``#metadata-search`` Input sits above the Metadata Values table; the
  query feeds straight into the existing ``metadata_workbench_rows(query=)``
  adapter (which already filters on ``f.filename`` and ``f.path``).
  Debounced at 250ms, mirroring the Files tab's search.
- **Filter the Dedupe duplicate-groups table by typing.** A new
  ``#dedupe-search`` Input matches all space-separated terms against the
  group's hash, keep-path, and member files. ``dedupe_group_rows`` gained
  a ``query`` parameter; filtering happens post-hoc in Python since
  ``find_duplicates`` returns the full group set up front.
- **Not extended to Scan / Clean / Advanced.** Those tabs surface small
  categorical *findings* tables (file counts by issue category, not file
  lists). Filtering would be low-value churn for tables of <20 rows.

### Tier 5.12 — Smart Tab Invalidation (Replaces Reactive Rewrite)

The originally-specified Tier 5.12 was a reactive-partial-refresh rewrite
to avoid rebuilding DataTables on every state change. On closer inspection
the premise didn't hold: the visible tables cap at 100 rows, so re-rendering
them is bounded — the real cost is the SQL underneath. A 3-5 day reactive
rewrite would barely help.

What actually helped: **honor the ``ActionResult.refresh`` hints that every
action already declares.**

- Every action in ``sfxworkbench.tui_actions`` already returns a
  ``refresh`` tuple like ``("metadata", "reports")`` to indicate what it
  invalidates. Until this change the App ignored it — every action
  blindly marked every tab dirty.
- ``_refresh()`` gained an optional ``dirty: tuple[str, ...]`` argument.
  ``_run_action`` now passes ``result.refresh`` so only the named tabs
  get marked dirty. The ``None`` default preserves "everything dirty"
  for startup, resize, library-path changes, and the manual refresh.
- **Dependency rule:** the Scan tab's findings are a dashboard view
  derived from file inventory, metadata coverage, and dedupe state. If
  any tab gets dirtied, Scan does too — so the dashboard stays accurate
  without editing 25 individual refresh declarations.
- **New invariant test** ``test_action_refresh_hints_are_known`` scans
  the action module's AST and asserts every ``refresh=(...)`` literal
  uses a known hint key. Guards against typos that would silently
  under-invalidate.

**Concrete payoff per action:** a ``metadata_audit`` while sitting on the
Files tab used to re-fill Files (50k-row SQL), Clean, Dedupe, and
Advanced. Now it re-fills only Metadata + Scan. Same story for plan-only
and audit-only actions across every tab.

### Tier 3.8 — Multi-Select (Deferred, Awaiting Implementation)

Selection should persist between tabs but invalidate on re-scan (user
preference confirmed). The contract choice resolved to **Option (a)**:
add ``target_paths: tuple[Path, ...] | None`` to every plan dataclass and
filter candidates inside each executor. Reasons:

- Plans already carry optional fields (``dry_run``, ``--no-backup``);
  adding one more is consistent.
- Executors already filter candidates by rule predicates; one more
  filter step is the same pattern.
- The "forgot to wire it" failure mode is loud (visible regression) vs.
  the silent-failure mode in Option (b)'s implicit-scope alternative.
- The TUI holds ``_selected_paths: set[Path]`` invalidated on scan
  completion; every action call site adds
  ``target_paths=tuple(self._selected_paths) or None``.

Implementation: ~12 plan dataclasses × 2 changes each, plus selection
UI on the Files table (DataTable cursor + space-to-toggle binding, count
shown in the status strip).

### Tier 5.14 — Lazy Tab Fill

- **`_refresh` no longer fills every tab eagerly.** It marks all six tabs
  dirty and fills only the active one; switching tabs drains the dirty flag.
  A user who only opens Scan and Files in a session skips the per-refresh
  build of Clean/Dedupe/Metadata/Advanced entirely. Per-tab widget
  composition stays eager (cheap); the deferred work is the expensive
  data-side fill — e.g. ``_fill_files_impl`` on a 50k-row library.

### Follow-Up Round 2: Tightening The Safety + Config Stories

- **`--no-backup` now requires `--yes` to confirm the safety bypass.**
  Combining ``--apply --no-backup`` without ``--yes`` on ``sfx metadata
  write-apply`` exits with a clear error explaining that the readback-mismatch
  rollback path is unavailable in that mode.
- **Mypy ratchet on new code.** Cleaned up 16 errors introduced in
  ``sfxworkbench.query`` and ``sfxworkbench.tui_screens.metadata_review``
  during the initial rollout. Mypy baseline back to the pre-rollout 43.
- **`sfx tag suggest` reads `library_root` from active Config** when path
  isn't given. First real ``ctx.obj``-as-Config opt-in beyond ``sfx config``;
  the pattern is a one-liner each command can adopt.
- **Resumability test for `apply_tag_plan`.** Simulates a hard interruption
  mid-loop and verifies the SQLite all-or-nothing transaction property: no
  partial state in ``accepted_tags``, re-running converges to the intended
  state. Same invariant a real SIGTERM test would prove, reliably timed.

### Follow-Up: Completed Deferred Work From The Initial Rollout

- **`cli.py` split fully complete** (was: 1 of 13 subapps extracted). All
  remaining subapps moved to per-module files under `sfxworkbench/cli/`:
  `packs.py`, `groups.py`, `format.py`, `compare.py`, `delete.py`, `audio.py`
  (with nested ``dual_mono``), `organize.py`, `tag.py`, `ucs.py`,
  `similarity.py` (with nested ``feedback``). `cli/__init__.py` shrank from
  ~3,000 lines to ~670 (top-level commands + main wiring only).
- **Sibling `.original-<stamp>Z` backups now default** for
  `apply_metadata_write_plan` when no `--backup-dir` is given. New
  `--no-backup` flag for callers who have an external snapshot (with the
  trade-off that readback-mismatch restore is unavailable in that mode).
  Legacy `--backup-dir` path preserved for backward compat.
- **`MetadataReviewScreen` wired into the TUI**. Press `R` from any tab in
  `sfx tui` to push the two-pane review screen for the most recent
  `tag_plan*.json` in the active report directory. Falls back to a
  status-strip warning when no plan file exists.
- **`sfx config show` + `sfx config validate` commands** make the resolved
  configuration observable end-to-end. Demonstrates the `ctx.obj`-as-Config
  pattern other commands can adopt incrementally.
- **`apply_tag_plan` idempotency tests** confirm the
  ``ON CONFLICT(file_id, field, value) DO UPDATE SET ...`` invariant:
  re-running an apply after an interrupted run produces exactly one row in
  ``accepted_tags``, never duplicates. The kill-signal harness is deferred.

### Architecture

- Converted `sfxworkbench.cli` from a single 3000-LOC module to a package.
  Extracted the `metadata` subapp (10 commands, ~420 LOC) into its own module
  at `sfxworkbench/cli/metadata.py` as the exemplar for the per-subapp pattern:
  each subapp module owns its `typer.Typer(...)` instance plus its command
  decorations and is importable in isolation. `cli/__init__.py` imports the
  assembled subapp instance and wires it into the main `app`. The remaining
  12 subapps stay inline in `cli/__init__.py` for now; each is a mechanical
  one-PR extraction following the same pattern.
- Added a `Suggestor` Protocol and `SuggestContext` dataclass in
  `sfxworkbench.tag_suggest`. The five existing `suggest_from_*` functions are
  now wrapped by tiny `@dataclass(frozen=True)` adapters
  (`UcsStemSuggestor`, `GroupSuggestor`, `FilenameSuggestor`, `PathSuggestor`,
  `SynonymSuggestor`) registered in `DEFAULT_SUGGESTORS`. The orchestrator
  `build_tag_suggestion_report` now iterates this list via `run_suggestors`,
  threading the accumulating suggestion list through as `prior` so gating
  (filename-description skip when UCS/group already produced one) and
  meta-expansion (synonyms) stay correct. Adding a new suggestor is now a
  one-class change with no orchestrator edit. No behavior change.

### Power Features

- Added `sfxworkbench/tui_screens/metadata_review.py` — the two-pane
  metadata-review screen (Picard-inspired). Left pane is the queue of files
  awaiting review; right pane is the per-field candidate table with proposed
  value, source, and a ``new``/``same``/``change`` diff marker. Key bindings:
  ``a`` approve, ``r`` reject, ``s`` skip file, ``n`` next file, ``j``/``k``
  cursor down/up, ``q`` back. The pure data layer (``FileReviewItem``,
  ``TagCandidate``, ``build_review_queue``) is importable without the ``tui``
  extra so it stays unit-testable; the Textual ``Screen`` itself is built
  lazily via ``build_metadata_review_screen``. Wiring into a top-level tab in
  ``tui_app.py`` follows as a small follow-up — the screen accepts a plan
  path and is ready to be ``push_screen``-ed.
- Added `sfxworkbench.query` — a beets-style key:value DSL parser and SQL
  compiler over the SQLite ``files`` index. Supports equality, comma lists
  (``ext:wav,flac``), comparison operators on numeric fields
  (``rate:>=48000``), ranges (``rate:44100..96000``), negation (``-ext:mp3``),
  boolean ``has:bext`` / ``missing:bext`` flags, free-text path/filename/stem
  search, and quoted phrases. Field aliases (``rate``, ``ext``, ``size``, …)
  and the boolean flag list are one-line registry edits.
- Added `sfx ls QUERY` command that compiles the DSL, runs the SQL, and
  prints a Rich table (or JSON, with ``--json``). Supports ``--limit``,
  ``--sort`` with ``-`` prefix for descending.

### Configuration

- Added `sfxworkbench.config` with a `Config` Pydantic model (plus
  `ConfidenceProfile` and `BackupConfig` sub-models). User preferences load
  from a TOML file with the precedence chain ``--config`` flag → ``$SFX_CONFIG``
  env var → ``~/.config/sfxworkbench/config.toml`` → defaults. Malformed or
  explicitly-missing files raise a clear `ConfigError`; missing default
  locations silently fall back. The top-level `sfx --config PATH` option is
  wired into the CLI callback and stashes the resolved `Config` on
  `typer.Context.obj`. Subcommand plumbing follows in subsequent PRs.
- Repointed `tag_suggest.py`'s `_CONFIDENCE_*` module constants at the
  `ConfidenceProfile` defaults so the Pydantic model is the single source of
  truth for the historical anchors. No behavior change.

### Safety And Correctness

- Added `sfxworkbench.backups` with the ExifTool-style sibling backup
  primitive: `make_original_backup(path)` creates a sibling
  ``<filename>.original-<UTC-ISO-stamp>Z`` file alongside the original (preserving
  mode and mtime via `shutil.copy2`). `discover_backups(root)` walks a tree
  yielding parsed `OriginalBackup` records, and `clean_backups(root,
  older_than_days, dry_run)` is the garbage collector with injectable
  reference time. New `sfx maintenance clean-backups PATH --older-than-days N
  [--apply]` CLI command exposes the GC, defaulting to dry-run with JSON
  output available for automation. Integration with the
  `apply_metadata_write_plan` / `sfx rename --apply` / `sfx organize --apply`
  flows follows in a subsequent PR; the policy knobs in `BackupConfig` and the
  helpers in this module are the substrate.
- Strengthened verify-on-readback in `metadata_write.apply_metadata_write_plan`:
  when a post-write readback now disagrees with the planned fields, the apply
  step automatically restores the original file from its pre-apply backup
  rather than leaving the user with a divergent file. The error entry records
  whether the restore succeeded, includes the backup path, and a new
  `files_restored` counter on `MetadataWriteApplyResult` makes the rollback
  visible in the result + apply-log JSON.
- Added `atomic_write_text` and `atomic_write_json` helpers in
  `sfxworkbench/utils.py` that write via a sibling temp file, `fsync`, and
  `os.replace`. A crash mid-write now leaves the destination either unchanged
  (if it existed) or absent — never truncated. Migrated all plan, report,
  manifest, and apply-log JSON writers across the package to the atomic
  helpers.
- Bumped the minimum supported Python to 3.11 (was 3.10). CI matrix now covers
  3.11 and 3.12.

### Test Coverage

- Added `tests/test_delete.py` (7 tests) covering the reviewed permanent-delete
  pipeline: `build_delete_plan` (drops missing quarantine paths, marks
  safe-folder entries as errors), `review_delete_plan` (approve-all and
  approve/reject by entry id), `apply_delete_plan` dry-run, the explicit
  `--i-understand-permanent-delete` confirmation gate, and dry-run
  idempotency (two consecutive runs produce identical counts).
- Added `tests/test_dual_mono.py` (5 tests) covering the previously-untested
  stereo-to-mono detection and copy-output pipeline: detection of files with
  identical channels, plan review, dry-run vs apply behavior, and dry-run
  idempotency.

### Project Hygiene

- Added `mypy` to the dev extras and exposed it as a new `poe lint-types`
  task with lax settings (ignore missing imports, warn on unused ignores).
  `lint-types` is not yet wired into `poe check` because the brownfield
  codebase has a pre-existing error baseline; the plan is to ratchet errors
  down and then gate CI on it.

### Public Readiness

- Added release documentation, SQLite migration notes, demo-library guidance,
  and clean wheel-install smoke-test steps for GitHub release packaging.
- Updated install guidance for release wheels, future PyPI installs, source
  installs, and optional metadata/TUI extras.
- Expanded security/support guidance for commercial audio-library privacy,
  generated SQLite/JSON artifacts, and optional future ML analysis.

### TUI Workbench

- Reworked `sfx tui` into a full-feature operations workbench with Scan, Files,
  Clean, Dedupe, Organize, Metadata, Similarity, and Advanced pages.
- Added shared action-result contracts for TUI/GUI parity, covering safe
  scan/audit, cleanup, dedupe, pack, rename, DB-only tag, sidecar, and
  similarity actions.
- Added `sfx audit-bundle` to refresh the index and write a core read-only
  audit bundle for app-driven review sessions.

### Similarity And Audio Analysis

- Added `sfx similarity crawl` as an experimental deterministic audio
  descriptor crawler. It analyzes indexed files, skips unchanged descriptor
  rows by size/mtime/hash anchors, stores results in SQLite, writes an optional
  cache run report, and reports peak/RMS/crest/silence/clipping plus simple
  zero-crossing, transient-density, and spectral centroid/bandwidth/rolloff/
  flatness descriptors. Added `sfx similarity search --file QUERY` to rank
  cached descriptors against a query audio file, including `--scope segment`
  for event-window search. Added RMS-based event segment detection during crawl
  plus `sfx similarity segments` to inspect cached segment windows. Added `sfx
  similarity audit` to produce report-only near-duplicate groups from cached
  descriptor rows, including `--scope segment` for matching event windows
  across files. Segment audit now prunes candidate comparisons with coarse
  descriptor buckets and reports comparison counts, excluding exact MD5
  duplicate pairs by default.
- Added bounded crawl controls with `--max-files` and `--throttle-ms`, partial
  run status, pending/stale counts, backend versioning, parameter hashes, and
  `sfx similarity backends`.
- Reserved an `audio_embeddings` SQLite table for future optional embedding
  backends. No model runs by default.
- `sfx tag propose` now includes cached deterministic descriptor evidence as
  review-only support when descriptors are available.

### Advanced Maintenance

- Added preservation-priority evidence for duplicate keep decisions. `sfx
  dedupe --output PLAN --prefer-folder PATH --prefer-extension EXT` and `sfx
  packs plan --prefer-folder PATH` store ordered rule evidence in generated
  plans and use those rules when choosing keep copies.
- Added exact dedupe safe-folder protection. `sfx dedupe --output PLAN
  --safe-folder PATH` records protected folders, prefers protected duplicate
  files as keep copies, and marks protected extra copies as ignored. `sfx
  dedupe --apply PLAN --safe-folder PATH` re-checks protections before
  quarantine or deletion.
- Added pack safe-folder protection. `sfx packs plan --safe-folder PATH`
  records protected folders, prefers protected exact-duplicate folders as keep
  copies, and marks protected sources as ignored. `sfx packs apply
  --safe-folder PATH` also re-checks protections before moving folders so older
  plans cannot quarantine newly protected paths.

### UCS And Tagging

- Added `sfx ucs` Typer app with `import`, `info`, and `categories`
  subcommands. Parses the official `Soundminer/_categorylist.csv` shipped in
  `UCS Release.zip`, normalizes 753 UCS v8.2.1 entries into a versioned JSON
  cache at `~/.sfxworkbench/ucs_catalog.json` with full provenance (source URL,
  release version, import timestamp, attribution). Discovery chain supports
  explicit `--catalog` path, `SFXWORKBENCH_UCS_DATA` environment variable, and
  the default cache. XLSX import deferred. Catalog data is not yet wired into
  rename or tag_suggest; those integrations follow in subsequent slices.
- Added `sfx tag suggest` report-only command. Composes UCS stem parsing,
  filename heuristics (abbreviation expansion, take-number extraction),
  parent-folder evidence, and related-group membership into versioned tag
  suggestion JSON plans. No filesystem or DB writes. Phase B of
  `docs/METADATA_TAGGING.md`.

### Project Hygiene

- Prepared internal studio beta safety workflows.
- Restored standalone `audit.py`.
- Added JSON output contracts for CLI automation.
- Added quarantine-first dedupe apply behavior.
- Added UCS-oriented rename preview/apply/undo workflow.
- Added development tasks, Ruff checks, CI, and benchmark scripts.
- Added open-source hygiene docs and package metadata.
