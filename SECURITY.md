# Security And Privacy Policy

sfxworkbench is in public-readiness beta and does not currently promise fixed
security response times. It is designed to run locally against local files.

Please report security issues privately to the maintainers. Do not open public
issues containing:

- real commercial library paths
- customer or client names
- proprietary filenames
- sample audio content
- production SQLite databases or generated reports

When reporting a problem, include the command run, operating system, Python
version, whether `--json` was used, and redacted output.

## Commercial Audio Privacy

sfxworkbench does not need network access for normal CLI operation. Scans,
reports, metadata plans, similarity descriptors, and review feedback are stored
locally in SQLite or JSON files that may contain proprietary filenames, folder
paths, metadata values, and review decisions. Treat those files as confidential
studio data.

Do not upload generated reports, SQLite databases, cache files, or logs unless
they have been reviewed and redacted.

## Optional Analysis

The deterministic similarity backend is local and does not send audio anywhere.
Future ML or fingerprint backends must document model provenance, licensing,
runtime behavior, privacy implications, and storage format before becoming a
recommended workflow.
