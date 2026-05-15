"""Desktop reveal and audition command adapters."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


def _powershell_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class DesktopIntegration:
    """Build and launch platform-specific desktop commands."""

    platform: str = sys.platform
    which: Callable[[str], str | None] = shutil.which
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen

    def command(self, target: Path, *, reveal: bool = False) -> list[str]:
        """Return a desktop command for revealing a path or auditioning audio."""
        if reveal:
            if self.platform == "darwin":
                return ["open", "-R", str(target)]
            if self.platform == "win32":
                return ["explorer", f"/select,{target}"]
            opener = self.which("xdg-open")
            if opener is None:
                return []
            return [opener, str(target.parent)]

        if self.platform == "darwin":
            return ["afplay", str(target)]
        if self.platform == "win32":
            escaped = _powershell_single_quoted(str(target))
            return [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(New-Object Media.SoundPlayer {escaped}).PlaySync()",
            ]
        for tool in ("paplay", "aplay", "play"):
            path = self.which(tool)
            if path is not None:
                return [path, str(target)]
        return []

    def open(self, target: Path, *, reveal: bool = False) -> list[str]:
        """Launch a desktop command and return the argv used."""
        command = self.command(target, reveal=reveal)
        if command:
            self.popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return command


def desktop_open_command(
    target: Path,
    *,
    reveal: bool = False,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Compatibility helper for callers/tests that need only the argv."""
    return DesktopIntegration(platform=platform, which=which).command(target, reveal=reveal)
