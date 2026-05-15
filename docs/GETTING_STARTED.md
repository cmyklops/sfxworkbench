# Getting Started

sfxworkbench is safest when you treat the first run as an inspection pass, not
a cleanup spree. Point it at a copied library, build the index, read the
reports, then apply only the changes you understand.

## The Short Version

```bash
sfx guide PATH
sfx tui
```

Use `sfx guide PATH` when you want command-line next steps. Use `sfx tui` when
you want the interactive workbench: paste or drag a copied library folder into
the Library field, press Enter, and start from the Start tab.

## First Run Checklist

1. Copy the library first.

   Do not use your only production copy for the first pass. A local disposable
   copy lets you validate reports, quarantines, apply logs, and undo behavior
   without risking the source collection.

2. Build the searchable index.

   In the TUI, run **Quick Index** from Start or Scan. In the CLI:

   ```bash
   sfx scan PATH --mode index
   ```

   This creates or refreshes the SQLite index used by search, audits, duplicate
   review, and metadata reports.

3. Run a full audit when you are ready for richer evidence.

   In the TUI, run **Full Audit**. In the CLI:

   ```bash
   sfx audit-bundle PATH --output-dir ~/reports/sfxworkbench_first_run
   ```

   The audit bundle writes read-only reports for scan health, filename issues,
   duplicates, metadata gaps, and related library risks.

4. Review before applying.

   Start with health and filename issues, then duplicates, then metadata. The
   normal pattern is preview or report, review the generated plan, then apply
   only after the plan looks right.

5. Keep the evidence.

   Reports, plans, action history, and apply logs are part of the safety model.
   They explain what happened and are often required for undo workflows.

## Good First CLI Session

Replace `PATH` with a copied library folder:

```bash
sfx guide PATH
sfx scan PATH --mode index
sfx audit-bundle PATH --output-dir ~/reports/sfxworkbench_first_run
sfx search "rain" --db ~/.sfxworkbench/index.db
sfx clean PATH
sfx dedupe --summary-only
```

The last two commands are previews or summaries. They do not remove or move
audio files.

## What Not To Do First

- Do not run apply commands against your only copy.
- Do not permanently delete from live library paths.
- Do not trust UCS-looking filenames as semantic truth without catalog/evidence
  review.
- Do not write embedded metadata until a write plan has been reviewed and, for
  important libraries, fixture-tested.

## Where Things Go

The default index is:

```text
~/.sfxworkbench/index.db
```

The TUI uses a report directory near the selected index or library when one is
available. You can be explicit:

```bash
sfx tui --db ~/.sfxworkbench/index.db --report ~/reports/sfxworkbench_first_run
```

Apply logs usually land in an `apply_logs/` folder beside the active report or
plan.
