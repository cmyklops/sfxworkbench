"""Tests for sfxworkbench.utils."""

from sfxworkbench.utils import fmt_bytes


def test_fmt_bytes_b() -> None:
    assert fmt_bytes(0) == "0.0 B"
    assert fmt_bytes(512) == "512.0 B"


def test_fmt_bytes_kb() -> None:
    assert fmt_bytes(1024) == "1.0 KB"
    assert fmt_bytes(2048) == "2.0 KB"


def test_fmt_bytes_mb() -> None:
    assert fmt_bytes(1024 * 1024) == "1.0 MB"


def test_fmt_bytes_gb() -> None:
    assert fmt_bytes(1024**3) == "1.0 GB"


def test_fmt_bytes_tb() -> None:
    assert fmt_bytes(1024**4) == "1.0 TB"
