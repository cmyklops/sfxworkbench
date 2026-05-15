# Release Checklist

This checklist is for publishing a beta or v1 release that someone outside the
original development machine can install and use against a copied library.

## Preflight

1. Confirm the version in `pyproject.toml` and `sfxworkbench/__init__.py`.
2. Update `CHANGELOG.md` with the release date and milestone summary.
3. Review `README.md`, `SECURITY.md`, `SUPPORT.md`, and `docs/MIGRATIONS.md`.
4. Make sure no generated reports, local SQLite DBs, logs, or commercial audio
   paths are staged.

## Local Validation

Run from a clean checkout:

```bash
uv sync --extra dev
uv sync --extra metadata --extra dev
uv run sfx --help
uv run --extra dev poe check
uv build
```

Then install the built wheel in a temporary environment:

```bash
uv venv --python 3.11 /tmp/sfxworkbench-release-smoke
uv pip install --python /tmp/sfxworkbench-release-smoke/bin/python dist/sfxworkbench-*.whl
/tmp/sfxworkbench-release-smoke/bin/sfx --help
/tmp/sfxworkbench-release-smoke/bin/sfx scan tests/fixtures/library_basic --db /tmp/sfxworkbench-release-smoke/index.db --json
/tmp/sfxworkbench-release-smoke/bin/sfx audit --db /tmp/sfxworkbench-release-smoke/index.db --json
```

## Cross-Platform Validation

CI must pass on the claimed Python versions:

- Python 3.10
- Python 3.11
- metadata extra smoke tests

For a public release, run the same wheel install smoke test on macOS and Linux.
Linux must also pass the full local suite with `uv run --extra dev poe check`.
If either platform is not validated, say so in the release notes.

## Publishing

Attach both source distribution and wheel artifacts to the GitHub release:

```text
dist/sfxworkbench-<version>.tar.gz
dist/sfxworkbench-<version>-py3-none-any.whl
```

Do not publish to PyPI until the GitHub release wheel has passed the clean
install smoke test and the README install section matches the published package.
