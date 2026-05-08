# Metadata Tagging Plan

Tagging should follow wavwarden's existing safety model:

`scan` observes files -> `audit` reports gaps -> `tag/suggest` creates reviewed
plans -> `tag --apply` validates and writes metadata -> `scan --force` confirms
results.

Core product rule: respect existing filenames and embedded metadata. Many users
have years of muscle memory around vendor names, custom descriptions, DAW search
terms, and private tagging conventions. wavwarden should preserve existing
human-entered metadata by default and propose additions as reviewed suggestions,
not replacements.

Professional Soundminer-oriented tools reinforce a useful lesson: metadata
workflows need field-level review controls. wavwarden should support bulk
find/replace and CSV-backed updates eventually, but they should pass through the
same reviewed-plan model as tag suggestions.

Sononym reinforces a complementary lesson: tags are stateful review data, not
just strings. Future wavwarden tag tables should distinguish suggested tags,
accepted DB-only tags, rejected or hidden suggestions, manual user tags,
auto-tags from filename/path/metadata evidence, UCS category tags, aliases, and
synonym matches. Search and audit views should also be able to show only the
metadata fields that are actually present in a selected library, so sparse
metadata does not create unusable empty tables.

Default metadata-write policy:

- read existing embedded tags before planning writes
- never overwrite a non-empty existing value unless the plan explicitly marks
  that field as `replace`
- treat new fields and empty-field fills as `add`
- keep original value, proposed value, source, confidence, and evidence in the
  reviewed plan
- apply only reviewed entries
- write an immutable apply log with tool versions and file anchors
- prefer DB-only accepted tags and sidecars before binary WAV mutation

## Phase A: Inventory, No Writes

First, improve metadata reads before adding writers.

Best immediate candidate:

- `wavinfo` is MIT licensed and directly supports richer professional WAV
  metadata reads, including BWF, iXML, RIFF INFO, RF64, ADM, cue markers, and
  sampler chunks. Evaluate it before expanding wavwarden's custom RIFF parsing.

Current implementation:

- `audio.read_audio_info()` keeps `soundfile` as the required core audio reader.
- If the optional `metadata` extra is installed, wavwarden probes WAV metadata
  with `wavinfo` and records read-only presence flags for BWF/iXML, RIFF INFO,
  ADM, cue markers, and sampler chunks in `AudioInfo`, SQLite scan rows, and
  CSV export.
- Install the optional reader with `uv pip install -e ".[metadata,dev]"`.

Potential additive tables:

- `metadata_fields`: normalized metadata by file, namespace, key, value, source
- `metadata_raw`: raw or parsed bext/iXML/XML snippets for debugging
- `tag_suggestions`: proposed tags with confidence, evidence, and status
- `accepted_tags`: DB-only accepted/manual/auto tag assignments, including
  source and whether the tag is hidden/rejected/manual/automatic
- `tag_aliases`: user-defined aliases and synonyms for filename/path matching
- `tag_apply_log`: immutable write attempts and outcomes

Keep `files.has_bext` and `files.has_ixml` as fast audit booleans.

## Phase B: Filename and UCS Suggestions

Add a pure parser module, separate from `rename.py`, that suggests metadata from:

- UCS-like filename stems
- parent folders
- common take/version suffixes
- known abbreviations such as `AMB`, `SFX`, and `FOLEY`
- optional user dictionaries
- user-defined aliases and synonyms, including simple singular/plural or
  conjugation-style expansions

Suggestions should be data, not writes:

```json
{
  "field": "description",
  "value": "Gunshot 01",
  "source": "filename",
  "method": "ucs_heuristic",
  "confidence": 0.86,
  "evidence": ["SFX_GUNSHOT_01.wav"]
}
```

## Phase C: Reviewed Tag Plans

Suggested CLI:

```bash
uv run sfx tag PATH --from-filename --output tag_plan.json
uv run sfx tag --from-csv metadata.csv --output tag_plan.json
uv run sfx tag --apply tag_plan.json --db ~/.wavwarden/index.db
```

Each plan entry should include validation anchors:

- path
- file id when indexed
- size and mtime
- MD5 when available
- target metadata fields
- action per field: `add`, `skip_existing`, or explicit `replace`
- existing value when present
- proposed value
- source, confidence, and evidence

Apply should refuse or warn when files changed after the plan was created.

Bulk find/replace should use the same plan format:

```bash
uv run sfx tag plan --find-replace metadata.csv --output tag_plan.json
uv run sfx tag review tag_plan.json --approve-entry 1
uv run sfx tag apply tag_plan.json --require-reviewed
```

The initial implementation should be DB-only or sidecar-only. Embedded metadata
writes remain a later step.

## Phase D: Metadata Writes

Start with DB-only accepted tags and CSV export. Then add sidecar output. Binary
audio mutation comes last.

Preferred write ladder:

1. DB-only accepted tags
2. sidecar JSON/XML export
3. BWF/iXML writes for proven-safe formats
4. optional overwrite mode with original-file backup/quarantine

BWF MetaEdit is the leading candidate for Broadcast WAV metadata because it is
designed for importing, editing, embedding, and exporting BWF metadata. The BWF
format itself is specified by EBU Tech 3285. Mutagen is useful for many tagged
formats, but its license and WAV/BWF/iXML limits need evaluation before making
it a dependency.

Use BWF MetaEdit as the professional reference behavior first. If wavwarden
wraps it, treat it as an external command with explicit version capture in tag
plans/logs. Avoid hand-rolled binary metadata mutation until the read/plan/apply
contracts are stable and backed by fixtures from real-world files.

## Audio Listening Suggestions

Yes, wavwarden can eventually "listen" to files and suggest tags, but those
suggestions should never be applied automatically.

The similarity crawler should be the shared backend for this work. Sononym shows
why descriptor and similarity browsing are useful for sound libraries;
Soundminer-style crawlers show the safer implementation shape: precompute audio
analysis in a separate, resumable command, then let search, tag suggestions, and
future UI layers consume cached evidence.

Recommended design:

```bash
uv run sfx suggest PATH --from-audio --output suggestions.json
uv run sfx suggest PATH --from-filename --from-audio --merge --output tag_plan.json
uv run sfx similarity crawl PATH --db ~/.wavwarden/index.db --cache ~/.wavwarden/similarity
```

Store model outputs in SQLite with:

- file path plus size/mtime/hash key
- model/tool name and version
- analyzed duration/window
- labels, confidence, and evidence
- failure reason
- generated timestamp

Likely suggestion classes:

- content labels: rain, gunshot, whoosh, footsteps
- scene labels: interior, exterior, city, forest
- technical tags: mono/stereo, long/short, possible loop
- quality flags: silence, clipping, hum, low level, truncation

The first crawler-backed slice should prefer deterministic descriptors and
segment/event detection before ML labels. Embeddings can be added later as an
optional extra, keyed by model/backend version so old analysis can be identified
and rebuilt when needed.

CLAP-style audio-text embedding models are promising for zero-shot sound-effect
labels. AudioSet-style classifiers can provide broad sound-event categories.
Speech models such as Whisper are useful for speech detection/transcription, not
general SFX labeling.

Concrete candidates:

- PANNs inference: MIT licensed, useful for broad AudioSet-style sound-event
  suggestions.
- CLAP-style models: useful for text/audio similarity and label ranking, but
  model licensing and runtime footprint must be checked per model.
- aiSFX: relevant research direction for UCS-like sound-effect embeddings, but
  treat as experimental until maintenance, license, and model provenance are
  verified.

All audio-model features need explicit privacy and cost controls before use on
commercial libraries.

See [`SIMILARITY.md`](SIMILARITY.md) for the dedicated crawler roadmap.

## References

- BWF MetaEdit / FADGI help: https://www.digitizationguidelines.gov/audio-visual/documents/help_home.html
- BWF MetaEdit project: https://bwfmetaedit.sourceforge.net/
- EBU Tech 3285 Broadcast Wave Format: https://tech.ebu.ch/publications/tech3285
- Mutagen documentation: https://mutagen.readthedocs.io/
- CLAP paper: https://www.microsoft.com/en-us/research/publication/clap-learning-audio-concepts-from-natural-language-supervision/
- Microsoft CLAP implementation: https://github.com/microsoft/CLAP
- AudioSet ontology: https://github.com/audioset/ontology
