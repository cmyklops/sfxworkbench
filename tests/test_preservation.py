from pathlib import Path

from wavwarden.preservation import build_preservation_rules, evidence, priority_key, protected_by


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
