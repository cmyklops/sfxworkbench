import json
from pathlib import Path

from sfxworkbench.preservation import (
    build_preservation_rules,
    evidence,
    load_preservation_config,
    priority_key,
    protected_by,
)


def test_load_preservation_config_supports_top_level_and_nested_rules(tmp_path: Path) -> None:
    safe = tmp_path / "Master"
    nested_safe = tmp_path / "Archive"
    preferred = tmp_path / "Preferred"
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(
        json.dumps(
            {
                "safe_folders": [str(safe)],
                "preservation": {
                    "safe_folders": [str(nested_safe)],
                    "prefer_folders": [str(preferred)],
                    "prefer_extensions": ["wav"],
                },
            }
        )
    )

    rules = load_preservation_config(config_path)

    assert rules.safe_folders == (str(safe.resolve()), str(nested_safe.resolve()))
    assert rules.prefer_folders == (str(preferred.resolve()),)
    assert rules.prefer_extensions == (".wav",)


def test_load_preservation_config_rejects_scalar_lists(tmp_path: Path) -> None:
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": str(tmp_path / "Master")}))

    try:
        load_preservation_config(config_path)
    except ValueError as exc:
        assert "safe_folders must be a list" in str(exc)
    else:
        raise AssertionError("scalar safe_folders should be rejected")


def test_build_preservation_rules_merges_config_before_cli_overrides(tmp_path: Path) -> None:
    config_safe = tmp_path / "Master"
    cli_safe = tmp_path / "Session"
    config_path = tmp_path / "sfxworkbench.json"
    config_path.write_text(json.dumps({"safe_folders": [str(config_safe)]}))

    rules = build_preservation_rules(config_path=config_path, safe_folders=[cli_safe])

    assert rules.safe_folders == (str(config_safe.resolve()), str(cli_safe.resolve()))


def test_preservation_rules_keep_user_priority_order(tmp_path: Path) -> None:
    second = tmp_path / "Second"
    first = tmp_path / "First"

    rules = build_preservation_rules(
        prefer_folders=[second, first, second],
        prefer_extensions=["flac", ".wav", "FLAC"],
    )

    assert rules.prefer_folders == (str(second.resolve()), str(first.resolve()))
    assert rules.prefer_extensions == (".flac", ".wav")
    assert rules.model()["rules"] == [
        {"rule": "prefer_folder", "values": [str(second.resolve()), str(first.resolve())]},
        {"rule": "prefer_extension", "values": [".flac", ".wav"]},
    ]


def test_priority_key_prefers_safe_folder_then_folder_then_extension(tmp_path: Path) -> None:
    safe = tmp_path / "Safe"
    preferred = tmp_path / "Preferred"
    regular = tmp_path / "Regular"
    rules = build_preservation_rules(
        safe_folders=[safe],
        prefer_folders=[preferred],
        prefer_extensions=["wav"],
    )

    ordered = sorted(
        [
            regular / "sound.wav",
            preferred / "sound.flac",
            preferred / "sound.wav",
            safe / "sound.aif",
        ],
        key=lambda path: priority_key(path, rules),
    )

    assert ordered == [
        safe / "sound.aif",
        preferred / "sound.wav",
        preferred / "sound.flac",
        regular / "sound.wav",
    ]
    assert protected_by(safe / "sound.aif", rules) == str(safe.resolve())
    assert evidence(preferred / "sound.wav", rules) == [
        {"rule": "prefer_folder", "value": str(preferred.resolve())},
        {"rule": "prefer_extension", "value": ".wav"},
    ]
