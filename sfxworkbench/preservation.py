"""Shared duplicate-preservation priority helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_ENV_VAR = "SFXWORKBENCH_CONFIG"


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


def _list_from_config(raw: dict, key: str, *, config_path: Path) -> list:
    value = raw.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{config_path}: {key} must be a list")
    return value


def _values_from_config(raw: dict, key: str, *, config_path: Path) -> list:
    values: list = []
    top_level = _list_from_config(raw, key, config_path=config_path)
    preservation = raw.get("preservation", {})
    if top_level:
        values.extend(top_level)
    if preservation:
        if not isinstance(preservation, dict):
            raise ValueError(f"{config_path}: preservation must be an object")
        values.extend(_list_from_config(preservation, key, config_path=config_path))
    return values


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


def _normalize_config_folders(values: list, *, config_path: Path) -> tuple[str, ...]:
    folders: list[Path] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{config_path}: preservation folder values must be strings")
        folders.append(Path(value))
    return _normalize_folders(folders)


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


def load_preservation_config(config_path: Path | None = None) -> PreservationRules:
    """Load optional shared preservation rules from JSON config.

    Supported shape:

    {
      "safe_folders": ["~/CommercialLibraries/Master"],
      "preservation": {
        "safe_folders": [],
        "prefer_folders": [],
        "prefer_extensions": ["wav"]
      }
    }

    Top-level `safe_folders` is kept as a convenience alias for studio-wide
    protection; nested `preservation` fields hold the full rule set.
    """
    path = config_path
    if path is None:
        env_path = os.environ.get(CONFIG_ENV_VAR)
        if not env_path:
            return PreservationRules()
        path = Path(env_path)
    if not path.exists():
        raise FileNotFoundError(f"sfxworkbench config not found: {path}")
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: sfxworkbench config must be a JSON object")
    return PreservationRules(
        safe_folders=_normalize_config_folders(
            _values_from_config(raw, "safe_folders", config_path=path), config_path=path
        ),
        prefer_folders=_normalize_config_folders(
            _values_from_config(raw, "prefer_folders", config_path=path), config_path=path
        ),
        prefer_extensions=_normalize_extensions(_values_from_config(raw, "prefer_extensions", config_path=path)),
    )


def build_preservation_rules(
    *,
    config_path: Path | None = None,
    safe_folders: list[Path] | None = None,
    prefer_folders: list[Path] | None = None,
    prefer_extensions: list[str] | None = None,
    include_config_prefer_extensions: bool = True,
) -> PreservationRules:
    config = load_preservation_config(config_path)
    config_prefer_extensions = list(config.prefer_extensions) if include_config_prefer_extensions else []
    return PreservationRules(
        safe_folders=_normalize_folders([Path(folder) for folder in config.safe_folders] + list(safe_folders or [])),
        prefer_folders=_normalize_folders(
            [Path(folder) for folder in config.prefer_folders] + list(prefer_folders or [])
        ),
        prefer_extensions=_normalize_extensions(config_prefer_extensions + list(prefer_extensions or [])),
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


def move_protected_by(path: Path, rules: PreservationRules) -> str | None:
    """Return the safe folder touched by moving, renaming, or writing this path."""
    resolved = path.expanduser().resolve()
    for folder in rules.safe_folders:
        safe = Path(folder)
        if resolved == safe or _is_relative_to(resolved, safe) or _is_relative_to(safe, resolved):
            return folder
    return None


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


def score_explanation(path: Path, rules: PreservationRules, *, include_extension: bool = True) -> dict:
    """Return the ordered preservation score and the rule evidence behind it."""
    key = priority_key(path, rules, include_extension=include_extension)
    return {
        "path": str(path),
        "score": list(key[:3]),
        "tie_breaker": key[3],
        "evidence": evidence(path, rules, include_extension=include_extension),
    }
