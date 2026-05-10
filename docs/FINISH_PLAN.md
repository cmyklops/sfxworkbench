# wavwarden Finish Plan

Generated: 2026-05-09

This plan audits the remaining work needed to move wavwarden from the current
Internal Studio Beta codebase toward a finished, trustworthy v1 product. It is
based on the implemented CLI surface, current roadmap docs, tests, and the app
UI direction reference in `docs/APP_UI_DIRECTION.md`.

## Current State

wavwarden already has a broad, safety-first CLI core:

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
  proposals, DB-only tag plans, sidecar export/import, and tag apply logs.
- Deterministic similarity crawl, segment listing, whole-file and segment
  search/audit, plus DB-only feedback states.
- JSON contracts and tests for the major automation surfaces.
- A first app UI direction mockup and note under `docs/assets/` and
  `docs/APP_UI_DIRECTION.md`.

The core safety posture is intact: mutating workflows are dry-run by default,
reviewed, backed up, quarantined, or undoable.

## Audit Findings

### Documentation Drift

Some durable docs still describe older behavior and need a synchronization pass:

- `README.md` says the "Reports And Metadata" section is report-only, but that
  list now includes commands with real reviewed apply behavior, and it does not
  yet mention `metadata write-apply` or `metadata write-undo`.
- `docs/PHASES.md` lists metadata write planning/readback but not the latest
  Mutagen apply/undo/readback verification flow.
- `docs/PHASES.md` JSON contract list does not yet include
  `metadata write-apply` or `metadata write-undo`.
- `NEXT.md` still says to decide whether to build an embedded metadata write
  plan, but that lane has now advanced to Mutagen-backed original-file writes.
- Two root-level generated metadata apply logs are present and should either be
  removed before commit or covered by `.gitignore`.

### Beta Readiness Gaps

The beta-safe workflows are mostly present. The remaining beta work is about
proving them on clean installs, realistic fixture sequences, copied real
libraries, and user-facing documentation.

Important gaps:

- Clean install and packaging validation from a fresh machine/environment.
- Full docs-to-CLI command parity.
- Real-library dry-run audit bundles captured and reviewed after the recent
  metadata-write additions.
- More end-to-end fixture workflows for complete command sequences, especially
  metadata write apply/undo and pack/organize edge cases.
- CI remains Python 3.11-only; the package claims Python 3.10+.

### Metadata Writing Gaps

Mutagen-backed formats have the first safe path. Remaining work:

- Real BWF/WAV apply through BWF MetaEdit, including fixture execution, original
  apply, backup, readback, undo, and version capture.
- Real tiny fixture files for each supported standard format:
  `.flac`, `.mp3`, `.m4a`, `.ogg`, `.opus`, `.aif`, `.aiff`.
- Field-by-field mapping decisions by container, including UCS provenance,
  semantic category/subcategory, keywords, originator, take number, and channel
  position.
- Existing embedded metadata reads before embedded write planning, so non-empty
  fields default to skip unless the user explicitly chooses replace.
- W64 policy: keep sidecar-first unless a safe write/readback backend is proven.
- Stronger apply/undo guards: store pre/post hashes in logs and refuse undo when
  the target has changed unexpectedly unless a future explicit force flag is
  provided.

### Tagging And Metadata Model Gaps

The current `accepted_tags` path works, but the long-term model needs more
state:

- Normalized embedded metadata table(s), such as `metadata_fields`, for read
  evidence and write conflict checks.
- Tag states beyond accepted DB-only values: suggested, rejected, hidden,
  manual, auto, alias, provenance, and semantic.
- User alias/synonym dictionaries for filename/path matching.
- CSV-backed bulk find/replace through reviewed tag plans.
- Better `tag propose` calibration on real libraries, especially noisy terms
  such as short category/subcategory words.
- Audio descriptor and similarity evidence feeding proposals without automatic
  tagging.

### Advanced Workflow Gaps

The advanced roadmap is clear but mostly not implemented:

- Shared config-backed safe folders across all planners, not only CLI overrides
  for dedupe/packs.
- Preservation-priority scoring with visible rationale across dedupe, packs,
  and future import compare workflows.
- Workflow presets over existing commands, such as `internal-beta`,
  `duplicate-review`, `metadata-prep`, and `advanced-forensics`.
- Database/import compare before adding a new pack/library to a master index.
- Processed-file detection for normalized, reverbed, denoised, stretched, or
  pitched variants.
- Permanent deletion only from reviewed quarantine logs.
- Dual-mono audit, reviewed copy-output conversion, and later guarded in-place
  replacement.

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

The CLI JSON surface is ready to support a review UI, but no UI exists yet.

The first UI should be Textual, not Tauri. It should use the visual direction in
`docs/APP_UI_DIRECTION.md` and `docs/assets/app-ui-direction-mockup.png`, while
staying dense and workbench-like:

- Scan dashboard and command history.
- Searchable file table.
- Filename, metadata, and UCS issue queues.
- Duplicate and pack-overlap review.
- Tag and metadata write planning, apply, readback, and undo logs.
- Similarity group review.
- Safe-folder and preservation-priority controls.

## Finish Milestones

### M0: Stabilize The Current Branch

Goal: make the current repo internally consistent after the recent metadata work.

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

Acceptance criteria:

- Advanced destructive actions start from reviewed plans and cannot operate
  directly on live scan reports.
- Every advanced mutation has logs and recovery or intentionally irreversible
  confirmation.

### M5: Finish Similarity And Audio Analysis

Goal: make similarity useful for discovery and review, not automatic cleanup.

Tasks:

- Add crawl job controls: CPU/job limits, resume reporting, and interruption
  clarity.
- Validate segment thresholds on real libraries.
- Add optional fingerprint backend after dependency/license review.
- Add optional embedding backend table and model/version anchoring.
- Feed similarity and descriptor evidence into `tag propose` as review-only
  support.
- Add similarity review UX contracts for future UI.

Acceptance criteria:

- Similarity search/audit remains report-only.
- False positives are explainable and reviewable.
- Cached analysis can be rebuilt when backend/model parameters change.

### M6: Build The Review UI

Goal: make wavwarden comfortable for long review sessions without hiding the CLI.

Tasks:

- Build a Textual app using CLI JSON and SQLite state.
- Start with read-only dashboards:
  scan state, audit issues, metadata coverage, duplicates, packs, and tags.
- Add review/apply surfaces only after the read-only views are stable.
- Use `docs/APP_UI_DIRECTION.md` and the mockup as visual direction:
  dense workbench, graphite panels, off-white workspace, safety colors.
- Keep every UI action backed by the same JSON plans/logs as CLI commands.

Acceptance criteria:

- A user can review and approve plans without opening JSON manually.
- UI never creates a hidden mutation path that bypasses CLI safety rules.

### M7: Public v1 Readiness

Goal: make wavwarden installable, documented, and supportable outside the
original development machine.

Tasks:

- Package install from PyPI or GitHub release.
- Update README quickstart for real users.
- Add changelog entries per milestone.
- Add migration notes for SQLite schema changes.
- Add security/privacy note for commercial audio libraries and optional ML
  analysis.
- Add sample fixture/demo library and screenshots once UI exists.
- Run final clean-machine smoke tests on macOS and Linux.

Acceptance criteria:

- A new user can install, scan a copied library, review reports, apply safe
  workflows, and undo changes by following README alone.
- CI, docs, and package metadata agree.

## Recommended Order

1. M0: stabilize docs and remove generated artifacts.
2. M1: beta freeze and real-library dry-run audit.
3. M2: finish metadata writing because audio mutation is the highest-risk
   already-started lane.
4. M3: finish tag review ergonomics.
5. M4: advanced workflows.
6. M5: similarity expansion.
7. M6: Textual UI.
8. M7: public release polish.

## Near-Term Sprint

The next focused sprint should be M0 plus the first half of M1:

1. Update README, PHASES, and NEXT.
2. Remove or ignore generated metadata apply logs.
3. Add JSON contract coverage for `metadata write-apply` and `metadata write-undo`.
4. Add CI Python 3.10.
5. Run clean install with `--extra metadata`.
6. Run `poe check`, `poe json-smoke`, and one beta audit bundle.

That sprint turns the current feature-rich branch into a coherent beta baseline
before more feature work is layered on.
