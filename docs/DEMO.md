# Demo Library

The repository includes a tiny synthetic fixture at
`tests/fixtures/library_basic`. It is safe to use for smoke tests because it
does not contain commercial audio.

The fixture intentionally includes:

- audio-extension files for scan/audit smoke tests
- junk files such as AppleDouble and waveform-cache artifacts
- risky filename cases for health checks

Run a quick report-only demo:

```bash
uv run sfx scan tests/fixtures/library_basic --db /tmp/sfxworkbench_demo.db --json
uv run sfx audit --db /tmp/sfxworkbench_demo.db --json
uv run sfx search rain --db /tmp/sfxworkbench_demo.db --json
uv run sfx clean tests/fixtures/library_basic
```

Do not run `clean --apply` against the committed fixture in the repository.
Copy it first when testing apply behavior:

```bash
cp -R tests/fixtures/library_basic /tmp/sfxworkbench_demo_library
uv run sfx clean /tmp/sfxworkbench_demo_library --apply
```

The UI direction screenshot in `docs/assets/app-ui-direction-mockup.png` is a
product mockup, not a screenshot of a shipped review/apply UI.
