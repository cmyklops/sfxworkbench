"""Workflow + idempotency tests for sfxworkbench.dual_mono (PR #9).

Covers the previously-untested stereo-to-mono detection and copy-output
pipeline. Tests stay at the helper level — the real copy is exercised through
``apply_dual_mono_plan`` in dry-run mode plus one applied conversion check.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from sfxworkbench.db import get_connection
from sfxworkbench.dual_mono import (
    apply_dual_mono_plan,
    build_dual_mono_plan,
    build_dual_mono_report,
    load_dual_mono_plan,
    review_dual_mono_plan,
    write_dual_mono_plan,
)

# -- WAV fixtures -----------------------------------------------------------


def _write_stereo_wav(path: Path, *, samples: bytes, identical_channels: bool) -> None:
    """Write a 2-channel 16-bit PCM WAV at 48 kHz. Same samples in both channels iff *identical_channels*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        if identical_channels:
            # Interleave left=right.
            interleaved = b"".join(samples[i : i + 2] + samples[i : i + 2] for i in range(0, len(samples), 2))
        else:
            # Interleave left=samples, right=zeros so channels differ.
            interleaved = b"".join(samples[i : i + 2] + b"\x00\x00" for i in range(0, len(samples), 2))
        w.writeframes(interleaved)


def _seed_stereo_file(tmp_db: Path, path: Path) -> None:
    """Insert a row for *path* into the test DB so dual_mono can find it."""
    stat = path.stat()
    with get_connection(tmp_db) as conn:
        conn.execute(
            """
            INSERT INTO files (
                path, filename, stem, extension, size_bytes, mtime, channels,
                sample_rate, bit_depth, duration_s, scan_error, scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '2026-05-12T00:00:00Z')
            """,
            (
                str(path),
                path.name,
                path.stem,
                path.suffix.lower(),
                stat.st_size,
                stat.st_mtime,
                2,
                48000,
                16,
                1.0,
            ),
        )
        conn.commit()


# -- build_dual_mono_report -------------------------------------------------


def test_build_dual_mono_report_flags_identical_channel_files(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    samples = struct.pack("<" + "h" * 100, *range(100))  # 100 samples, each 2 bytes

    fake_mono = root / "AMB_RAIN_01.wav"
    real_stereo = root / "AMB_OCEAN_01.wav"
    _write_stereo_wav(fake_mono, samples=samples, identical_channels=True)
    _write_stereo_wav(real_stereo, samples=samples, identical_channels=False)
    _seed_stereo_file(tmp_db, fake_mono)
    _seed_stereo_file(tmp_db, real_stereo)

    report = build_dual_mono_report(root, tmp_db)

    flagged_paths = {entry.path for entry in report.entries}
    assert str(fake_mono) in flagged_paths
    assert str(real_stereo) not in flagged_paths
    assert report.summary.exact == 1


# -- build_dual_mono_plan + review ------------------------------------------


def _make_plan(tmp_path: Path, tmp_db: Path) -> Path:
    root = tmp_path / "library"
    samples = struct.pack("<" + "h" * 100, *range(100))
    audio = root / "AMB_RAIN_01.wav"
    _write_stereo_wav(audio, samples=samples, identical_channels=True)
    _seed_stereo_file(tmp_db, audio)

    report = build_dual_mono_report(root, tmp_db)
    plan = build_dual_mono_plan_from_report(report)
    plan_path = tmp_path / "dual_mono_plan.json"
    write_dual_mono_plan(plan, plan_path, quiet=True)
    return plan_path


def build_dual_mono_plan_from_report(report) -> object:
    """Local shim: dual_mono.build_dual_mono_plan takes a report path, so write to a tmp file first."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        f.write(report.model_dump_json())
        report_path = Path(f.name)
    return build_dual_mono_plan(report_path)


def test_review_dual_mono_plan_approve_all(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = _make_plan(tmp_path, tmp_db)

    review_dual_mono_plan(plan_path, approve_all=True, quiet=True)

    loaded = load_dual_mono_plan(plan_path)
    assert all(e.review_status == "approved" for e in loaded.entries)


# -- apply_dual_mono_plan (dry-run) -----------------------------------------


def test_apply_dual_mono_plan_dry_run_writes_nothing(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = _make_plan(tmp_path, tmp_db)
    review_dual_mono_plan(plan_path, approve_all=True, quiet=True)
    output_root = tmp_path / "mono_output"

    result = apply_dual_mono_plan(
        plan_path,
        output_root=output_root,
        dry_run=True,
        require_reviewed=True,
        quiet=True,
    )

    assert result.dry_run is True
    # output_root is not created in dry-run.
    assert not output_root.exists() or list(output_root.rglob("*.wav")) == []


def test_apply_dual_mono_plan_apply_writes_mono_file(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = _make_plan(tmp_path, tmp_db)
    review_dual_mono_plan(plan_path, approve_all=True, quiet=True)
    output_root = tmp_path / "mono_output"

    result = apply_dual_mono_plan(
        plan_path,
        output_root=output_root,
        dry_run=False,
        require_reviewed=True,
        quiet=True,
    )

    assert result.written >= 1
    # A mono file was written somewhere under output_root.
    mono_files = list(output_root.rglob("*.mono.wav"))
    assert mono_files
    # And it really is mono.
    with wave.open(str(mono_files[0]), "rb") as r:
        assert r.getnchannels() == 1


# -- Idempotency ------------------------------------------------------------


def test_apply_dual_mono_plan_dry_run_is_idempotent(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = _make_plan(tmp_path, tmp_db)
    review_dual_mono_plan(plan_path, approve_all=True, quiet=True)
    output_root = tmp_path / "mono_output"

    first = apply_dual_mono_plan(plan_path, output_root=output_root, dry_run=True, require_reviewed=True, quiet=True)
    second = apply_dual_mono_plan(plan_path, output_root=output_root, dry_run=True, require_reviewed=True, quiet=True)

    assert first.written == second.written
    assert first.skipped == second.skipped
    assert first.errors == second.errors
