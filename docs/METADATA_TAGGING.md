# Metadata Tagging Plan

Tagging should follow wavwarden's existing safety model:

`scan` observes files -> `audit` reports gaps -> `tag/suggest` creates reviewed
plans -> `tag --apply` validates and writes metadata -> `scan --force` confirms
results.

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
- `tag_apply_log`: immutable write attempts and outcomes

Keep `files.has_bext` and `files.has_ixml` as fast audit booleans.

## Phase B: Filename and UCS Suggestions

Add a pure parser module, separate from `rename.py`, that suggests metadata from:

- UCS-like filename stems
- parent folders
- common take/version suffixes
- known abbreviations such as `AMB`, `SFX`, and `FOLEY`
- optional user dictionaries

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
- source, confidence, and evidence

Apply should refuse or warn when files changed after the plan was created.

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

Recommended design:

```bash
uv run sfx suggest PATH --from-audio --output suggestions.json
uv run sfx suggest PATH --from-filename --from-audio --merge --output tag_plan.json
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

## References

- BWF MetaEdit / FADGI help: https://www.digitizationguidelines.gov/audio-visual/documents/help_home.html
- BWF MetaEdit project: https://bwfmetaedit.sourceforge.net/
- EBU Tech 3285 Broadcast Wave Format: https://tech.ebu.ch/publications/tech3285
- Mutagen documentation: https://mutagen.readthedocs.io/
- CLAP paper: https://www.microsoft.com/en-us/research/publication/clap-learning-audio-concepts-from-natural-language-supervision/
- Microsoft CLAP implementation: https://github.com/microsoft/CLAP
- AudioSet ontology: https://github.com/audioset/ontology
