.PHONY: test lint fmt-check cli json-smoke audit-fixture bench-scan

TEST_PATH ?= tests/
FIXTURE_PATH ?= tests/fixtures/library_basic
BENCH_PATH ?= $(HOME)/CommercialLibraries
BENCH_LIMIT ?= 1000

test:
	uv run --extra dev poe test

lint:
	uv run --extra dev poe lint

fmt-check:
	uv run --extra dev poe fmt-check

cli:
	uv run sfx --help

json-smoke:
	uv run --extra dev poe json-smoke

audit-fixture:
	python3 audit.py $(FIXTURE_PATH) --output-dir /tmp/sfxworkbench-audit-fixture --json

bench-scan:
	uv run --extra dev poe bench-scan --root /tmp/sfxworkbench-bench/library --files $(BENCH_LIMIT) --no-hash
