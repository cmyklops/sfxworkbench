# Audio Similarity Crawler Roadmap

wavwarden should treat audio similarity as an optional analysis layer, not as
part of the baseline cleanup scan. The goal is to borrow the strongest product
lesson from Sononym and the strongest implementation lesson from Soundminer:
descriptor and similarity browsing are useful, but large libraries need an
offline, resumable crawler that caches evidence before any UI tries to browse
it.

## Roadmap Fit

The crawler belongs after the current cleanup, organization, dedupe, and tag
suggestion foundations are stable, and before a Textual/Tauri discovery UI.
Roadmap placement:

```text
Phase 0: standalone audit
Phase 1: scan/search/clean/dedupe/export
Phase 2: cleanup tooling, rename, organize, metadata/tag plans
Phase 2.5: audio descriptors and similarity crawler
Phase 3: Textual TUI, then later GUI discovery workflows
```

`sfx scan` should stay fast and metadata-oriented. Similarity is heavier,
optional, model-dependent, and may need CPU throttling. It should be run
explicitly:

```bash
uv run sfx similarity crawl ~/CommercialLibraries \
  --db ~/.wavwarden/index.db \
  --cache ~/.wavwarden/similarity \
  --max-duration 30

uv run sfx similarity search --file ~/Desktop/query.wav \
  --db ~/.wavwarden/index.db \
  --limit 50 \
  --json
```

Implemented first slice:

- `sfx similarity crawl PATH`
- `sfx similarity search --file QUERY`
- `sfx similarity audit PATH`
- deterministic backend name: `deterministic_v1`
- SQLite-backed `analysis_runs` and `audio_descriptors` tables
- optional cache directory for run report JSON
- incremental skips when path anchors still match size, mtime, and MD5
- descriptor fields for peak, RMS, crest factor, silence ratio, clipping count,
  zero-crossing rate, transient density, spectral centroid/bandwidth/rolloff/
  flatness, and duration bucket
- nearest-neighbor search over cached descriptor vectors with distance and
  0-1 score output
- report-only near-duplicate groups from cached descriptors, with exact MD5
  duplicate pairs excluded by default

## Product Lessons

Sononym is the product reference for why this matters:

- sample libraries benefit from descriptor-driven browsing
- perceptual similarity is useful for discovery and near-duplicate review
- hide, ignore, accepted, rejected, favorite, and manual states should be
  DB-only before any filesystem action
- false positives are expected, so similarity is evidence, not proof

Soundminer-style crawlers are the implementation reference for how to make it
scale:

- crawl in a separate command instead of blocking the main app
- skip files whose anchors have not changed
- resume interrupted runs
- support job/CPU limits so users can keep working
- cache small per-file and per-segment analysis artifacts
- allow scheduled or overnight runs
- separate expensive embedding generation from fast search/index loading

## Initial Scope

The first implementation should be boring and report-first:

1. Cheap audio descriptors: implemented in the first crawler slice.
   peak, RMS, crest factor, silence, spectral shape, transient density,
   duration buckets, clipping flags, channel count, sample rate, bit depth.
2. Segment/event detection:
   identify candidate regions inside longer files so one ambience or designed
   sound can produce multiple searchable moments.
3. Optional embeddings:
   store per-file and per-segment vectors from a clearly named model/backend.
4. Search/report commands: first search and near-duplicate audit commands
   implemented.
   return nearest neighbors as JSON with distances, anchors, and caveats.

Do not let the first crawler quarantine, rename, delete, retag, or mutate audio.
It can later feed reviewed workflows such as near-duplicate reports or
audio-listening tag suggestions, but those should stay explicit and reviewable.

## Suggested Data Model

Similarity data should live outside the existing `files` row shape:

- `analysis_runs`: backend, model/tool version, parameters, start/end time,
  status, failure counts
- `audio_descriptors`: cheap computed descriptors keyed to indexed file anchors
- `audio_segments`: file id, start time, end time, method, confidence
- `audio_embeddings`: file id, optional segment id, backend, dimensions, vector
  storage reference or packed blob
- `similarity_feedback`: DB-only accepted, ignored, hidden, favorite, or
  rejected neighbor relationships

Every analysis record should include enough anchors to detect staleness:

- file path
- size
- mtime
- MD5 when available
- model/backend name
- model/backend version
- parameters or preset name
- generated timestamp
- failure reason when analysis fails

## Backend Candidates

Start with deterministic descriptors because they are cheap, explainable, and
useful even without ML dependencies.

Optional later backends:

- Chromaprint/AcoustID-style fingerprints for perceptual near-duplicate
  candidates
- PANNs-style classifiers for broad sound-event labels
- CLAP-style audio/text embeddings for "find sounds like this" and text-to-audio
  ranking

Any ML backend needs explicit license, provenance, privacy, runtime, and storage
review before becoming a documented recommended path.

## UI Implications

A future Textual or GUI layer can build Sononym/Soundminer-like discovery on top
of crawler data:

- nearest-neighbor lists
- cluster views
- segment-level matching
- "neighbors of neighbors" graph exploration
- DB-only favorites, hides, ignores, and reviewed similarity feedback

The UI should consume CLI JSON and SQLite state. It should not be the first
place where similarity semantics are defined.
