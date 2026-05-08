"""Tests for report-only metadata writer backend discovery."""

from __future__ import annotations

import subprocess

from wavwarden import metadata_backends
from wavwarden.metadata_backends import build_metadata_backends_report


def test_metadata_backends_reports_missing_bwfmetaedit(monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.shutil, "which", lambda _name: None)

    report = build_metadata_backends_report()

    backend = report.backends[0]
    assert backend.name == "bwfmetaedit"
    assert backend.available is False
    assert backend.executable is None
    assert backend.error == "not found on PATH"
    assert ".wav" in backend.supported_extensions


def test_metadata_backends_captures_bwfmetaedit_version(monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.shutil, "which", lambda name: "/usr/local/bin/bwfmetaedit")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="BWF MetaEdit 24.04\n", stderr="")

    report = build_metadata_backends_report(run=fake_run)

    backend = report.backends[0]
    assert backend.available is True
    assert backend.executable == "/usr/local/bin/bwfmetaedit"
    assert backend.version == "BWF MetaEdit 24.04"
    assert backend.version_command == ["/usr/local/bin/bwfmetaedit", "--Version"]
    assert backend.writes_bext is True
    assert backend.writes_ixml is False
    assert calls == [["/usr/local/bin/bwfmetaedit", "--Version"]]


def test_metadata_backends_uses_explicit_executable(tmp_path) -> None:
    executable = tmp_path / "bwfmetaedit"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="explicit version\n", stderr="")

    report = build_metadata_backends_report(bwfmetaedit=executable, run=fake_run)

    backend = report.backends[0]
    assert backend.available is True
    assert backend.executable == str(executable)
    assert backend.version == "explicit version"
