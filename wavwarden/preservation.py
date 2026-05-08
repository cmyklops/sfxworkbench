"""Shared duplicate-preservation priority helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreservationRules:
    safe_folders: tuple[str, ...] = ()
    prefer_folders: tuple[str, ...] = ()
    prefer_extensions: tuple[str, ...] = ()

    def model(self) -> dict:
        rules: list[dict] = []
        if self.safe_folders:
            rules.append({"rule": "prefer_safe_folder", "values": list(self.safe_folders)})
        if self.prefer_folders:
            rules.append({"rule": "prefer_folder", "values": list(self.prefer_folders)})
        if self.prefer_extensions:
            rules.append({"rule": "prefer_extension", "values": list(self.prefer_extensions)})
        return {"rules": rules}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalize_folders(folders: list[Path] | None) -> tuple[str, ...]:
    if not folders:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for folder in folders:
        resolved = str(folder.expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(resolved)
    return tuple(normalized)


def _normalize_extensions(extensions: list[str] | None) -> tuple[str, ...]:
    if not extensions:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for extension in extensions:
        value = extension.strip().lower()
        if not value:
            continue
        if not value.startswith("."):
            value = f".{value}"
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def build_preservation_rules(
    *,
    safe_folders: list[Path] | None = None,
    prefer_folders: list[Path] | None = None,
    prefer_extensions: list[str] | None = None,
) -> PreservationRules:
    return PreservationRules(
        safe_folders=_normalize_folders(safe_folders),
        prefer_folders=_normalize_folders(prefer_folders),
        prefer_extensions=_normalize_extensions(prefer_extensions),
    )


def matching_folder(path: Path, folders: tuple[str, ...]) -> str | None:
    resolved = path.expanduser().resolve()
    for folder in folders:
        candidate = Path(folder)
        if resolved == candidate or _is_relative_to(resolved, candidate):
            return folder
    return None


def protected_by(path: Path, rules: PreservationRules) -> str | None:
    return matching_folder(path, rules.safe_folders)


def priority_key(path: Path, rules: PreservationRules, *, include_extension: bool = True) -> tuple[int, int, int, str]:
    safe_match = matching_folder(path, rules.safe_folders)
    preferred_folder = matching_folder(path, rules.prefer_folders)
    preferred_extension = path.suffix.lower() if include_extension else None
    extension_index = (
        rules.prefer_extensions.index(preferred_extension)
        if preferred_extension in rules.prefer_extensions
        else len(rules.prefer_extensions)
    )
    return (
        0 if safe_match is not None else 1,
        rules.prefer_folders.index(preferred_folder) if preferred_folder is not None else len(rules.prefer_folders),
        extension_index,
        str(path),
    )


def evidence(path: Path, rules: PreservationRules, *, include_extension: bool = True) -> list[dict]:
    result: list[dict] = []
    safe_match = matching_folder(path, rules.safe_folders)
    if safe_match is not None:
        result.append({"rule": "prefer_safe_folder", "value": safe_match})
    preferred_folder = matching_folder(path, rules.prefer_folders)
    if preferred_folder is not None:
        result.append({"rule": "prefer_folder", "value": preferred_folder})
    extension = path.suffix.lower()
    if include_extension and extension in rules.prefer_extensions:
        result.append({"rule": "prefer_extension", "value": extension})
    return result
