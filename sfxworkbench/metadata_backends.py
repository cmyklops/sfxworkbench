"""Report-only discovery for future embedded metadata write backends."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from importlib import util as importlib_util
from pathlib import Path

from rich.console import Console
from rich.table import Table

from sfxworkbench import __version__
from sfxworkbench.models import MetadataWriteBackend, MetadataWriteBackendsReport

console = Console()

BWF_METAEDIT_NAMES = ("bwfmetaedit", "BWFMetaEdit")
BWF_METAEDIT_VERSION_FLAGS = ("--Version", "--version", "-v")
BWF_METAEDIT_EXTENSIONS = [".wav", ".rf64"]
MUTAGEN_EXTENSIONS = [".aif", ".aiff", ".mp3", ".flac", ".ogg", ".opus", ".m4a"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_path_separator(value: str) -> bool:
    return "/" in value or "\\" in value


def _resolve_executable(candidates: Sequence[str]) -> str | None:
    for candidate in candidates:
        if _has_path_separator(candidate):
            path = Path(candidate).expanduser()
            if path.exists() and path.is_file():
                return str(path)
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _first_output_line(stdout: str | None, stderr: str | None) -> str | None:
    output = (stdout or "").strip() or (stderr or "").strip()
    if not output:
        return None
    return output.splitlines()[0].strip()


def _probe_version(
    executable: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str | None, list[str], str | None]:
    errors: list[str] = []
    for flag in BWF_METAEDIT_VERSION_FLAGS:
        command = [executable, flag]
        try:
            result = run(command, capture_output=True, text=True, timeout=5, check=False)
        except FileNotFoundError:
            return None, command, "executable disappeared before version probe"
        except subprocess.TimeoutExpired:
            errors.append(f"{flag}: timed out")
            continue
        except Exception as e:
            errors.append(f"{flag}: {e}")
            continue
        line = _first_output_line(result.stdout, result.stderr)
        if result.returncode == 0 and line:
            return line, command, None
        detail = line or f"exit {result.returncode}"
        errors.append(f"{flag}: {detail}")
    return None, [executable, BWF_METAEDIT_VERSION_FLAGS[0]], "; ".join(errors) or "version probe returned no output"


def probe_bwfmetaedit(
    executable: str | Path | None = None,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> MetadataWriteBackend:
    """Discover BWF MetaEdit without performing any metadata writes."""
    candidates = [str(executable)] if executable is not None else list(BWF_METAEDIT_NAMES)
    resolved = _resolve_executable(candidates)
    if resolved is None:
        return MetadataWriteBackend(
            name="bwfmetaedit",
            display_name="BWF MetaEdit",
            available=False,
            error="not found on PATH" if executable is None else f"executable not found: {executable}",
            supported_extensions=BWF_METAEDIT_EXTENSIONS,
            writes_bext=True,
            writes_ixml=False,
            notes=[
                "Preferred external reference for Broadcast WAV metadata writes.",
                "Supports reviewed WAV/RF64 BEXT and RIFF INFO keyword write workflows.",
            ],
        )

    version, version_command, error = _probe_version(resolved, run=run)
    return MetadataWriteBackend(
        name="bwfmetaedit",
        display_name="BWF MetaEdit",
        available=True,
        executable=resolved,
        version=version,
        version_command=version_command,
        error=error,
        supported_extensions=BWF_METAEDIT_EXTENSIONS,
        writes_bext=True,
        writes_ixml=False,
        notes=[
            "Reference backend for reviewed WAV/RF64 BEXT and RIFF INFO keyword writes.",
            "Capture executable and version in metadata write plans and logs.",
        ],
    )


def probe_mutagen() -> MetadataWriteBackend:
    """Discover the optional Mutagen library without importing it."""
    if importlib_util.find_spec("mutagen") is None:
        return MetadataWriteBackend(
            name="mutagen",
            display_name="Mutagen",
            available=False,
            error="python package not installed; install sfxworkbench[metadata]",
            supported_extensions=MUTAGEN_EXTENSIONS,
            notes=[
                "Planned backend for tagged standard formats outside the BWF/WAV family.",
                "Used for reviewed dry-run plans before any embedded mutation is enabled.",
            ],
        )
    try:
        version = importlib_metadata.version("mutagen")
    except importlib_metadata.PackageNotFoundError:
        version = None
    return MetadataWriteBackend(
        name="mutagen",
        display_name="Mutagen",
        available=True,
        version=version,
        supported_extensions=MUTAGEN_EXTENSIONS,
        notes=[
            "Planned backend for MP3, FLAC, Ogg/Vorbis, Opus, M4A, and AIFF-style tags.",
            "Writes are still held behind sfxworkbench's reviewed dry-run workflow.",
        ],
    )


def build_metadata_backends_report(
    *,
    bwfmetaedit: str | Path | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> MetadataWriteBackendsReport:
    """Build a report of installed metadata writer backends."""
    return MetadataWriteBackendsReport(
        generated_at=_now_iso(),
        tool_version=__version__,
        backends=[probe_bwfmetaedit(bwfmetaedit, run=run), probe_mutagen()],
    )


def show_metadata_backends_report(report: MetadataWriteBackendsReport) -> None:
    table = Table(title="Metadata write backends", show_lines=False)
    table.add_column("Backend")
    table.add_column("Available", justify="right")
    table.add_column("Executable")
    table.add_column("Version")
    table.add_column("Writes")
    for backend in report.backends:
        writes = []
        if backend.writes_bext:
            writes.append("bext")
        if backend.writes_ixml:
            writes.append("iXML")
        table.add_row(
            backend.display_name,
            "yes" if backend.available else "no",
            backend.executable or "-",
            backend.version or backend.error or "-",
            ", ".join(writes) or "-",
        )
    console.print(table)
