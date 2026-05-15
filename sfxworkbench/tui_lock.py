"""DB-scoped single-instance lock for the Textual TUI."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def tui_lock_path(db_path: Path) -> Path:
    db = Path(db_path).expanduser().resolve()
    return db.with_name(f"{db.name}.tui.lock")


def lock_file_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.lstrip("\ufeff")
        if not line.startswith("pid="):
            continue
        try:
            return int(line.partition("=")[2])
        except ValueError:
            return None
    return None


def process_is_running(pid: int, *, platform: str = sys.platform, kernel32: Any | None = None) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if platform == "win32":
        if kernel32 is None:
            import ctypes

            kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000
        query_limited = 0x1000
        wait_timeout = 0x00000102
        handle = kernel32.OpenProcess(synchronize | query_limited, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class TuiInstanceLock:
    """Atomic, stale-aware single-instance guard for one TUI database."""

    def __init__(
        self,
        db_path: Path,
        *,
        process_checker: Callable[[int], bool] = process_is_running,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.lock_path = tui_lock_path(self.db_path)
        self._process_checker = process_checker
        self._fd: int | None = None

    def acquire(self) -> None:
        payload = f"pid={os.getpid()}\ndb={self.db_path}\n"
        for attempt in range(2):
            try:
                self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner_pid = lock_file_pid(self.lock_path)
                if owner_pid is not None and self._process_checker(owner_pid):
                    raise RuntimeError(
                        "Another sfxworkbench TUI is already running for "
                        f"{self.db_path} (pid {owner_pid}). Close it before starting a new one."
                    ) from None
                if attempt:
                    raise RuntimeError(
                        f"Another sfxworkbench TUI lock exists at {self.lock_path}. Remove it if no TUI is running."
                    ) from None
                try:
                    self.lock_path.unlink()
                except OSError as exc:
                    raise RuntimeError(f"Could not remove stale TUI lock {self.lock_path}: {exc}") from exc
                continue
            os.write(self._fd, payload.encode("utf-8"))
            return
        raise RuntimeError(f"Could not acquire TUI lock at {self.lock_path}.")

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if lock_file_pid(self.lock_path) == os.getpid():
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
