"""Small shared helpers."""


def fmt_bytes(b: float) -> str:
    """Render a byte count as a human-readable string (1.5 GB, 4.2 KB, etc.)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
