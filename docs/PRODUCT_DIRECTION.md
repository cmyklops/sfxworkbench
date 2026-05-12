# sfxworkbench Product Direction

sfxworkbench is a safe cleanup and metadata repair workbench for sound effects
libraries. It is not a daily sample manager, Soundminer replacement, BaseHead
replacement, SoundQ replacement, Sononym replacement, or AI tagging app.

The strongest product wedge is trust: dry-run first, review everything, protect
source folders, undo changes where possible, and make messy libraries safer to
use in the tools sound editors already prefer.

## Core Promise

Clean up a messy SFX library without accidentally damaging the collection.

Every destructive action should be:

- previewed before apply
- reviewable in batches
- protected by safe-folder rules
- logged
- undoable where possible
- exportable for external review

## Product Pillars

### New Pack Intake

A guided workflow for deciding whether and how to add a downloaded library,
vendor pack, recovered folder, or client delivery into an existing collection.

It should scan the incoming pack before import, compare it with the existing
library, and produce a reviewable intake plan. The workflow should detect exact
duplicates, near-duplicates, format variants, folder/package overlap, vendor and
product naming, unsafe filenames, long paths, UCS-looking filenames, embedded
metadata coverage, and likely destination folders.

The user question is: "Can I safely add this pack to my master library, and what
mess will it introduce?"

### Before/After Cleanup Simulator

A visual migration-review surface for planned changes before anything touches
disk.

It should summarize file renames, folder moves, duplicate quarantines, metadata
writes, sidecar imports/exports, affected file counts, bytes moved, conflicts,
protected paths, and undo availability.

This should feel like reviewing a database or filesystem migration, not browsing
files casually.

### Safe-Folder Firewall

A central protection system for important folders such as raw recordings, master
libraries, client deliverables, vendor originals, and "do not modify" areas.

Safe folders should block rename, move, quarantine, delete, and metadata-write
actions inside protected paths. Every plan should surface the protection reason
when it skips or refuses an action. Shared config files should make these rules
repeatable across studio machines and projects.

### UCS Migration Assistant

A focused workflow for moving libraries toward Universal Category System
compatibility without pretending filename shape is semantic truth.

It should import the official UCS catalog, validate UCS-looking filenames,
detect fake or vendor-specific prefixes, suggest category and subcategory with
evidence, separate filename provenance from semantic tags, review suggestions
before accepting them, rename only after review, export Soundminer/BaseHead/SoundQ
friendly metadata, and write UCS data into supported fields only when safe.

UCS-looking filenames are evidence, not proof. sfxworkbench should explain why it
suggests a category.

### Pack Overlap And Duplicate Intelligence

A stronger duplicate system than simple MD5 matching.

The product should combine exact duplicate detection, folder signatures, pack
overlap reports, same-content/different-folder checks, same-sound/different-name
candidates, same-sound/different-metadata candidates, format variant grouping,
preservation-priority rules, and quarantine-first workflows.

The user question is: "Which copies are redundant, and which folder should I
keep?"

### Metadata Gap Report

A high-value report that explains what is missing or inconsistent before asking
the user to change anything.

It should cover missing BEXT, missing iXML, missing descriptions, DB-only tags
that are not embedded, unusual sample rates, mixed bit depth inside related
groups, inconsistent channel counts, existing embedded metadata conflicts, and
unsupported write formats.

This report is a natural free-product conversion hook because it demonstrates
library risk without requiring mutation.

### Review Queues

The UI should be built around decision queues, not raw tables.

Important queues include obvious duplicates, possible duplicates, pack overlaps,
unsafe filenames, long paths, Unicode normalization issues, missing metadata, UCS
validation failures, suggested UCS tags, embedded metadata conflicts, format
inconsistencies, and review-later imports.

Queues should support approving safe batches, rejecting, ignoring, revealing in
Finder, auditioning, comparing metadata, exporting reports, and applying reviewed
changes. Mutation actions should remain behind explicit confirmation gates.

### Compatibility, Not Replacement

sfxworkbench should cooperate with existing sound-library tools.

Important integration surfaces include CSV export, JSON plans, sidecar metadata
export/import, BEXT/iXML where safe, Soundminer-friendly metadata fields,
BaseHead/SoundQ-compatible embedded metadata, Finder reveal, external editor
open, and optional drag-to-DAW later.

Positioning: use sfxworkbench before Soundminer, BaseHead, SoundQ, or Sononym, not
instead of them.

### Evidence-Based Tag Suggestions

Tag suggestions should show why they exist.

Evidence sources include filename, folder path, related group, UCS catalog match,
existing embedded metadata, accepted tags, similarity group, and future optional
audio analysis.

Suggestion states should include strong, review, weak, blocked, accepted,
rejected, and ignored. The app should avoid presenting guesses as facts.

### Cleanup Plans With Undo

Every workflow should produce a plan first.

Plan types include rename, organize, duplicate quarantine, pack consolidation,
metadata write, tag apply, and new pack intake. Apply logs should include
pre-apply path, post-apply path, file size, mtime, hash when available, backup
path when relevant, errors, and undo status.

## GUI Information Architecture

Main navigation for the polished app should include:

- Dashboard
- Intake
- Search
- Cleanup
- Duplicates
- Metadata
- UCS
- Similarity
- Reports
- Logs
- Settings

Dashboard signals should include indexed files, duplicate groups, missing
metadata, filename issues, UCS issues, pack overlaps, pending review actions,
and protected folders.

## Free And Paid Boundary

Likely free features:

- scan library
- search indexed files
- audit reports
- metadata gap report
- duplicate report
- UCS validation report
- preview cleanup plans
- export CSV/JSON reports

Likely paid features:

- apply rename plans
- apply organize plans
- quarantine duplicates
- apply pack cleanup
- write metadata
- import/export sidecars
- approve review queues
- undo workflows
- batch processing

This boundary should remain secondary to trust. Free users should still see what
sfxworkbench would do before being asked to pay for mutation or batch workflow
execution.

## TUI Implications

The first Textual TUI should not try to be the polished GUI. It should validate
the product model with lower risk:

- dashboard signals
- review queues
- before/after plan viewer
- safe-folder firewall visibility
- metadata gap report
- search and file detail views
- report/log browser

Mutation from the TUI can come after the read-only review workbench feels
trustworthy.
