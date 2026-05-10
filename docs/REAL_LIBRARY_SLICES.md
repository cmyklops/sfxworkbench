# Real Library Slices

Small copied slices let wavwarden prove risky workflows against real files
without touching the full copied library.

## BWF Missing-Metadata Slice

Created: 2026-05-09

Purpose: prove reviewed BWF MetaEdit `bext` writes on real WAV files that were
missing embedded BWF/iXML metadata.

Source library:

```text
/Users/mattwesdock/CommercialLibraries
```

Copied slice root:

```text
/private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_library
```

Slice DB:

```text
/private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_slice.db
```

Selection criteria:

```sql
SELECT path
FROM files
WHERE lower(extension) = '.wav'
  AND scan_error IS NULL
  AND COALESCE(has_bext, 0) = 0
ORDER BY path
LIMIT 4;
```

Files copied:

```text
1.Metal Fence, Alice Springs, AU 2015.wav
2.Unidentifed Chiroptera, Peron Homestead, AU 2014.wav
3.Cockatoos In Storm, Ravenswood Mine AU 2010.wav
4.Bushfire, Near Mt Isa, AU 2010.wav
```

Reviewed tags inserted into the slice DB only:

```text
field: description
value: file stem
source: real_library_bwf_slice
method: manual
confidence: 1.0
```

Artifacts:

```text
/private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_plan.json
/private/tmp/wavwarden_bwf_slice_20260509_113309/fixtures/metadata_write_fixture_manifest.json
/private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_apply_log_rerun.json
```

Verified workflow:

```bash
uv run sfx scan /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_library --db /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_slice.db --json
uv run sfx metadata write-plan /private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_plan.json --db /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_slice.db --path /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_library --bwfmetaedit /opt/homebrew/bin/bwfmetaedit --json
uv run sfx metadata write-review /private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_plan.json --approve-all --json
uv run sfx metadata write-preview /private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_plan.json --db /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_slice.db --require-reviewed --json
uv run sfx metadata write-fixtures /private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_plan.json /private/tmp/wavwarden_bwf_slice_20260509_113309/fixtures --db /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_slice.db --require-reviewed --write-fixture-metadata --json
uv run sfx metadata write-readback /private/tmp/wavwarden_bwf_slice_20260509_113309/fixtures --json
uv run sfx metadata write-apply /private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_plan.json --db /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_slice.db --require-reviewed --backup-dir /private/tmp/wavwarden_bwf_slice_20260509_113309/backups_rerun --log /private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_apply_log_rerun.json --apply --json
uv run sfx metadata write-undo /private/tmp/wavwarden_bwf_slice_20260509_113309/metadata_write_apply_log_rerun.json --db /private/tmp/wavwarden_bwf_slice_20260509_113309/missing_bext_slice.db --apply --json
```

Results:

- Fixture write: 4 files written, 0 errors.
- Fixture readback: 4 files checked, 4 matched, 0 mismatches.
- Original copied-slice apply: 4 files backed up, 4 written, 4 verified, 0
  errors.
- Post-apply metadata audit: 0 missing metadata rows after indexed metadata
  refresh.
- Undo: 4 files restored, 0 errors.
- Post-undo metadata audit: 4 missing metadata rows again, matching the original
  slice state.

Important finding:

- Real apply initially updated only size/mtime/MD5 in SQLite. The slice exposed
  that `has_bext` stayed stale after BWF writes. The apply/undo path now rereads
  audio metadata and refreshes indexed metadata flags after successful write or
  restore.
- An earlier candidate slice used files that already had BEXT/iXML metadata.
  Metadata write planning now reads existing BWF core fields and marks non-empty
  target fields as `skip_existing`, preserving vendor/human metadata until a
  future explicit replace mode exists.

## Existing BWF Collision Slice

Created: 2026-05-09

Purpose: prove that reviewed BWF write planning fills only missing fields and
does not overwrite existing embedded BWF values.

Copied slice root:

```text
/private/tmp/wavwarden_existing_bwf_slice_rF9UII/library
```

Slice DB:

```text
/private/tmp/wavwarden_existing_bwf_slice_rF9UII/slice.db
```

Files copied:

```text
RL_TU_Hi_Tension_Pulse_03.wav
RL_TU_Soundscape Hi freq tension layer.wav
RL_TU_Soundscape with tubulent wind and low cry.wav
```

Reviewed tags inserted into the slice DB only:

```text
field: description
value: Wavwarden proposed description for <file stem>

field: originator
value: Wavwarden QA

field: originator_reference
value: WW-0001, WW-0002, WW-0003
```

Artifacts:

```text
/private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan.json
/private/tmp/wavwarden_existing_bwf_slice_rF9UII/fixtures/metadata_write_fixture_manifest.json
```

Verified workflow:

```bash
uv run sfx scan /private/tmp/wavwarden_existing_bwf_slice_rF9UII/library --db /private/tmp/wavwarden_existing_bwf_slice_rF9UII/slice.db
uv run sfx metadata write-plan /private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan.json --db /private/tmp/wavwarden_existing_bwf_slice_rF9UII/slice.db --path /private/tmp/wavwarden_existing_bwf_slice_rF9UII/library --backend bwfmetaedit --bwfmetaedit /opt/homebrew/bin/bwfmetaedit --json
uv run sfx metadata write-review /private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan.json --approve-all --json
uv run sfx metadata write-preview /private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan.json --db /private/tmp/wavwarden_existing_bwf_slice_rF9UII/slice.db --require-reviewed --json
uv run sfx metadata write-fixtures /private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan.json /private/tmp/wavwarden_existing_bwf_slice_rF9UII/fixtures --db /private/tmp/wavwarden_existing_bwf_slice_rF9UII/slice.db --require-reviewed --write-fixture-metadata --json
uv run sfx metadata write-readback /private/tmp/wavwarden_existing_bwf_slice_rF9UII/fixtures --json
```

Results:

- Write plan considered 9 accepted tags across 3 copied real WAV files.
- 4 entries were marked `skip_existing`: all 3 populated `Description` fields
  plus the populated `Originator` field on `RL_TU_Hi_Tension_Pulse_03.wav`.
- Preview would write only 5 missing values: 3 `OriginatorReference` values and
  2 empty `Originator` values.
- Fixture readback checked 3 files, all matched, with 0 mismatches and 0
  errors.
- Existing descriptions stayed intact after fixture writes; only empty target
  fields were filled.

Replace-mode smoke:

```bash
uv run sfx metadata write-plan /private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan_replace.json --db /private/tmp/wavwarden_existing_bwf_slice_rF9UII/slice.db --path /private/tmp/wavwarden_existing_bwf_slice_rF9UII/library --backend bwfmetaedit --bwfmetaedit /opt/homebrew/bin/bwfmetaedit --replace-existing --json
uv run sfx metadata write-review /private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan_replace.json --approve-all --json
uv run sfx metadata write-preview /private/tmp/wavwarden_existing_bwf_slice_rF9UII/metadata_write_plan_replace.json --db /private/tmp/wavwarden_existing_bwf_slice_rF9UII/slice.db --require-reviewed --json
```

Replace-mode results:

- The same 9 accepted tags became 9 supported entries with 0 skips.
- The 4 values that were previously `skip_existing` became explicit
  `replace_bext` entries.
- Preview emitted 3 file-level BWF MetaEdit command groups with
  `allow_overwrite: true`.
- Replacement command groups omitted `--reject-overwrite`; the default
  add-missing plan still includes it.

## WAV RIFF INFO Keyword Slice

Created: 2026-05-10

Purpose: prove reviewed synonym/keyword metadata writes to real copied WAV files
using RIFF INFO `IKEY` via BWF MetaEdit.

Copied slice root:

```text
/private/tmp/wavwarden_ikey_slice_rwtgYd/library
```

Slice DB:

```text
/private/tmp/wavwarden_ikey_slice_rwtgYd/slice.db
```

Files copied:

```text
RL_TU_Hi_Tension_Pulse_03.wav
RL_TU_Soundscape Hi freq tension layer.wav
```

Reviewed tags inserted into the slice DB only:

```text
RL_TU_Hi_Tension_Pulse_03.wav:
  keyword: distortion
  keyword: hit
  keyword: impact
  keyword: tension pulse

RL_TU_Soundscape Hi freq tension layer.wav:
  keyword: ambience
  keyword: high frequency
  keyword: tension layer
  keyword: texture
```

Artifacts:

```text
/private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_plan.json
/private/tmp/wavwarden_ikey_slice_rwtgYd/fixtures/metadata_write_fixture_manifest.json
/private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_apply_log.json
```

Verified workflow:

```bash
uv run sfx scan /private/tmp/wavwarden_ikey_slice_rwtgYd/library --db /private/tmp/wavwarden_ikey_slice_rwtgYd/slice.db --json
uv run sfx metadata write-plan /private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_plan.json --db /private/tmp/wavwarden_ikey_slice_rwtgYd/slice.db --path /private/tmp/wavwarden_ikey_slice_rwtgYd/library --backend bwfmetaedit --bwfmetaedit /opt/homebrew/bin/bwfmetaedit --json
uv run sfx metadata write-review /private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_plan.json --approve-all --json
uv run sfx metadata write-preview /private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_plan.json --db /private/tmp/wavwarden_ikey_slice_rwtgYd/slice.db --require-reviewed --json
uv run sfx metadata write-fixtures /private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_plan.json /private/tmp/wavwarden_ikey_slice_rwtgYd/fixtures --db /private/tmp/wavwarden_ikey_slice_rwtgYd/slice.db --require-reviewed --write-fixture-metadata --json
uv run sfx metadata write-readback /private/tmp/wavwarden_ikey_slice_rwtgYd/fixtures --json
uv run sfx metadata write-apply /private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_plan.json --db /private/tmp/wavwarden_ikey_slice_rwtgYd/slice.db --require-reviewed --backup-dir /private/tmp/wavwarden_ikey_slice_rwtgYd/backups --log /private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_apply_log.json --apply --json
uv run sfx metadata write-undo /private/tmp/wavwarden_ikey_slice_rwtgYd/metadata_write_apply_log.json --db /private/tmp/wavwarden_ikey_slice_rwtgYd/slice.db --apply --json
```

Results:

- Write plan considered 8 accepted `keyword` tags across 2 copied real WAV
  files.
- Preview grouped those into 2 BWF MetaEdit `--IKEY=...` commands, one per file.
- Fixture write: 2 files written, 0 errors.
- Fixture readback: 2 files checked, 2 matched, 0 mismatches.
- Original copied-slice apply: 2 files backed up, 2 written, 2 verified, 0
  errors.
- Post-apply RIFF INFO readback showed:
  - `distortion; hit; impact; tension pulse`
  - `ambience; high frequency; tension layer; texture`
- Undo restored 2 files with 0 errors; post-undo RIFF INFO readback showed no
  `IKEY` values.

## Existing BWF Originator Fill Slice

Created: 2026-05-10

Purpose: prove reviewed BWF MetaEdit writes can fill missing BEXT
`Originator` and `OriginatorReference` values on real copied WAV files while
preserving populated BEXT `Description` values.

Copied slice root:

```text
/private/tmp/wavwarden_bwf_originator_slice_20260509_214926/library
```

Slice DB:

```text
/private/tmp/wavwarden_bwf_originator_slice_20260509_214926/slice.db
```

Files copied:

```text
AMB Edinburgh Napier University Cafeteria walla room tone D100.wav
AMB Edinburgh Napier University Computing Centre walla room tone D100.wav
AMB South Africa Afternoon savannah Limpopo province birds cicadas crickets insects D100.wav
AMB South Africa Dawn savannah Limpopo river birds frogs insects D100.wav
```

Selection criteria:

```sql
SELECT path
FROM files
WHERE path LIKE '/Users/mattwesdock/CommercialLibraries/2016 Holiday Freebies - MAFX/_Sounds/%'
  AND lower(extension) = '.wav'
  AND scan_error IS NULL
  AND COALESCE(has_bext, 0) = 1
ORDER BY path
LIMIT 4;
```

Reviewed tags inserted into the slice DB only:

```text
field: description
value: Wavwarden proposed description for <file stem>

field: originator
value: Wavwarden QA

field: originator_reference
value: WW-MAFX-ORIG-0001 through WW-MAFX-ORIG-0004
```

Artifacts:

```text
/private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_plan.json
/private/tmp/wavwarden_bwf_originator_slice_20260509_214926/fixtures/metadata_write_fixture_manifest.json
/private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_apply_log.json
```

Verified workflow:

```bash
uv run sfx scan /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/library --db /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/slice.db --json
uv run sfx metadata write-plan /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_plan.json --db /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/slice.db --path /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/library --backend bwfmetaedit --bwfmetaedit /opt/homebrew/bin/bwfmetaedit --json
uv run sfx metadata write-review /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_plan.json --approve-all --json
uv run sfx metadata write-preview /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_plan.json --db /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/slice.db --require-reviewed --json
uv run sfx metadata write-fixtures /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_plan.json /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/fixtures --db /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/slice.db --require-reviewed --write-fixture-metadata --json
uv run sfx metadata write-readback /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/fixtures --json
uv run sfx metadata write-apply /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_plan.json --db /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/slice.db --require-reviewed --backup-dir /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/backups --log /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_apply_log.json --apply --json
uv run sfx metadata write-undo /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/metadata_write_apply_log.json --db /private/tmp/wavwarden_bwf_originator_slice_20260509_214926/slice.db --apply --json
```

Results:

- Write plan considered 12 accepted tags across 4 copied real WAV files.
- 4 proposed descriptions were marked `skip_existing`, preserving populated
  vendor BEXT descriptions.
- Preview grouped 8 missing values into 4 BWF MetaEdit commands with
  `--reject-overwrite`.
- Fixture write: 4 files written, 0 errors.
- Fixture readback: 4 files checked, 4 matched, 0 mismatches.
- Original copied-slice apply: 4 files backed up, 4 written, 4 verified, 0
  errors.
- Post-apply readback showed original descriptions unchanged, `Originator` set
  to `Wavwarden QA`, and unique `OriginatorReference` values.
- Undo restored 4 files with 0 errors; post-undo readback showed original
  descriptions intact and empty originator fields again.
