"""Tests for sfxworkbench.clean."""

from pathlib import Path

from sfxworkbench.clean import clean_library, find_junk


def test_find_junk_detects_appledouble(tmp_library: Path) -> None:
    junk_files, _ = find_junk(tmp_library)
    names = [f.name for f, _ in junk_files]
    assert any(n.startswith("._") for n in names), "Should find AppleDouble files"


def test_find_junk_detects_ds_store(tmp_library: Path, monkeypatch) -> None:
    """``.DS_Store`` is detected as junk on non-Darwin platforms.

    On macOS the file is exempted (Finder regenerates it) — covered by
    ``test_find_junk_skips_ds_store_on_macos`` below and the unit test
    in ``test_junk.py``.
    """
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    junk_files, _ = find_junk(tmp_library)
    names = [f.name for f, _ in junk_files]
    assert ".DS_Store" in names, "Should find .DS_Store files on non-macOS"


def test_find_junk_skips_ds_store_on_macos(tmp_library: Path, monkeypatch) -> None:
    """``.DS_Store`` is intentionally not flagged as junk on macOS."""
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    junk_files, _ = find_junk(tmp_library)
    names = [f.name for f, _ in junk_files]
    assert ".DS_Store" not in names, "Should not flag .DS_Store as junk on macOS"


def test_find_junk_detects_wfcache_dir(tmp_library: Path) -> None:
    _, junk_dirs = find_junk(tmp_library)
    dir_names = [d.name for d, _ in junk_dirs]
    assert "_wfCache" in dir_names, "Should find _wfCache directory"


def test_find_junk_detects_macosx_dir(tmp_library: Path) -> None:
    _, junk_dirs = find_junk(tmp_library)
    dir_names = [d.name for d, _ in junk_dirs]
    assert "__MACOSX" in dir_names, "Should find __MACOSX directory"


def test_find_junk_detects_reapeaks(tmp_library: Path) -> None:
    junk_files, _ = find_junk(tmp_library)
    extensions = [f.suffix.lower() for f, _ in junk_files]
    assert ".reapeaks" in extensions, "Should find .reapeaks files"


def test_find_junk_detects_sfk(tmp_library: Path) -> None:
    junk_files, _ = find_junk(tmp_library)
    extensions = [f.suffix.lower() for f, _ in junk_files]
    assert ".sfk" in extensions, "Should find .sfk files"


def test_find_junk_returns_sizes(tmp_library: Path) -> None:
    """Returned tuples include captured byte sizes."""
    junk_files, _ = find_junk(tmp_library)
    assert all(isinstance(sz, int) and sz >= 0 for _, sz in junk_files)


def test_dry_run_makes_no_changes(tmp_library: Path) -> None:
    before_files = set(tmp_library.rglob("*"))
    result = clean_library(tmp_library, dry_run=True)
    after_files = set(tmp_library.rglob("*"))
    assert before_files == after_files, "Dry run should not change any files"
    assert result.dry_run is True


def test_apply_removes_junk(tmp_library: Path, monkeypatch) -> None:
    """Apply removes the full junk set on non-macOS platforms (.DS_Store
    included). macOS skips .DS_Store per ``junk.is_junk_file`` — that
    behavior is covered by the unit test in ``test_junk.py``.
    """
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    result = clean_library(tmp_library, dry_run=False)
    assert result.dry_run is False

    remaining = list(tmp_library.rglob("*"))
    remaining_names = [f.name for f in remaining]

    assert ".DS_Store" not in remaining_names, "DS_Store should be removed"
    assert not any(n.startswith("._") for n in remaining_names), "AppleDouble files should be removed"
    assert not any(tmp_library / "_wfCache" in p.parents or p == tmp_library / "_wfCache" for p in remaining), (
        "_wfCache dir should be gone"
    )


def test_apply_leaves_audio_files(tmp_library: Path) -> None:
    clean_library(tmp_library, dry_run=False)
    remaining = list(tmp_library.rglob("*"))
    wav_files = [f for f in remaining if f.suffix.lower() == ".wav" and not f.name.startswith("._")]
    assert len(wav_files) > 0, "Audio files should remain after clean"


def test_clean_result_counts(tmp_library: Path) -> None:
    result = clean_library(tmp_library, dry_run=True)
    assert len(result.removed_files) > 0, "Should report files to remove"
    assert len(result.removed_dirs) >= 2, "Should report at least _wfCache and __MACOSX dirs"
    assert result.bytes_freed > 0, "Should report bytes to free"


def test_clean_log_written(tmp_library: Path, tmp_path: Path) -> None:
    import json

    log_path = tmp_path / "clean_log.json"
    clean_library(tmp_library, dry_run=True, log_path=log_path)
    assert log_path.exists(), "Log file should be created"
    data = json.loads(log_path.read_text())
    assert "removed_files" in data
    assert "dry_run" in data
    assert data["dry_run"] is True


def test_clean_apply_drops_index_rows_for_removed_files(tmp_path: Path, tmp_db: Path) -> None:
    """Junk files that happen to be indexed must have their rows removed so the size status drops."""
    from sfxworkbench.db import get_connection

    root = tmp_path / "library"
    root.mkdir()
    junk_path = root / "leftover.reapeaks"
    audio_path = root / "keep.wav"
    junk_path.write_text("junk-bytes-go-here")
    audio_path.write_bytes(b"audio-bytes")
    conn = get_connection(tmp_db)
    for path, size in ((junk_path, junk_path.stat().st_size), (audio_path, audio_path.stat().st_size)):
        conn.execute(
            """
            INSERT INTO files (path, filename, stem, extension, size_bytes, mtime, md5, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(path), path.name, path.stem, path.suffix.lower(), size, 0.0, None, "2026"),
        )
    conn.commit()
    before_total = conn.execute("SELECT COALESCE(SUM(size_bytes), 0) AS s FROM files").fetchone()["s"]
    conn.close()
    assert before_total > 0

    clean_library(root, dry_run=False, quiet=True, db_path=tmp_db)

    conn = get_connection(tmp_db)
    remaining_paths = {row["path"] for row in conn.execute("SELECT path FROM files").fetchall()}
    after_total = conn.execute("SELECT COALESCE(SUM(size_bytes), 0) AS s FROM files").fetchone()["s"]
    conn.close()
    assert remaining_paths == {str(audio_path)}
    assert after_total == audio_path.stat().st_size


def test_clean_apply_reports_finalizing_steps_before_complete(tmp_path: Path, tmp_db: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (root / "leftover.reapeaks").write_text("junk")
    log_path = tmp_path / "clean_log.json"
    events: list[tuple[str, int, int | None, str]] = []

    clean_library(
        root,
        dry_run=False,
        log_path=log_path,
        quiet=True,
        db_path=tmp_db,
        progress_callback=lambda phase, completed, total, message: events.append((phase, completed, total, message)),
    )

    phases = [phase for phase, _, _, _ in events]
    assert "cleaning" in phases
    assert "updating_index" in phases
    assert "writing_log" in phases
    assert phases[-1] == "complete"
    assert phases.index("cleaning") < phases.index("updating_index") < phases.index("writing_log")
    assert log_path.exists()


def test_cancelled_apply_reports_only_removed_junk(tmp_path: Path) -> None:
    import json

    root = tmp_path / "library"
    root.mkdir()
    for index in range(60):
        (root / f"waveform_{index}.reapeaks").write_text("junk")
    log_path = tmp_path / "clean_log.json"

    result = clean_library(root, dry_run=False, log_path=log_path, quiet=True, cancel_requested=lambda: True)

    assert result.cancelled is True
    assert len(result.removed_files) == 50
    assert result.removed_dirs == []
    assert result.bytes_freed == 50 * len("junk")
    assert len(list(root.glob("*.reapeaks"))) == 10

    data = json.loads(log_path.read_text())
    assert data["cancelled"] is True
    assert len(data["removed_files"]) == 50
    assert data["bytes_freed"] == result.bytes_freed
