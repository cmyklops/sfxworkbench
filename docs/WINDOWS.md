# Windows Support

Windows support is experimental. The core CLI should start, but the project treats Windows as trustworthy only after path-scoped DB workflows, portable rename safety, and CI smoke coverage have passed on Windows runners.

## Current CI Coverage

GitHub Actions runs a non-blocking `windows-latest` smoke job on Python 3.11:

```powershell
uv sync --extra dev
uv run poe test-windows-smoke
```

The smoke task covers path-scope helpers, the artifact/job registry, filename health checks, related groups, pack audit scoping, tag suggestions, and UCS validation. It is intentionally narrow while Windows support is being hardened. Linux `poe check` remains the required full-suite signal.

## Known Exclusions

The Windows smoke job does not yet prove:

- TUI launch, reveal, command hints, or audio audition behavior.
- External metadata writer availability beyond backend discovery.
- Full destructive workflows on a real library.
- Shell-specific command snippets for PowerShell or CMD.

Run apply/undo workflows only against a disposable copy until the Windows smoke job is promoted from non-blocking to required.

## Local TUI Test Handoff

Use Windows Terminal or PowerShell against a disposable copy of a sound library. Do not point first-run testing at a production library.

For the simplest setup, open normal PowerShell, not as Administrator, and paste only this line. Do not add `powershell` before it:

```powershell
irm https://raw.githubusercontent.com/cmyklops/sfxworkbench/main/scripts/install-windows-tui.ps1 | iex
```

The script installs missing prerequisites, clones or updates the repo in your user folder, installs dependencies, and launches the TUI.

For macOS Terminal, use the companion installer instead:

```bash
curl -fsSL https://raw.githubusercontent.com/cmyklops/sfxworkbench/main/scripts/install-macos-tui.sh | bash
```

Manual fallback:

Install the command-line prerequisites first. If either installer says it changed `PATH`, close every PowerShell tab and open a new one before continuing.

```powershell
winget install --id Git.Git --exact --source winget
winget install --id astral-sh.uv --exact --source winget
```

In the new PowerShell session, verify both commands are visible. Start from your user folder, not `C:\WINDOWS\system32`:

```powershell
Set-Location $HOME
git --version
uv --version
```

If either command is still not found, restart PowerShell again. Do not run the clone/install block until both commands work.

Clone the repo and install the optional TUI dependencies:

```powershell
Set-Location $HOME
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is not available. Restart PowerShell, then run git --version." }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is not available. Restart PowerShell, then run uv --version." }
if (Test-Path .\sfxworkbench) {
    Set-Location .\sfxworkbench
    git pull
} else {
    git clone https://github.com/cmyklops/sfxworkbench.git
    Set-Location .\sfxworkbench
}
uv python install 3.11
uv sync --python 3.11 --extra dev --extra metadata --extra tui
```

Launch the TUI:

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\sfx.exe tui --db .\win_test.db --report .\reports
```

Inside the TUI:

- Set the library path to the disposable test library.
- Run `Scan Library` first. The first scan can be slow on Windows because it reads audio metadata and hashes files; later scans skip unchanged files by `mtime + size`.
- Exercise the feature tabs: Scan, Cleanup, Dedupe, Metadata, Files, and History.
- For cleanup/dedupe/delete/metadata-write actions, use preview/review steps first and keep the test library disposable.
- In Metadata, the simplified flow is `Find Tags`, `Review Tags`, `Accept Tags & Prepare Write`, then `Write Metadata to Files`.

Useful output paths:

- `.\reports\action_history\*.json` - completed TUI action summaries.
- `.\reports\apply_logs\*.json` - apply/undo logs when an action writes one.
- `.\reports\metadata_tag_plan.json` - current generated tag-review plan.
- `.\reports\metadata_write_plan.json` - current embedded metadata write plan.

The TUI creates a DB-specific lock such as `win_test.db.tui.lock` so two instances do not open the same SQLite index. If launch reports another TUI is already running, close the existing TUI. Remove the lock file only after confirming no `sfx.exe tui` process is still running.

For a quick non-interactive signal:

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_tui_app.py tests/test_tui_data.py tests/test_tui_command_palette_pilot.py -q --basetemp C:\tmp\sfxworkbench-pytest
uv run poe test-windows-smoke
```

When reporting feedback, include:

- Windows version and terminal app.
- The exact TUI action that was running.
- Any screenshot of the TUI state.
- Relevant files from `.\reports\action_history`.
- Whether the issue happened on a first scan or a repeated scan.

## Local PowerShell Smoke

Use a small copied test library, not a production library:

```powershell
uv sync --extra dev --extra metadata --extra tui
uv run poe test-windows-smoke
uv run sfx --help
uv run sfx scan .\test_library --db .\win_test.db --force --json
uv run sfx audit --db .\win_test.db --json
uv run sfx rename .\test_library --pattern portable --db .\win_test.db --json
uv run sfx dedupe --db .\win_test.db --summary-only --json
uv run sfx tag suggest .\test_library --db .\win_test.db --limit 50 --json
uv run sfx metadata backends --json
```

For apply/undo validation, stay on a disposable copy:

```powershell
uv run sfx rename .\test_library --pattern portable --db .\win_test.db --apply --log .\rename_log.json
uv run sfx rename --undo .\rename_log.json --db .\win_test.db --apply
```
