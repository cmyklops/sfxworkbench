# Metadata Tagging Plan

Tagging should follow wavwarden's existing safety model:

`scan` observes files -> `audit` reports gaps -> `tag propose` fuses evidence
into candidate UCS tags -> reviewed plans validate and write DB-only accepted
tags -> export confirms results.

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
auto-tags from filename/path/metadata evidence, UCS provenance tags, aliases, and
synonym matches. Search and audit views should also be able to show only the
metadata fields that are actually present in a selected library, so sparse
metadata does not create unusable empty tables.

## Product Direction: Evidence Before Tags

The end goal is complete, portable metadata for files that lack it, while
respecting existing filenames and embedded/vendor metadata. UCS is the target
vocabulary for portable tagging, but UCS-looking filenames are not enough to
assign semantic UCS tags. A stem like `FIRE_BURST_SmallBurst` could describe
literal fire, firearm bursts, a magical spell, or a designed whoosh depending on
folder path, library/source context, embedded description, and the audio itself.

wavwarden should therefore separate:

- **Intrinsic file facts**: sample rate, bit depth, channels, duration, hashes,
  and format flags. These remain indexed/displayed facts, not user-facing tags.
- **Provenance**: filename/catalog claims such as `ucs_category` and
  `ucs_subcategory`. These are useful audit/search evidence but are not semantic
  truth.
- **Candidate semantic tags**: proposed UCS category/subcategory assignments
  based on corroborated evidence.
- **Accepted tags**: reviewed DB-only metadata that can later be exported to
  sidecars or safely embedded into WAVs.

The product should be bold about surfacing source material across the whole
library, not limited to folder-by-folder hunt-and-peck. Grouping files with
overlapping candidate UCS tags across different vendors/libraries is a feature:
the point is to make all useful source material findable by a meaningful search.
But those tags should come from evidence fusion, not from one filename heuristic.

First-class semantic evidence sources:

- existing embedded metadata, when readable
- folder/library/vendor/product path context
- filename tokens, treated as weak evidence
- UCS provenance fields, treated as weak evidence
- related-file/group context, treated as structural evidence
- deterministic audio descriptors and later audio-listening models
- similarity to already-reviewed/accepted material

Candidate proposals should be classified as:

- `strong`: multiple corroborating sources, suitable for batch review
- `review`: plausible but ambiguous
- `weak`: observed evidence only, held by default
- `blocked`: conflicts with existing human/vendor metadata

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

## Phase B: Evidence And Candidate Proposals

Current legacy suggestor:

- `sfx tag suggest` emits raw filename/path/group/UCS-provenance suggestions.
- It remains useful as an evidence source and debugging view.
- It is not the primary semantic tagging path.

The forward path is `sfx tag propose`, a report-only evidence-fusion command
that proposes candidate UCS tags from multiple sources. It should not mutate
SQLite or audio files.

Current proposal matching is intentionally conservative: exact UCS catalog pairs
and primary subcategory terms can open candidates; category terms only
corroborate. Synonyms and broader filename heuristics should be added back as
lower-trust layers only after real-library review proves they help.

Evidence can come from:

- parent folders
- existing embedded metadata, currently WAV/RF64 BEXT `Description` and RIFF
  INFO `IKEY`
- filename tokens
- UCS provenance from catalog matches
- related groups
- deterministic audio descriptors
- optional user dictionaries
- user-defined aliases and synonyms

Proposals should be data, not writes:

```json
{
  "category": "FIRE",
  "subcategory": "BURNING",
  "cat_id": "FIREBurn",
  "strength": "strong",
  "confidence": 0.82,
  "evidence": [
    {"source": "path", "value": "fire", "detail": "folder context"},
    {"source": "filename", "value": "burning", "detail": "filename token"}
  ]
}
```

UCS-derived category fields are provenance, not final semantic labels. For
example, a filename stem such as `FIRE_BURST` may indicate a UCS catalog match,
but the sound could still be literal fire, a gun burst, or a magic spell
depending on path, group, metadata, and audio context. The suggestor therefore
emits `ucs_category` and `ucs_subcategory` for UCS filename/catalog evidence.
Future semantic `category`/`subcategory` tags should require corroborating
evidence from multiple sources or explicit review.

## Phase C: Reviewed Tag Plans

Current first implementation:

```bash
uv run sfx tag propose PATH --db ~/.wavwarden/index.db --min-confidence 0.6 --output tag_proposals.json
uv run sfx tag suggest PATH --db ~/.wavwarden/index.db --use-ucs-catalog --min-confidence 0.8 --source ucs_catalog --field ucs_category --field ucs_subcategory --output tag_suggestions.json
uv run sfx tag suggest PATH --db ~/.wavwarden/index.db --include-synonyms --field keyword --output synonym_keywords.json
uv run sfx tag plan PATH --db ~/.wavwarden/index.db --from-suggestions tag_suggestions.json --source ucs_catalog --field ucs_category --field ucs_subcategory --output tag_plan.json
uv run sfx tag plan PATH --db ~/.wavwarden/index.db --include-synonyms --source synonym --field keyword --output synonym_keyword_plan.json
uv run sfx tag summarize tag_plan.json --value-limit 20
uv run sfx tag review tag_plan.json --approve-field ucs_category --only-status pending
uv run sfx tag review tag_plan.json --approve-all
uv run sfx tag apply tag_plan.json --db ~/.wavwarden/index.db --require-reviewed --apply --log tag_apply_log.json
uv run sfx tag sidecar-export accepted_tags.sidecar.json --db ~/.wavwarden/index.db --path PATH
uv run sfx tag sidecar-import accepted_tags.sidecar.json --db ~/.wavwarden/index.db
uv run sfx metadata view QUERY --db ~/.wavwarden/index.db
uv run sfx metadata backends --json
uv run sfx metadata write-plan metadata_write_plan.json --db ~/.wavwarden/index.db --path PATH --bwfmetaedit /path/to/bwfmetaedit
uv run sfx metadata write-plan metadata_write_plan.json --db ~/.wavwarden/index.db --path PATH --bwfmetaedit /path/to/bwfmetaedit --replace-existing
uv run sfx metadata write-review metadata_write_plan.json --approve-all
uv run sfx metadata write-preview metadata_write_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx metadata write-fixtures metadata_write_plan.json metadata_fixtures --db ~/.wavwarden/index.db
uv run sfx metadata write-fixtures metadata_write_plan.json metadata_fixtures --db ~/.wavwarden/index.db --write-fixture-metadata
uv run sfx metadata write-readback metadata_fixtures --json
uv run sfx metadata write-apply metadata_write_plan.json --db ~/.wavwarden/index.db          # dry-run
uv run sfx metadata write-apply metadata_write_plan.json --db ~/.wavwarden/index.db --apply  # reviewed BWF/Mutagen writes
uv run sfx metadata write-undo metadata_write_apply_log.json --db ~/.wavwarden/index.db      # dry-run
uv run sfx metadata write-undo metadata_write_apply_log.json --db ~/.wavwarden/index.db --apply
```

Each plan entry should include validation anchors:

- path
- file id when indexed
- size and mtime
- MD5 when available
- target metadata fields
- action per field: `write_bext`/`write_tag`, `skip_existing`, or explicit
  `replace_bext`
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

The initial tag implementation is DB-only: approved entries are written to
`accepted_tags`, and apply writes `tag_apply_log` rows plus an external JSON log.
Accepted tags can also be exported and re-imported as JSON sidecars. Embedded
metadata writing now has narrow original-file mutation paths for reviewed
Mutagen-backed formats and BWF MetaEdit-backed WAV/RF64 `bext` plus RIFF INFO
keyword fields.

Batch review should start with `sfx tag summarize`, then approve or reject
narrow selectors such as `--approve-field ucs_category`, `--reject-value FIRE`,
or `--approve-source group --only-status pending`. Selector review is meant to
make large plans manageable without opening JSON by hand.

Synonym suggestions are metadata enrichment suggestions, not search-only query
expansion. `tag suggest --include-synonyms` derives conservative `keyword`
suggestions from existing filename/path/group/UCS evidence, using source
`synonym` and method `controlled_synonym_map`. Reviewed synonym keywords can be
approved into `accepted_tags` like any other DB-only tag. During embedded
metadata writes, supported tagged formats can carry those approved `keyword`
values through the existing Mutagen-backed `keywords` target. WAV/RF64 writes
carry approved keywords through RIFF INFO `IKEY` via BWF MetaEdit. Multiple
approved keyword values stay structured in wavwarden plans and readback reports;
for RIFF INFO they are rendered as a semicolon-separated `IKEY` value because
that container field is text-based.

## Phase D: Metadata Writes

Start with DB-only accepted tags and portable export. This first slice is
implemented: `sfx export` includes an `accepted_tags` JSON column, and
`sfx tag sidecar-export/import` round-trips accepted tags through a validated
JSON sidecar. `sfx metadata write-plan/review/preview` builds an embedded write
plan from accepted tags and validates anchors. `write-fixtures` can exercise
supported Mutagen and BWF MetaEdit writes against copied fixture files, and
`write-apply` can write reviewed Mutagen-backed original files plus BWF
MetaEdit-backed WAV/RF64 `bext` fields with backups and readback verification.
W64 remains sidecar-first.

Preferred write ladder:

1. DB-only accepted tags
2. sidecar JSON export/import, then XML only if another tool needs it
3. reviewed dry-run embedded-write plans
4. BWF/iXML writes for proven-safe WAV-family formats and native tag writes for
   standard tagged formats
5. optional overwrite mode with original-file backup/quarantine

BWF MetaEdit is the leading candidate for Broadcast WAV metadata because it is
designed for importing, editing, embedding, and exporting BWF metadata. The BWF
format itself is specified by EBU Tech 3285. Mutagen is the planned backend for
standard tagged formats outside the BWF/WAV family: AIFF, MP3, FLAC, Ogg/Vorbis,
Opus, and M4A. W64 remains sidecar-first until a reliable embedded-write backend
is proven with fixtures.

Use BWF MetaEdit as the professional reference behavior first. If wavwarden
wraps it, treat it as an external command with explicit version capture in tag
plans/logs. Avoid hand-rolled binary metadata mutation until the read/plan/apply
contracts are stable and backed by fixtures from real-world files.

Current embedded-write preflight:

```bash
uv run sfx metadata backends --json
uv run sfx metadata backends --bwfmetaedit /path/to/bwfmetaedit --json
```

This command only probes writer availability and version. It does not read or
modify audio files. Future embedded-write plans should copy the discovered
backend executable and version into plan/log records before any write is allowed.

Current embedded-write preview:

```bash
uv run sfx metadata write-plan metadata_write_plan.json --db ~/.wavwarden/index.db --path PATH --bwfmetaedit /path/to/bwfmetaedit
uv run sfx metadata write-review metadata_write_plan.json --approve-all
uv run sfx metadata write-preview metadata_write_plan.json --db ~/.wavwarden/index.db --require-reviewed
uv run sfx metadata write-fixtures metadata_write_plan.json metadata_fixtures --db ~/.wavwarden/index.db
uv run sfx metadata write-fixtures metadata_write_plan.json metadata_fixtures --db ~/.wavwarden/index.db --write-fixture-metadata
uv run sfx metadata write-readback metadata_fixtures --json
uv run sfx metadata write-apply metadata_write_plan.json --db ~/.wavwarden/index.db          # dry-run
uv run sfx metadata write-apply metadata_write_plan.json --db ~/.wavwarden/index.db --apply  # reviewed BWF/Mutagen writes
uv run sfx metadata write-undo metadata_write_apply_log.json --db ~/.wavwarden/index.db      # dry-run
uv run sfx metadata write-undo metadata_write_apply_log.json --db ~/.wavwarden/index.db --apply
```

The first BWF mapping is deliberately narrow: accepted `description`,
`originator`, and `originator_reference` tags can target BWF `bext` fields via
BWF MetaEdit. The `auto` planner also routes `.aif`, `.aiff`, `.mp3`, `.flac`,
`.ogg`, `.opus`, and `.m4a` entries to planned Mutagen tag writes for common
fields such as `description`, `category`, UCS provenance fields, take number,
and channel position. Fields that do not map cleanly remain visible in the plan
as `unsupported_field` or `unsupported_extension` instead of being silently
dropped. Preview renders simulated BWF MetaEdit commands and internal Mutagen
write intents; these commands are for validation and review only, not for
execution by wavwarden.

`write-fixtures` copies only the files that survived preview validation into an
output bundle, rewrites the simulated commands to those copied files, and writes
`metadata_write_fixture_manifest.json` with expected fields. With
`--write-fixture-metadata`, wavwarden can apply supported Mutagen writes and BWF
MetaEdit commands to the copied fixture files only. The fixture manifest records
the executable command result for BWF MetaEdit. Original library audio is not
modified.
`write-readback` compares copied fixture WAV BEXT/RIFF INFO fields or
Mutagen-readable text tags against the manifest and reports
matched/mismatched/error files.

`write-apply` is the first original-file mutation path and remains narrow:
it applies reviewed Mutagen-backed entries and BWF MetaEdit-backed WAV/RF64
`bext` plus RIFF INFO `IKEY` entries only, defaults to dry-run, requires
`--apply` to touch originals, writes full-file backups before mutation, records
an apply log, verifies fields by reading them back after write, and refreshes the indexed file
size/mtime/MD5 after successful verified writes. W64 and unsupported fields stay
DB-only/sidecar-only.

For BWF `bext` fields, write planning reads the existing core BEXT values first.
If the target field already has a non-empty embedded value, the plan marks that
entry as `skip_existing` and records the current value. This keeps wavwarden in
add-missing-metadata mode by default. `write-plan --replace-existing` is the
explicit escape hatch: it converts those would-be skips into reviewed
`replace_bext` entries and generated BWF MetaEdit commands omit
`--reject-overwrite` only for command groups that include an approved
replacement.

Write planning also blocks conflicting accepted tags before embedded writes are
rendered. If more than one accepted value targets the same single-value
embedded field on the same file, the affected entries are marked `conflict`,
counted in the plan summary, reported in plan/preview errors, and omitted from
fixture/apply commands. Multi-value fields such as RIFF INFO `IKEY` and Mutagen
`keywords` remain allowed to collect multiple accepted values.

`write-undo` restores originals from a `write-apply` log's backup list and
refreshes indexed size/mtime/MD5 after restore. It also defaults to dry-run and
requires `--apply` before copying backup files over originals.

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
uv run sfx similarity crawl PATH --db ~/.wavwarden/index.db --cache ~/.wavwarden/similarity
uv run sfx tag propose PATH --db ~/.wavwarden/index.db --min-confidence 0.6 --output tag_proposals.json
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
