"""Tests for sfxworkbench.config (PR #4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sfxworkbench.cli import app
from sfxworkbench.config import (
    DEFAULT_CONFIG_PATH,
    ConfidenceProfile,
    Config,
    ConfigError,
    load_config,
)
from typer.testing import CliRunner

runner = CliRunner()


# -- Defaults ---------------------------------------------------------------


def test_load_config_with_no_inputs_returns_defaults(tmp_path: Path) -> None:
    """When nothing resolves, the loader returns a Config with default values."""
    missing = tmp_path / "definitely_does_not_exist.toml"
    cfg = load_config(env={}, default_locations=[missing])

    assert cfg.library_root is None
    assert cfg.db_path is None
    assert cfg.confidence.ucs_heuristic == 0.75
    assert cfg.confidence.ucs_catalog == 0.95
    assert cfg.backup.enabled is True
    assert cfg.backup.retain_days == 30


def test_confidence_profile_defaults_match_tag_suggest_anchors() -> None:
    """ConfidenceProfile is the single source of truth for the historical anchors."""
    profile = ConfidenceProfile()
    assert profile.ucs_heuristic == 0.75
    assert profile.ucs_catalog == 0.95
    assert profile.group == 0.85
    assert profile.filename_abbreviation == 0.65
    assert profile.filename_take == 0.60
    assert profile.filename_description == 0.55
    assert profile.path == 0.50
    assert profile.synonym == 0.62


# -- Precedence chain -------------------------------------------------------


def _write_toml(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_explicit_config_path_overrides_env_and_defaults(tmp_path: Path) -> None:
    explicit = _write_toml(
        tmp_path / "explicit.toml",
        "[confidence]\nucs_heuristic = 0.10\n",
    )
    env_file = _write_toml(
        tmp_path / "env.toml",
        "[confidence]\nucs_heuristic = 0.20\n",
    )
    default_file = _write_toml(
        tmp_path / "default.toml",
        "[confidence]\nucs_heuristic = 0.30\n",
    )

    cfg = load_config(
        config_path=explicit,
        env={"SFX_CONFIG": str(env_file)},
        default_locations=[default_file],
    )
    assert cfg.confidence.ucs_heuristic == 0.10


def test_env_var_takes_precedence_over_default_location(tmp_path: Path) -> None:
    env_file = _write_toml(tmp_path / "env.toml", "[confidence]\nucs_heuristic = 0.20\n")
    default_file = _write_toml(tmp_path / "default.toml", "[confidence]\nucs_heuristic = 0.30\n")

    cfg = load_config(env={"SFX_CONFIG": str(env_file)}, default_locations=[default_file])
    assert cfg.confidence.ucs_heuristic == 0.20


def test_default_location_used_when_no_flag_or_env(tmp_path: Path) -> None:
    default_file = _write_toml(tmp_path / "default.toml", "[confidence]\nucs_heuristic = 0.30\n")

    cfg = load_config(env={}, default_locations=[default_file])
    assert cfg.confidence.ucs_heuristic == 0.30


def test_default_locations_silently_skip_missing_candidates(tmp_path: Path) -> None:
    missing_a = tmp_path / "never_existed_a.toml"
    missing_b = tmp_path / "never_existed_b.toml"

    cfg = load_config(env={}, default_locations=[missing_a, missing_b])
    # Falls all the way back to defaults rather than erroring.
    assert cfg.confidence.ucs_heuristic == 0.75


def test_default_config_path_constant_points_at_xdg_location() -> None:
    """Sanity check that the documented default location matches what's used."""
    assert DEFAULT_CONFIG_PATH == Path.home() / ".config" / "sfxworkbench" / "config.toml"


# -- Error handling ---------------------------------------------------------


def test_explicit_config_path_missing_raises(tmp_path: Path) -> None:
    """An explicit ``--config`` that doesn't exist is a user-facing error."""
    missing = tmp_path / "explicit_missing.toml"

    with pytest.raises(ConfigError, match="config file not found"):
        load_config(config_path=missing)


def test_env_var_pointing_at_missing_file_raises(tmp_path: Path) -> None:
    """If ``$SFX_CONFIG`` points somewhere that doesn't exist, that's an error."""
    missing = tmp_path / "env_target_missing.toml"

    with pytest.raises(ConfigError, match="SFX_CONFIG points at missing file"):
        load_config(env={"SFX_CONFIG": str(missing)})


def test_malformed_toml_raises_config_error(tmp_path: Path) -> None:
    bad = _write_toml(tmp_path / "bad.toml", "this is = not [valid toml")

    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(config_path=bad)


def test_unknown_field_in_config_is_rejected(tmp_path: Path) -> None:
    """``extra="forbid"`` catches typos in user config files."""
    rogue = _write_toml(tmp_path / "rogue.toml", 'mystery_field = "what is this"\n')

    with pytest.raises(ConfigError, match="invalid config"):
        load_config(config_path=rogue)


def test_out_of_range_confidence_is_rejected(tmp_path: Path) -> None:
    """ge/le constraints catch nonsensical thresholds."""
    bad = _write_toml(tmp_path / "out_of_range.toml", "[confidence]\nucs_heuristic = 1.5\n")

    with pytest.raises(ConfigError, match="invalid config"):
        load_config(config_path=bad)


# -- Partial overrides ------------------------------------------------------


def test_partial_override_preserves_other_defaults(tmp_path: Path) -> None:
    """A TOML file that sets one field leaves all other defaults intact."""
    partial = _write_toml(tmp_path / "partial.toml", "[confidence]\nucs_heuristic = 0.42\n")

    cfg = load_config(config_path=partial)
    assert cfg.confidence.ucs_heuristic == 0.42
    # Untouched defaults remain.
    assert cfg.confidence.ucs_catalog == 0.95
    assert cfg.confidence.group == 0.85
    assert cfg.backup.enabled is True


def test_library_root_path_round_trips_through_toml(tmp_path: Path) -> None:
    cfg_file = _write_toml(
        tmp_path / "with_root.toml",
        f"library_root = '{tmp_path / 'library'}'\n",
    )

    cfg = load_config(config_path=cfg_file)
    assert isinstance(cfg.library_root, Path)
    assert cfg.library_root == tmp_path / "library"


# -- CLI integration --------------------------------------------------------


def test_cli_main_accepts_config_flag(tmp_path: Path) -> None:
    """The top-level ``--config`` flag is registered on the main app.

    ``--version`` is eager and bypasses the callback, so we just verify the
    invocation succeeds with no error. The loader's behavior is tested
    exhaustively above via direct ``load_config`` calls.
    """
    cfg_file = _write_toml(tmp_path / "cli.toml", "[confidence]\nucs_heuristic = 0.11\n")

    result = runner.invoke(app, ["--config", str(cfg_file), "--version"])
    assert result.exit_code == 0


def test_config_model_dump_round_trips(tmp_path: Path) -> None:
    """Config can be reconstructed from its own model_dump output."""
    original = Config(
        library_root=tmp_path / "lib",
        confidence=ConfidenceProfile(ucs_heuristic=0.42),
    )
    rebuilt = Config.model_validate(original.model_dump())
    assert rebuilt.library_root == tmp_path / "lib"
    assert rebuilt.confidence.ucs_heuristic == 0.42
    assert rebuilt.confidence.ucs_catalog == 0.95
