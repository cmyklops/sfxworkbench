# sfxworkbench Finish Plan

Generated: 2026-05-09
Updated: 2026-05-11

This plan audits the remaining work needed to move sfxworkbench from the current
Internal Studio Beta codebase toward a finished, trustworthy v1 product. It is
based on the implemented CLI surface, current roadmap docs, tests, and the app
UI direction reference in `docs/APP_UI_DIRECTION.md`. Product positioning and
polished GUI feature direction live in `docs/PRODUCT_DIRECTION.md`.

## Current State

sfxworkbench already has a broad, safety-first CLI core:

- Standalone zero-dependency `audit.py`.
- SQLite-backed scan, audit, search, and export.
- Junk cleanup with dry-run/apply.
- Exact duplicate plans and quarantine apply.
- Pack/folder duplicate audit, plan, review, apply, and undo.
- Rename and organize workflows with review, apply, undo, collision checks, and
  SQLite path updates.
- Metadata audit, per-file metadata view, backend discovery, reviewed metadata
  write plans, fixture bundles, readback, Mutagen apply, backup, verification,
  and undo.
- UCS import, info, category query, validation, raw tag suggestions, evidence
  proposals, DB-only tag plans, CSV-backed bulk tag plans, sidecar
  export/import, and tag apply logs.
- Normalized embedded metadata evidence in `metadata_fields`, populated during
  scan/index refresh and used by metadata view and tag proposals.
- Deterministic similarity crawl, segment listing, whole-file and segment
  search/audit, plus DB-only feedback states.
- JSON contracts and tests for the major automation surfaces.
- A read-only Textual alpha behind `sfx tui` with start guidance, review
  queues, saved review/report views, indexed-file detail, generated JSON
  report/log browsing, and protected-folder visibility.
- A first full-feature operations workbench slice behind `sfx tui`, organized
  around Scan, Files, Clean, Dedupe, Organize, Metadata, Similarity, and
  Advanced feature pages with shared action-result contracts.
- A first app UI direction mockup and note under `docs/assets/` and
  `docs/APP_UI_DIRECTION.md`.

The core safety posture is intact: mutating workflows are dry-run by default,
reviewed, backed up, quarantined, or undoable.

## Audit Findings

### Documentation Drift

The M0/M1/M2/M6 closeout pass on 2026-05-11 removed the known drift around
metadata write apply/undo, generated root-level apply logs, beta validation, and
the read-only TUI alpha. Remaining roadmap drift should now be treated as part
of the next active milestone, not as unfinished baseline work.

### Beta Readiness Gaps

The beta-safe baseline is closed for M0/M1. Clean install checks, Python
3.10/3.11 CI, JSON smoke coverage, full local checks, a real-library beta audit,
and a bounded copied-library similarity-validation audit have been captured.
Future beta work should focus on the active feature milestone being changed.

### Metadata Writing Gaps

M2 is closed for the current beta scope. Mutagen-backed standard tagged formats
and BWF MetaEdit-backed WAV/RF64 writes now use reviewed plans, existing-value
skip/replace behavior, fixture/readback paths, original-file backups, apply
logs, readback verification, index refresh, and undo guards. AIFF/AIF remain
unsupported plan entries, W64 remains sidecar-first unless a backend is proven,
and future iXML/wider BWF writes are deferred feature work rather than baseline
stragglers.

### Tagging And Metadata Review

M3 is closed for the current beta scope. The tag review path now has normalized
embedded metadata evidence, CSV-backed bulk tag plans, synonym-assisted keyword
suggestions, selector/batch review summaries, accepted DB-only tags, sidecars,
and embedded metadata write handoff through reviewed plans. Ongoing real-library
calibration, richer user dictionaries, and future similarity/audio evidence
remain product-quality improvements rather than blockers for the current M3
acceptance bar.

### Advanced Workflow Status

M4 is closed for the current beta scope. Advanced maintenance now covers
config-backed safe folders across mutating workflows, preservation-priority
scoring explanations, exact-hash import/database comparison, report-only
processed-file detection, permanent deletion from reviewed quarantine logs, and
dual-mono audit/plan/review/apply with copy-output conversion. Advanced
destructive actions still start from reviewed plans and either stay undoable or
require explicit irreversible confirmation.

Remaining advanced work is product polish beyond the current M4 acceptance bar:
new-pack intake presets, before/after cleanup simulation, richer safe-folder
editing surfaces in the TUI/GUI, and future guarded in-place audio replacement
after copy-output conversion has more field validation.

### Similarity And Audio Analysis Gaps

The deterministic crawler is implemented and useful. Remaining work:

- Runtime and cache-size validation on large copied libraries.
- Job/CPU limits and resumability polish for long crawls.
- Optional embedding table/backend after license, privacy, and runtime review.
- Optional Chromaprint/AcoustID-style fingerprints for re-exported or
  metadata-mutated near duplicates.
- Optional audio-listening tag suggestions from model outputs, always
  review-only.

### UI Gaps

M6's read-only TUI baseline is closed. The remaining UI gap is intentionally
later: review/apply surfaces should only be added after the read-only workbench
has more real-library use and every action can stay backed by the same CLI JSON
plans/logs.

## Finish Milestones

### Mini Milestone: M0/M1/M2/M6 Closeout

Goal: close all known straggling work from the mostly-complete stabilization,
beta-freeze, metadata-writing, and read-only TUI milestones before starting the
next similarity expansion slice.

Status: complete on 2026-05-11.

Completed tasks:

- Reconciled this finish plan with the current repo state: M0, M1, M2, and the
  read-only portion of M6 are no longer listed as open baseline work.
- Confirmed M0 documentation and generated-log cleanup through the existing
  README/PHASES/NEXT updates, `.gitignore`, and green validation.
- Confirmed M1 clean install and CI coverage: `uv sync --extra dev`,
  `uv sync --extra metadata --extra dev`, `uv run sfx --help`, Python 3.10/3.11
  CI, JSON smoke, and full local checks are recorded in `NEXT.md`.
- Ran the missing manual similarity-validation beta audit on a bounded copied
  real-library slice:
  `/private/tmp/sfxworkbench_mini_closeout_slice_20260511/audit`.
- Captured performance numbers on that 200-file copied real-library slice:
  scan 1.61s, pack audit 0.17s, metadata write-plan 0.18s, tag propose 0.29s,
  similarity crawl 5.74s, and full similarity-validation beta audit 7.55s.
- Recorded the whole-library force-rescan attempt as performance evidence:
  stopped after 755.56s before report generation, reinforcing that similarity
  validation should stay bounded/manual until M5 adds crawl job controls and
  resume clarity.
- Reviewed mutation command trust language across CLI and implementation
  surfaces. Existing output/help consistently exposes dry-run, reviewed apply,
  backup, quarantine, safe-folder refusal, collision refusal, readback, and undo
  wording for the current beta mutation paths.
- Confirmed M2 scope: reviewed Mutagen and BWF MetaEdit writes have backup,
  readback, logs, index refresh, existing-value protection, and undo guards;
  W64 remains sidecar-first and future iXML/wider BWF writes are deferred.
- Confirmed M6 scope: the read-only Textual alpha has start guidance, review
  queues, saved views, grouped file detail, report/log browsing, summary rows,
  and protected-folder visibility. Mutation UI remains deferred by design.

Validation:

- `uv run --extra dev poe beta-audit /private/tmp/sfxworkbench_mini_closeout_slice_20260511/library --output-dir /private/tmp/sfxworkbench_mini_closeout_slice_20260511/audit --similarity-validation --include-format --limit 200`
  passed.
- `uv run sfx scan /private/tmp/sfxworkbench_mini_closeout_slice_20260511/library --db /private/tmp/sfxworkbench_mini_closeout_slice_20260511/perf_scan.db --force --json`
  passed.
- `uv run sfx packs audit /private/tmp/sfxworkbench_mini_closeout_slice_20260511/library --db /private/tmp/sfxworkbench_mini_closeout_slice_20260511/audit/index.db --json`
  passed.
- `uv run sfx metadata write-plan /private/tmp/sfxworkbench_mini_closeout_slice_20260511/perf_metadata_write_plan.json --db /private/tmp/sfxworkbench_mini_closeout_slice_20260511/audit/index.db --path /private/tmp/sfxworkbench_mini_closeout_slice_20260511/library --limit 200 --json`
  passed.
- `uv run sfx tag propose /private/tmp/sfxworkbench_mini_closeout_slice_20260511/library --db /private/tmp/sfxworkbench_mini_closeout_slice_20260511/audit/index.db --catalog /private/tmp/sfxworkbench_mini_closeout_slice_20260511/mini_ucs_catalog.json --min-confidence 0.6 --limit 200 --json`
  passed.
- `uv run sfx similarity crawl /private/tmp/sfxworkbench_mini_closeout_slice_20260511/library --db /private/tmp/sfxworkbench_mini_closeout_slice_20260511/audit/index.db --cache /private/tmp/sfxworkbench_mini_closeout_slice_20260511/perf_similarity_cache --max-duration 30 --force --limit 200 --json`
  passed.

### Mini Milestone: M3 Closeout

Goal: make metadata/tag review useful without requiring hand-edited JSON plans.

Status: complete on 2026-05-11.

Completed tasks:

- Added normalized `metadata_fields` rows for readable embedded metadata,
  including BEXT, RIFF INFO, and supported Mutagen-backed text tags.
- Populated normalized metadata fields during `sfx scan` and after successful
  embedded metadata write index refresh.
- Exposed indexed embedded fields in `sfx metadata view`.
- Updated `sfx tag propose` to use indexed embedded metadata evidence before
  falling back to direct WAV/RF64 reads.
- Added `sfx tag plan --from-csv` for reviewed bulk tag updates using
  `file_id`, `path`, `filename`, or `stem` selectors plus `field` and `value`.
- Kept CSV imports inside the existing reviewed DB-only tag plan/apply flow, so
  writes still require explicit review/apply gates and anchor validation.

Validation:

- `uv run pytest tests/test_scan.py tests/test_metadata_view.py tests/test_tag_propose.py tests/test_tag_suggest.py -v`
  passed.
- `uv run --extra dev poe check` passed.
- `uv run --extra dev poe json-smoke` passed.

### M0: Stabilize The Current Branch

Goal: make the current repo internally consistent after the recent metadata work.

Status: complete as of 2026-05-11.

Tasks:

- Update `README.md` to include `metadata write-apply`, `metadata write-undo`,
  and the current safety promise for Mutagen writes.
- Update `docs/PHASES.md` implemented command list, safety workflow list, and
  JSON contract list for metadata write apply/undo/readback verification.
- Refresh `NEXT.md` so it reflects the current state instead of the pre-apply
  metadata plan.
- Remove or ignore generated root-level `metadata_write_apply_log_*.json` files.
- Run `uv run --extra dev poe check` and `uv run --extra dev poe json-smoke`.

Acceptance criteria:

- Docs match actual CLI commands.
- No accidental generated logs are left in the repo root.
- Full test/lint suite is green.

### M1: Internal Studio Beta Freeze

Goal: make the current beta-safe product reliable enough for repeated studio
use on copied libraries.

Status: complete as of 2026-05-11 for the current beta baseline.

Tasks:

- Run clean install tests:
  `uv sync --extra dev`, `uv sync --extra metadata --extra dev`, and `uv run sfx --help`.
- Add CI coverage for Python 3.10 and 3.11, or narrow the package claim if 3.10
  is not actually supported.
- Expand fixture workflow tests for:
  `scan -> metadata plan -> review -> apply -> undo`,
  `scan -> packs audit -> plan -> review -> apply -> undo`,
  and stale-plan failures.
- Run `uv run --extra dev poe beta-audit` on a copied real library with and
  without `--include-similarity`.
- Capture performance numbers for scan, pack audit, metadata planning, tag
  propose, and similarity crawl.
- Review command output for trust language: every mutation should clearly say
  dry-run, apply, backup, quarantine, or undo.

Acceptance criteria:

- Internal beta audit bundle is reproducible.
- CI matches claimed Python support.
- No command listed in README fails from a clean checkout.
- Mutation commands have tested recovery paths.

### M2: Finish Metadata Writing

Goal: complete safe embedded metadata writing for standard formats.

Status: complete as of 2026-05-11 for reviewed Mutagen-backed standard tagged
formats and BWF MetaEdit-backed WAV/RF64 BEXT/RIFF INFO writes. Future iXML and
wider BWF field writes remain deferred feature work.

Tasks:

- Build real fixture corpus for each supported format.
- Prove Mutagen mappings on real fixture files, not only mocked readback.
- Add existing-tag read checks before write planning.
- Add explicit `add`, `skip_existing`, and future `replace` behavior in
  embedded write plans.
- Implement BWF MetaEdit fixture execution first:
  copy file, run external backend against copy, read back BEXT, report
  mismatch.
- Implement BWF MetaEdit original apply only after fixture execution is stable:
  backup, apply, readback, log, undo.
- Store pre/post hashes and readback status in metadata apply logs.
- Harden undo to refuse changed targets unless a future force flag is provided.
- Decide and document W64: sidecar-only, unsupported, or proven backend.

Acceptance criteria:

- `.wav` and `.rf64` BEXT writes have the same safety bar as Mutagen writes.
- Standard tagged formats have real fixture tests.
- Existing embedded values are not overwritten accidentally.
- Every original-file write has backup, log, readback, and undo.

### M3: Finish Tagging And Metadata Review

Goal: make metadata/tag review useful at real-library scale.

Tasks:

- Add normalized metadata read tables for embedded field evidence.
- Add user alias/synonym dictionaries.
- Add CSV-backed bulk metadata/tag update plans.
- Expand `tag propose` evidence fusion with embedded metadata and accepted
  semantic tags.
- Calibrate proposal thresholds on copied real libraries.
- Add review summaries that prioritize high-confidence, high-impact batches.
- Keep group-derived take/channel facts structural unless user review proves
  they are valuable as searchable tags.

Acceptance criteria:

- A studio can import UCS data, propose tags, review batches, accept tags,
  export sidecars, and optionally embed supported fields without editing JSON by
  hand.
- Ambiguous filename-only UCS cases stay weak/review by default.

### M4: Finish Advanced Library Maintenance

Goal: cover the remaining professional maintenance workflows without weakening
the beta safety model.

Status: complete on 2026-05-11.

Tasks:

- Add config-backed safe folders and apply them across dedupe, packs, organize,
  rename, metadata, dual-mono, and delete workflows.
- Add preservation-priority presets and score explanations.
- Add database/import compare:
  exact hash first, optional fingerprints later.
- Add processed-file detection as report-only.
- Add permanent delete workflow from quarantine logs only.
- Add dual-mono audit, reviewed plan, and copy-output conversion.
- Keep in-place audio replacement outside the default path until copy-output
  conversion is proven.

Completed scope:

- Config-backed safe folders now guard dedupe, packs, organize, rename,
  metadata writes, dual-mono copy conversion, and permanent delete.
- Preservation rules expose score explanations for reviewer-facing rationale.
- `sfx compare audit/plan` compares candidate imports against an existing index
  using exact MD5 matches and creates import-review plans.
- `sfx processed` reports likely rendered/processed variants without cleanup
  actions.
- `sfx delete plan/review/apply` permanently deletes only paths already present
  in sfxworkbench quarantine logs, requires reviewed plans, and requires
  `--i-understand-permanent-delete --apply`.
- `sfx audio dual-mono audit/plan/review/apply` detects dual-mono stereo files
  and writes approved mono copies to a separate output root without replacing
  originals.

Acceptance criteria:

- Advanced destructive actions start from reviewed plans and cannot operate
  directly on live scan reports.
- Every advanced mutation has logs and recovery or intentionally irreversible
  confirmation.

Validation:

- `uv run pytest tests/test_m4_advanced.py -v` passed.
- `uv run --extra dev poe check` passed.

### M5: Finish Similarity And Audio Analysis

Goal: make similarity useful for discovery and review, not automatic cleanup.

Status: complete on 2026-05-11 for the deterministic/report-only beta scope.

Tasks:

- Add crawl job controls: CPU/job limits, resume reporting, and interruption
  clarity.
- Validate segment thresholds on real libraries.
- Add optional fingerprint backend after dependency/license review.
- Add optional embedding backend table and model/version anchoring.
- Feed similarity and descriptor evidence into `tag propose` as review-only
  support.
- Add similarity review UX contracts for future UI.

Completed scope:

- `sfx similarity crawl` now supports bounded stale-file runs with
  `--max-files` and lightweight CPU yielding with `--throttle-ms`, records
  partial-run status and stop reasons, and reports pending/stale counts for
  resumable follow-up runs.
- Similarity cache records now include backend version and parameter hashes;
  `analysis_runs` stores run parameters, segment method, force/max-file limits,
  and status reason.
- `audio_embeddings` is reserved in schema with model/version/parameter
  anchoring for future embedding backends, without enabling any model by
  default.
- `sfx similarity backends` reports the available deterministic backend and
  explicitly deferred fingerprint/embedding backends for dependency and license
  review.
- `tag propose` includes cached deterministic descriptor evidence as
  review-only support on proposals; it does not use similarity descriptors as
  semantic proof or raise confidence.
- Existing similarity search, segment listing, audit, and feedback JSON remain
  report-only UI contracts for future review surfaces.

Acceptance criteria:

- Similarity search/audit remains report-only.
- False positives are explainable and reviewable.
- Cached analysis can be rebuilt when backend/model parameters change.

Validation:

- `uv run pytest tests/test_similarity.py tests/test_tag_propose.py tests/test_cli_json.py::test_similarity_cli_json_smoke -v` passed.

### M6: Build The Review UI

Goal: make sfxworkbench comfortable for long review sessions without hiding the CLI.

Status: complete as of 2026-05-11 for the read-only Textual alpha baseline.
Review/apply UI surfaces remain intentionally deferred.

Tasks:

- Build a Textual app using CLI JSON and SQLite state.
- Start with read-only dashboards:
  scan state, audit issues, metadata coverage, duplicates, packs, UCS drift,
  pending plans, logs, and protected folders.
- Build decision queues for unsafe filenames, long paths, Unicode
  normalization, missing metadata, UCS validation failures, duplicates, pack
  overlaps, format inconsistencies, tag proposals, and embedded metadata
  conflicts.
- Build a before/after plan viewer for rename, organize, dedupe, packs,
  metadata write, tag apply, and future intake plans.
- Surface the safe-folder firewall and metadata gap report as first-class
  screens.
- Add review/apply surfaces only after the read-only views are stable.
- Use `docs/PRODUCT_DIRECTION.md`, `docs/APP_UI_DIRECTION.md`, and the mockup as
  product/visual direction: safe cleanup workbench, dense review UI, graphite
  panels, off-white workspace, safety colors.
- Keep every UI action backed by the same JSON plans/logs as CLI commands.

Acceptance criteria:

- A user can review and approve plans without opening JSON manually.
- UI never creates a hidden mutation path that bypasses CLI safety rules.

### M7: Public v1 Readiness

Goal: make sfxworkbench installable, documented, and supportable outside the
original development machine.

Status: complete on 2026-05-11 for GitHub-release beta packaging readiness.

Tasks:

- Package install from PyPI or GitHub release.
- Update README quickstart for real users.
- Add changelog entries per milestone.
- Add migration notes for SQLite schema changes.
- Add security/privacy note for commercial audio libraries and optional ML
  analysis.
- Add sample fixture/demo library and screenshots once UI exists.
- Run final clean-machine smoke tests on macOS and Linux.

Completed scope:

- Built source distribution and wheel artifacts with `uv build`.
- Verified a clean Python 3.11 wheel install in `/private/tmp`, then ran
  `sfx --help`, `sfx scan`, and `sfx audit` from the installed console script
  against the committed demo fixture.
- Updated README install guidance for GitHub release wheels, future PyPI
  installs, GitHub source installs, optional metadata extras, and the read-only
  TUI.
- Added release, migration, and demo-library docs:
  `docs/RELEASE.md`, `docs/MIGRATIONS.md`, and `docs/DEMO.md`.
- Expanded `CHANGELOG.md` with milestone-oriented unreleased entries.
- Expanded `SECURITY.md` and `SUPPORT.md` with commercial audio-library privacy,
  generated artifact, and optional analysis guidance.
- Updated package metadata description and documentation URL.

Acceptance criteria:

- A new user can install, scan a copied library, review reports, apply safe
  workflows, and undo changes by following README alone.
- CI, docs, and package metadata agree.

Validation:

- `uv sync --extra dev` passed.
- `uv sync --extra metadata --extra dev` passed.
- `uv run sfx --help` passed.
- `uv build` passed and produced `dist/sfxworkbench-0.1.0.tar.gz` plus
  `dist/sfxworkbench-0.1.0-py3-none-any.whl`.
- `uv venv --python 3.11 /private/tmp/sfxworkbench_m7_smoke` passed.
- `uv pip install --python /private/tmp/sfxworkbench_m7_smoke/bin/python dist/sfxworkbench-0.1.0-py3-none-any.whl` passed.
- `/private/tmp/sfxworkbench_m7_smoke/bin/sfx --help` passed.
- `/private/tmp/sfxworkbench_m7_smoke/bin/sfx scan tests/fixtures/library_basic --db /private/tmp/sfxworkbench_m7_smoke/index.db --json` passed.
- `/private/tmp/sfxworkbench_m7_smoke/bin/sfx audit --db /private/tmp/sfxworkbench_m7_smoke/index.db --json` passed.
- `uv run --extra dev poe check` passed.

### M8: Local Validation And TUI Improvement

Goal: exercise the finished beta locally on realistic copied-library workflows
while turning the read-only Textual alpha into a more useful daily review
surface.

Status: in progress as of 2026-05-11.

Tasks:

- Create a local validation workspace with copied audio, generated reports,
  throwaway SQLite indexes, and safe output/quarantine roots.
- Run the core happy paths end to end on local data:
  scan, audit, search, clean preview, dedupe plan/review/apply/undo, rename
  preview/apply/undo, organize review/apply/undo, pack audit/plan/review/apply,
  tag suggest/plan/review/apply, metadata write fixture/readback, similarity
  crawl/search/audit, advanced compare/processed/delete/dual-mono workflows.
- Capture usability notes from each local run: confusing command output,
  missing report fields, stale-plan surprises, slow steps, and places where the
  next action is not obvious.
- Improve the TUI around real review sessions:
  clearer start checklist, report discovery, plan/log summaries, file detail,
  queue filtering, similarity feedback visibility, protected-folder visibility,
  and command copy/run affordances.
  - Started: the report browser now auto-discovers JSON artifacts beside the
    validation DB, near the last scanned root, and in `~/reports`; file detail
    now includes indexed embedded metadata fields from SQLite.
  - Completed Start-page optimization slice: compact workflow areas, persistent
    two-line orientation/status strip, responsive table columns, selected-area
    command/detail table, grouped library status, and no always-visible Start
    scrollbar when content fits.
  - Converted the feature coverage map into focused area tabs: Import, Cleanup,
    Metadata, Tags/UCS, Similarity, and Advanced each pair workflow/detail rows
    with their relevant review queues and matching files. Files and Reports
    stay global because they answer cross-cutting questions.
  - Expanded Files into a live SQLite-backed master list with per-row accepted
    tag, indexed embedded-field, and filename-issue counts while keeping the
    adapter capped for large-library performance.
  - Added a read-only button pass for the guided TUI: Start, Files, Reports, and
    each focused area now expose button controls for opening selected queues,
    jumping to matching files, finding related reports, clearing filters, and
    opening selected start recommendations.
  - Refined the buttons into action-oriented controls rather than duplicate
    page navigation, and added an editable library path context so generated
    workflow/queue commands can target a different copied library root without
    mutating the index.
  - Persisted the explicit TUI library path in the validation DB so reopening
    the TUI resumes the same generated-command root, while "Use Indexed Root"
    can still switch back to the last scan root.
  - Removed the Header clock and trimmed repeated summary fields from detail
    panes so detail tables focus on extra context and commands.
  - Routed default apply/undo logs through `apply_logs/` folders beside their
    source reports/plans, and taught the TUI report browser to include that
    folder.
  - Added the standalone Phase 0 `audit.py` filesystem audit as an Import
    workflow for first-pass folder review before a library is indexed.
- Keep TUI mutation actions out of scope until local read-only review flows feel
  reliable and every action maps cleanly to existing CLI JSON plans/logs.
- Add focused tests for any TUI data adapters or JSON contracts changed during
  the local validation pass.

Acceptance criteria:

- A local copied-library session can be driven from the TUI plus documented CLI
  commands without hand-opening JSON except for debugging.
- Every confusing or risky local behavior found during validation is either
  fixed, documented, or recorded as a follow-up.
- TUI improvements remain backed by the same CLI/SQLite data contracts and do
  not introduce hidden mutation paths.

Validation:

- Run `uv run --extra tui --extra dev sfx tui --help`.
- Run targeted `tests/test_tui_data.py` coverage for changed TUI adapters.
- Run `uv run --extra tui --extra dev poe check` before closing the milestone.

### M9: Full-Feature Operations Workbench

Goal: make the TUI/GUI direction cover the full sfxworkbench product surface
instead of narrowing around only metadata or dedupe.

Status: implemented as an initial TUI/action-contract slice.

Completed scope:

- Replaced the Start/workflow/queue/report-browser structure with feature tabs:
  Scan, Files, Clean, Dedupe, Organize, Metadata, Similarity, and Advanced.
- Moved normal UI framing to library path plus status; index/cache path is only
  surfaced in Advanced findings.
- Added shared TUI/GUI action results for scan, full audit, junk cleanup,
  dedupe plans/review/apply, pack audit/plan/review/apply, portable rename
  preview/apply/undo, metadata audit/tag plan/review/apply/sidecar export, and
  similarity crawl.
- Added `sfx audit-bundle PATH --db DB --output-dir DIR --json` to refresh the
  index and write core read-only audit artifacts for scan health, metadata,
  duplicates, groups/format, UCS validation when available, and pack overlap.
- Reworked Files so an indexed DB shows file rows immediately and an empty DB
  gives a scan-oriented empty state.
- Embedded generated reports/logs into each feature page by relevance instead
  of requiring a standalone Reports page.

Validation:

- `uv run --extra tui --extra dev pytest tests/test_tui_data.py tests/test_tui_actions.py tests/test_apply_logs.py tests/test_json_contracts.py::test_audit_search_export_json_contract -v`
  passed.

## Recommended Order

Completed baseline milestones:

1. M0: stabilize docs and remove generated artifacts.
2. M1: beta freeze and real-library dry-run audit.
3. M2: finish current-scope metadata writing.
4. M3: finish tag review ergonomics.
5. M4: advanced workflows.
6. M5: similarity expansion.
7. M6: read-only Textual UI baseline.
8. M7: public release readiness.

Remaining order:

1. M8: local validation and TUI improvement.

## Near-Term Sprint

The next focused sprint should be M8 local validation and TUI improvement:

1. Create the local validation workspace and run the main report/review/apply
   loops against copied data.
2. Convert friction found during those runs into TUI data/view improvements.
3. Keep mutation in the CLI while using the TUI to make review state, next
   commands, and generated artifacts easier to navigate.
4. Preserve the release-execution follow-up: run the wheel smoke test on Linux
   before advertising the release broadly.
