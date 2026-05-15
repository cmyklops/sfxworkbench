"""Tests for host-independent path comparison helpers."""

from __future__ import annotations

from pathlib import Path

from sfxworkbench.platform_paths import (
    canonical_path_key,
    is_scoped_path,
    resolve_scope_root,
    safe_relative_display,
    scoped_relative_parts,
    scoped_relative_path,
    windows_collision_name_key,
    windows_collision_path_key,
)


def test_canonical_path_key_normalizes_windows_text_lexically() -> None:
    assert canonical_path_key(r"C:\Libraries\SFX\Hit.wav") == "c:/libraries/sfx/hit.wav"
    assert canonical_path_key("C:/Libraries/SFX/") == "c:/libraries/sfx"
    assert canonical_path_key("//Studio NAS/SFX Share/Hit.wav") == "//studio nas/sfx share/hit.wav"


def test_scoped_relative_path_handles_windows_paths_on_posix() -> None:
    root = r"C:\Libraries\SFX"
    candidate = r"c:/libraries/sfx/Impacts/Big Hit.wav"

    assert is_scoped_path(candidate, root)
    assert scoped_relative_path(candidate, root) == "Impacts/Big Hit.wav"
    assert scoped_relative_parts(candidate, root) == ("Impacts", "Big Hit.wav")


def test_safe_relative_display_falls_back_for_out_of_scope_paths() -> None:
    assert safe_relative_display("/tmp/library/hit.wav", "/tmp/library") == "hit.wav"
    assert safe_relative_display("/tmp/other/hit.wav", "/tmp/library") == "/tmp/other/hit.wav"


def test_resolve_scope_root_preserves_windows_like_roots() -> None:
    root = resolve_scope_root(r"C:\Libraries\SFX")

    assert isinstance(root, Path)
    assert str(root) == r"C:\Libraries\SFX"


def test_windows_collision_keys_fold_case_and_trim_trailing_dot_space() -> None:
    assert windows_collision_name_key("Hit .WAV ") == "hit .wav"
    assert windows_collision_path_key(r"C:\Library\Hit.wav ") == "c:/library/hit.wav"
