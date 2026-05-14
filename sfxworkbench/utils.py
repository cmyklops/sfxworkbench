"""Small shared helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def fmt_bytes(b: float) -> str:
    """Render a byte count as a human-readable string (1.5 GB, 4.2 KB, etc.)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def to_jsonable(value: Any) -> Any:
    """Convert common project values into JSON-serializable objects."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def json_dumps(value: Any) -> str:
    """Stable JSON for CLI machine-readable output."""
    return json.dumps(to_jsonable(value), indent=2, sort_keys=True)


def _default_file_mode() -> int:
    """Return the file mode ``path.write_text`` would produce (umask-derived)."""
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically.

    Uses a sibling temp file, ``fsync``, and ``os.replace`` so a crash mid-write
    leaves the destination either unchanged (if it existed) or absent — never
    truncated or partially written. Parent directories are created as needed.

    The destination's mode is preserved when the file already exists; new files
    receive the umask-derived mode that ``Path.write_text`` would have produced,
    so this helper is drop-in compatible with existing ``write_text`` callsites.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        try:
            target_mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            target_mode = _default_file_mode()
        os.chmod(tmp_name, target_mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    """Atomic counterpart to ``path.write_text(json_dumps(value), encoding="utf-8")``."""
    atomic_write_text(path, json_dumps(value))


# Single-slot in-process cache for parsed plan JSON. Real-world plans hit
# ~100MB on libraries with 139k+ tag entries; each ``json.loads`` of one is
# multi-second + 2-3x peak memory. The TUI loads the same plan from at
# least three places per Metadata-tab activation: the workbench rows
# query, the review-screen mount, and the tag-change-rows panel. Caching
# the parsed dict across those callers within a single session collapses
# repeated work to a single load.
#
# Keyed on (path, mtime, size) so any rewrite invalidates automatically.
# Single slot — overwriting on key mismatch keeps memory bounded.
_PLAN_JSON_CACHE: dict[tuple[str, float, int], dict] = {}


def _plan_signature(path: Path) -> tuple[str, float, int]:
    """Cheap stat-only cache key for a plan JSON file."""
    try:
        stat = path.stat()
    except OSError:
        return (str(path), 0.0, 0)
    return (str(path), stat.st_mtime, stat.st_size)


def progress_interval(total: int) -> int:
    """Return the per-iteration interval at which progress should be reported.

    Targets ~100 progress callbacks across the whole run regardless of total
    size, so a 1M-entry apply doesn't spam the UI with 10k status updates
    (each of which re-renders the Rich-formatted status strip). The result
    stays at 1 for tiny runs so per-entry detail is preserved when there's
    only a handful of items.

    Callers should still poll ``cancel_requested`` at a tighter cadence —
    the cancel callback is cheap and users want sub-second cancellation
    response, but the visual progress bar doesn't need that frequency.
    """
    if total < 100:
        return 1
    return max(1, total // 100)


def load_plan_json_cached(path: Path) -> dict | None:
    """Return parsed plan JSON as a dict, reusing the parse if the file is unchanged.

    Returns ``None`` if the file doesn't exist or fails to parse — callers
    should treat that the same as "no plan loaded" rather than raise, which
    matches how the existing TUI data adapters handle missing plans.

    The returned dict is shared with other callers in the same session; do
    NOT mutate it in place. Read-only iteration is the only safe access.
    """
    if not path.exists():
        return None
    key = _plan_signature(path)
    cached = _PLAN_JSON_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        try:
            import orjson
        except ImportError:
            parsed = json.loads(path.read_text())
        else:
            parsed = orjson.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    # Single slot: evict everything else so memory stays bounded.
    _PLAN_JSON_CACHE.clear()
    _PLAN_JSON_CACHE[key] = parsed
    return parsed
