"""Tests for the `sfx config show` / `sfx config validate` commands (PR #15)."""

from __future__ import annotations

import json
from pathlib import Path

from sfxworkbench.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def _write_toml(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_sfx_config_show_with_no_config_prints_defaults() -> None:
    """Without a config file, ``sfx config show --json`` reports the bake-in defaults."""
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["confidence"]["ucs_heuristic"] == 0.75
    assert payload["confidence"]["ucs_catalog"] == 0.95
    assert payload["backup"]["enabled"] is True
    assert payload["backup"]["retain_days"] == 30


def test_sfx_config_show_reflects_override_loaded_via_flag(tmp_path: Path) -> None:
    """``sfx --config FILE config show`` reflects the override resolved by the top-level callback."""
    cfg_file = _write_toml(
        tmp_path / "override.toml",
        "[confidence]\nucs_heuristic = 0.11\n[backup]\nretain_days = 7\n",
    )
    result = runner.invoke(app, ["--config", str(cfg_file), "config", "show", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["confidence"]["ucs_heuristic"] == 0.11
    # Untouched defaults still come through.
    assert payload["confidence"]["ucs_catalog"] == 0.95
    assert payload["backup"]["retain_days"] == 7


def test_sfx_config_validate_ok(tmp_path: Path) -> None:
    cfg_file = _write_toml(tmp_path / "ok.toml", "[confidence]\nucs_heuristic = 0.5\n")
    result = runner.invoke(app, ["config", "validate", str(cfg_file), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "config_validate"


def test_sfx_config_validate_rejects_invalid_toml(tmp_path: Path) -> None:
    bad = _write_toml(tmp_path / "bad.toml", "this is = not [valid toml")
    result = runner.invoke(app, ["config", "validate", str(bad)])
    assert result.exit_code == 1
    assert "Invalid config" in result.output or "invalid TOML" in result.output


def test_sfx_config_validate_rejects_out_of_range(tmp_path: Path) -> None:
    bad = _write_toml(tmp_path / "out.toml", "[confidence]\nucs_heuristic = 1.5\n")
    result = runner.invoke(app, ["config", "validate", str(bad), "--json"])
    assert result.exit_code == 1
    # JSON path: should still emit a structured ok=False message.
    if result.stdout.strip().startswith("{"):
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "invalid config" in payload["error"].lower()
