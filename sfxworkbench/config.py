"""User configuration for sfxworkbench.

The runtime configuration is a Pydantic model loaded from a TOML file. Three
sources are merged with the following precedence (later wins):

1. Defaults baked into :class:`Config` and its sub-models.
2. ``~/.config/sfxworkbench/config.toml`` if it exists.
3. ``$SFX_CONFIG`` environment variable pointing at a TOML file, if set.
4. An explicit ``--config PATH`` (CLI flag) passed to :func:`load_config`.

The CLI surfaces this as a top-level ``--config`` option whose value, once
loaded, is stashed on ``typer.Context.obj``. Subcommands that need user
preferences read them from there. The lookup never silently swallows errors:
malformed TOML or a missing explicitly-requested file raises
:class:`ConfigError` with the offending path.

This module is intentionally *only* the loader + schema. Individual subsystems
(suggestor confidence anchors, backup policy, junk-pattern overrides) hold
their own runtime defaults that match the Pydantic defaults here, so adding a
new override later is a one-line plumbing change rather than a refactor.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ENV_VAR = "SFX_CONFIG"
"""Environment variable that may point at a TOML config file."""

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "sfxworkbench" / "config.toml"
"""Default user config location, searched only if the env var is unset."""


class ConfigError(RuntimeError):
    """Raised when an explicitly-requested config file is missing or invalid.

    The default user-config location and the env-var-pointed location are
    treated as best-effort: if they're absent the loader silently falls back.
    But an explicit ``--config PATH`` that doesn't exist (or doesn't parse)
    is a user-facing error.
    """


class ConfidenceProfile(BaseModel):
    """Per-source confidence anchors used by :mod:`sfxworkbench.tag_suggest`.

    Tuned so structured evidence (UCS, group membership) outranks unstructured
    filename or path heuristics. A future UCS-catalog match sits above the
    plain UCS-heuristic at 0.95. These defaults match the historical hard-coded
    values; user overrides should generally only widen or narrow the bands, not
    invert the ordering.
    """

    model_config = ConfigDict(extra="forbid")

    ucs_heuristic: float = Field(default=0.75, ge=0.0, le=1.0)
    ucs_catalog: float = Field(default=0.95, ge=0.0, le=1.0)
    group: float = Field(default=0.85, ge=0.0, le=1.0)
    filename_abbreviation: float = Field(default=0.65, ge=0.0, le=1.0)
    filename_take: float = Field(default=0.60, ge=0.0, le=1.0)
    filename_description: float = Field(default=0.55, ge=0.0, le=1.0)
    path: float = Field(default=0.50, ge=0.0, le=1.0)
    synonym: float = Field(default=0.62, ge=0.0, le=1.0)


class BackupConfig(BaseModel):
    """Policy for ``.original-<timestamp>`` backups produced before metadata writes.

    Wired into the destructive-command flow in PR #8. Held here as part of
    :class:`Config` so the loader/precedence chain is already in place when
    that PR lands.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    retain_days: int = Field(default=30, ge=0)


class Config(BaseModel):
    """Top-level user configuration."""

    model_config = ConfigDict(extra="forbid")

    library_root: Path | None = None
    """Default library root used when a command does not pass one explicitly."""

    db_path: Path | None = None
    """Override for the SQLite index location. ``None`` keeps the package default."""

    ucs_catalog_path: Path | None = None
    """Override for the UCS catalog JSON cache location."""

    confidence: ConfidenceProfile = Field(default_factory=ConfidenceProfile)
    """Confidence anchors used by the tag suggestor."""

    backup: BackupConfig = Field(default_factory=BackupConfig)
    """Backup policy for destructive commands (see PR #8)."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc


def _config_from_mapping(path: Path, payload: dict[str, Any]) -> Config:
    try:
        return Config.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"invalid config in {path}: {exc}") from exc


def load_config(
    *,
    config_path: Path | None = None,
    env: dict[str, str] | None = None,
    default_locations: Iterable[Path] | None = None,
) -> Config:
    """Resolve the effective :class:`Config` using the documented precedence chain.

    Parameters
    ----------
    config_path:
        Path passed via ``--config`` on the command line. Must exist and parse
        cleanly if given, otherwise :class:`ConfigError` is raised.
    env:
        Mapping to read ``SFX_CONFIG`` from. Defaults to :data:`os.environ`.
        Passing an explicit dict makes this function trivially testable.
    default_locations:
        Iterable of paths checked for a user config when neither ``config_path``
        nor the env var resolves. Defaults to ``[DEFAULT_CONFIG_PATH]``. Each
        candidate that exists is loaded; missing candidates are silent.
    """
    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(f"config file not found: {config_path}")
        return _config_from_mapping(config_path, _read_toml(config_path))

    environment = env if env is not None else os.environ
    env_value = environment.get(ENV_VAR)
    if env_value:
        env_path = Path(env_value).expanduser()
        if not env_path.exists():
            raise ConfigError(f"{ENV_VAR} points at missing file: {env_path}")
        return _config_from_mapping(env_path, _read_toml(env_path))

    candidates = list(default_locations) if default_locations is not None else [DEFAULT_CONFIG_PATH]
    for candidate in candidates:
        if candidate.exists():
            return _config_from_mapping(candidate, _read_toml(candidate))

    return Config()
