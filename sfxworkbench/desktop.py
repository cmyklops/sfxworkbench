"""Desktop reveal and audition command adapters."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


def _powershell_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class DesktopIntegration:
    """Build and launch platform-specific desktop commands."""

    platform: str = sys.platform
    which: Callable[[str], str | None] = shutil.which
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen
    run: Callable[..., Any] = subprocess.run

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

    def choose_directory(self, initial: Path | None = None) -> Path | None:
        """Open a native-ish directory picker and return the selected folder."""
        initial_path = str((initial or Path.home()).expanduser())
        if self.platform == "win32":
            escaped = _powershell_single_quoted(initial_path)
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$dialog.Description = 'Choose an sfx library folder'; "
                f"$dialog.SelectedPath = {escaped}; "
                "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
                "{ [Console]::Out.Write($dialog.SelectedPath) }"
            )
            command = ["powershell", "-NoProfile", "-STA", "-Command", script]
        elif self.platform == "darwin":
            escaped = initial_path.replace("\\", "\\\\").replace('"', '\\"')
            command = [
                "osascript",
                "-e",
                f'POSIX path of (choose folder with prompt "Choose an sfx library folder" default location POSIX file "{escaped}")',
            ]
        else:
            picker = self.which("zenity") or self.which("kdialog")
            if picker is None:
                return None
            if Path(picker).name == "kdialog":
                command = [picker, "--getexistingdirectory", initial_path]
            else:
                command = [picker, "--file-selection", "--directory", "--filename", initial_path]
        completed = self.run(command, capture_output=True, text=True, check=False)
        selected = str(getattr(completed, "stdout", "") or "").strip()
        if not selected:
            return None
        if self.platform == "win32":
            selected = PureWindowsPath(selected).as_posix()
        return Path(selected).expanduser()


def desktop_open_command(
    target: Path,
    *,
    reveal: bool = False,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Compatibility helper for callers/tests that need only the argv."""
    return DesktopIntegration(platform=platform, which=which).command(target, reveal=reveal)
