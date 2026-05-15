"""Cross-platform path component safety helpers."""

from __future__ import annotations

from pathlib import Path

from sfxworkbench.platform_paths import windows_collision_name_key, windows_collision_path_key

WINDOWS_RESERVED_BASENAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def windows_reserved_basename(component: str) -> str | None:
    """Return the reserved Windows basename for *component*, if any."""
    normalized = component.rstrip(" .")
    if not normalized:
        return None
    basename = normalized.split(".", 1)[0].casefold().upper()
    if basename in WINDOWS_RESERVED_BASENAMES:
        return basename
    return None


def has_windows_trailing_dot_or_space(component: str) -> bool:
    """Return whether Windows would trim trailing dot/space from this name."""
    return component.rstrip(" .") != component


def avoid_windows_reserved_component(component: str) -> tuple[str, bool]:
    """Return a component adjusted away from Windows reserved basenames."""
    if windows_reserved_basename(component) is None:
        return component, False
    if "." in component and not component.startswith("."):
        stem, suffix = component.rsplit(".", 1)
        return f"{stem}_.{suffix}", True
    return f"{component}_", True


def existing_windows_collision(source: Path, target: Path) -> Path | None:
    """Return an existing sibling that would collide with *target* on Windows."""
    try:
        siblings = list(target.parent.iterdir())
    except OSError:
        return None
    target_key = windows_collision_name_key(target.name)
    source_key = windows_collision_path_key(source)
    for sibling in siblings:
        if windows_collision_path_key(sibling) == source_key:
            continue
        if windows_collision_name_key(sibling.name) == target_key:
            return sibling
    return None


def path_exists_windows(target: Path) -> bool:
    """Return whether *target* exists or would collide on Windows."""
    if target.exists():
        return True
    try:
        target_key = windows_collision_name_key(target.name)
        return any(windows_collision_name_key(child.name) == target_key for child in target.parent.iterdir())
    except OSError:
        return False
