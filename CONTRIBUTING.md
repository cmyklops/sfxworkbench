# Contributing

sfxworkbench is currently an internal studio beta. External contributions are not
being actively accepted yet, but the repo is being prepared so that outside
collaboration can happen cleanly later.

Internal changes should:

- preserve dry-run, quarantine, or undo behavior for filesystem-changing workflows
- keep `audit.py` standalone and stdlib-only
- update tests for safety behavior and JSON contract changes
- run `uv run --extra dev poe check`
- avoid committing real audio libraries, generated reports, local DBs, or proprietary paths

Before public contributions are accepted, the project should choose an inbound
contribution policy such as Developer Certificate of Origin (DCO) or a
contributor license agreement.
