# Windows Support

Windows support is experimental. The core CLI should start, but the project treats Windows as trustworthy only after path-scoped DB workflows, portable rename safety, and CI smoke coverage have passed on Windows runners.

## Current CI Coverage

GitHub Actions runs a non-blocking `windows-latest` smoke job on Python 3.11:

```powershell
uv sync --extra dev
uv run poe test-windows-smoke
```

The smoke task covers path-scope helpers, filename health checks, related groups, pack audit scoping, tag suggestions, and UCS validation. It is intentionally narrow while Windows support is being hardened. Linux `poe check` remains the required full-suite signal.

## Known Exclusions

The Windows smoke job does not yet prove:

- TUI launch, reveal, command hints, or audio audition behavior.
- External metadata writer availability beyond backend discovery.
- Full destructive workflows on a real library.
- Shell-specific command snippets for PowerShell or CMD.

Run apply/undo workflows only against a disposable copy until the Windows smoke job is promoted from non-blocking to required.

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
