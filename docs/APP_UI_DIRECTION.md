# sfxworkbench App UI Direction

This note preserves the first visual direction mockup for sfxworkbench's eventual app surface.
Product scope and workflow priorities live in
[`PRODUCT_DIRECTION.md`](PRODUCT_DIRECTION.md); this file is the visual and
interaction-tone companion.

![App UI direction mockup](assets/app-ui-direction-mockup.png)

## Intent

The website can be expressive, but the app itself should feel like a careful audio-maintenance workbench:

- Dense, keyboard-friendly, and built for repeated review work.
- Audio-centric without becoming decorative: waveform strips, spectrogram hints, channel meters, file trees, and scan status indicators.
- Explicit about safety state: dry-run, review, quarantine, undo, validation, and readback.
- Calm enough for long sessions, with signal colors used consistently.

## Visual Language To Carry Forward

- Graphite inspection panels on an off-white workspace.
- Calibrated green for safe/accepted states.
- Muted signal blue for indexed or informational states.
- Amber for review/warning states.
- Small red markers for errors or destructive-risk attention.
- Practical technical labels such as `BWF/iXML`, `SQLite index`, `UCS drift`, `dry-run first`, and `quarantine, not delete`.

## Likely App Surfaces

- Scan dashboard
- New pack intake review
- Searchable file table
- Filename and metadata issue queues
- Duplicate and pack-overlap review
- Before/after cleanup simulator
- Safe-folder firewall
- UCS migration assistant
- Metadata gap report
- Similarity group review
- Tag and metadata write planning
- Apply/undo logs
- Command and validation history

## First TUI Validation Target

The first Textual TUI exists behind `sfx tui` as an alpha review workbench. It
should validate the review-workbench shape before the polished GUI exists, and
it should continue to prioritize read-only or dry-run surfaces:

- Dashboard signals for indexed files, duplicates, missing metadata, filename
  issues, UCS issues, pack overlaps, pending review actions, and protected
  folders.
- Review queues for unsafe filenames, long paths, Unicode normalization, missing
  metadata, UCS validation failures, duplicates, pack overlaps, format
  inconsistencies, tag proposals, and embedded metadata conflicts.
- A before/after plan viewer for rename, organize, dedupe, packs, metadata
  write, tag apply, and later pack-intake plans.
- Safe-folder firewall visibility from shared config.
- Metadata gap report drilldown.
- Search, file detail, report browser, and apply/undo log browser.

The TUI can add approve/apply/undo workflows later, once the read-only review
model feels trustworthy against real libraries.

Current alpha coverage:

- Dashboard signals from SQLite.
- Start tab for first-run setup, quick indexing, full audit, and payoff-ranked
  next steps.
- Payoff-ranked first-pass worklist that points users toward the biggest
  cleanup/review wins before lower-impact inspection, including the matching
  CLI next action for each step.
- Review queue counts and queue-specific next steps from SQLite.
- First indexed-file table with richer file detail and file-specific next
  actions.
- JSON report/plan/log summaries for the before/after plan viewer, separated
  by report category.
- Safe-folder firewall visibility from shared config.

The mockup is a visual reference, not a literal app specification. The production app should prioritize clarity, speed, and predictable review flows over homepage drama.
