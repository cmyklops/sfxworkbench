"""Report-only discovery for future embedded metadata write backends."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wavwarden import __version__
from wavwarden.models import MetadataWriteBackend, MetadataWriteBackendsReport

console = Console()

BWF_METAEDIT_NAMES = ("bwfmetaedit", "BWFMetaEdit")
BWF_METAEDIT_VERSION_FLAGS = ("--Version", "--version", "-v")


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
            supported_extensions=[".wav", ".rf64"],
            writes_bext=True,
            writes_ixml=False,
            notes=[
                "Preferred external reference for Broadcast WAV metadata writes.",
                "wavwarden still keeps embedded audio mutation behind reviewed future workflows.",
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
        supported_extensions=[".wav", ".rf64"],
        writes_bext=True,
        writes_ixml=False,
        notes=[
            "Use as the reference behavior before enabling any embedded WAV mutation.",
            "Capture executable and version in future metadata write plans and logs.",
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
        backends=[probe_bwfmetaedit(bwfmetaedit, run=run)],
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
