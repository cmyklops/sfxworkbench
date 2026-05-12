# SQLite Migration Notes

sfxworkbench keeps its working index in SQLite, usually at
`~/.sfxworkbench/index.db`. Schema setup is idempotent: every command that opens
the database calls the same schema initializer before reading or writing.

## Current Policy

- Schema changes must be additive unless a release explicitly documents a
  manual migration.
- Existing `files` rows and the `files_fts` triggers must remain compatible
  with older indexes.
- Generated JSON reports and plans carry their own `schema_version`; breaking
  JSON contract changes require a version bump.
- Before a public release, run an old-index smoke test by opening a copied DB
  with the new CLI and running `sfx audit`, `sfx search`, and at least one
  report-only command.

## 0.1.0 Beta Schema

The 0.1.0 beta schema includes:

- `files`, `files_fts`, `fn_issues`, and `scan_meta` for the core index.
- `accepted_tags`, `metadata_fields`, and `tag_apply_log` for reviewed DB-only
  tags and metadata write logs.
- `analysis_runs`, `audio_descriptors`, `audio_segments`, and
  `similarity_feedback` for deterministic similarity analysis.
- `audio_embeddings` reserved for future optional embedding backends. No model
  runs by default, and no embedding vectors are generated in the beta.

## Recent Additive Columns

Similarity analysis rows now record backend/version/parameter anchors:

- `analysis_runs.backend_version`
- `analysis_runs.parameters_json`
- `analysis_runs.parameters_hash`
- `analysis_runs.segment_method`
- `analysis_runs.max_files`
- `analysis_runs.force`
- `analysis_runs.status_reason`
- `audio_descriptors.backend_version`
- `audio_descriptors.parameters_hash`
- `audio_segments.backend_version`
- `audio_segments.parameters_hash`

If these columns are missing, opening the DB with the current CLI adds them.
Existing descriptors without these anchors are treated as stale and rebuilt by
the next matching `sfx similarity crawl`.

## Backup Guidance

SQLite indexes are reproducible from the source library, but reviewed DB-only
tags and similarity feedback live only in the DB unless exported. Before
upgrading or deleting an index:

```bash
cp ~/.sfxworkbench/index.db ~/.sfxworkbench/index.backup.db
sfx tag sidecar-export ~/reports/accepted_tags.sidecar.json --db ~/.sfxworkbench/index.db
sfx similarity feedback list --db ~/.sfxworkbench/index.db --json > ~/reports/similarity_feedback.json
```
