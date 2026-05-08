"""Small shared helpers."""

from __future__ import annotations

import json
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
