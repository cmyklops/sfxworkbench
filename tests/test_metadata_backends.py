"""Tests for report-only metadata writer backend discovery."""

from __future__ import annotations

import subprocess

from sfxworkbench import metadata_backends
from sfxworkbench.metadata_backends import build_metadata_backends_report


def test_metadata_backends_reports_missing_bwfmetaedit(monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.shutil, "which", lambda _name: None)
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: None)

    report = build_metadata_backends_report()

    backend = report.backends[0]
    mutagen = report.backends[1]
    assert report.recommended_backend == "auto"
    assert backend.name == "bwfmetaedit"
    assert backend.available is False
    assert backend.executable is None
    assert backend.error == "not found on PATH"
    assert ".wav" in backend.supported_extensions
    assert mutagen.name == "mutagen"
    assert mutagen.available is False
    assert ".mp3" in mutagen.supported_extensions


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


def test_metadata_backends_reports_available_mutagen(monkeypatch) -> None:
    monkeypatch.setattr(metadata_backends.shutil, "which", lambda _name: None)
    monkeypatch.setattr(metadata_backends.importlib_util, "find_spec", lambda _name: object())
    monkeypatch.setattr(metadata_backends.importlib_metadata, "version", lambda _name: "1.47.0")

    report = build_metadata_backends_report()

    backend = report.backends[1]
    assert backend.name == "mutagen"
    assert backend.available is True
    assert backend.version == "1.47.0"
    assert ".flac" in backend.supported_extensions


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
