"""Tests for the metadata-review screen helpers (PR #11).

The Textual ``Screen`` class itself is constructed lazily by
``build_metadata_review_screen`` so this module can import and exercise the
pure data layer without requiring the ``tui`` optional extra.

End-to-end interaction tests with Textual ``Pilot`` are intentionally not
added here — they're brittle in CI and the data-shape tests + binding
introspection give enough coverage for PR #11. The full Pilot snapshot suite
is the natural follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path

from sfxworkbench.tui_screens.metadata_review import (
    FileReviewItem,
    TagCandidate,
    build_review_queue,
)

# -- TagCandidate.diff_marker ----------------------------------------------


def _candidate(**overrides) -> TagCandidate:
    """Build a TagCandidate with sensible defaults for the diff-marker tests."""
    defaults = {
        "entry_id": 1,
        "field": "description",
        "proposed_value": "Rain",
        "current_value": None,
        "source": "filename",
        "confidence": 0.6,
    }
    defaults.update(overrides)
    return TagCandidate(**defaults)


def test_diff_marker_says_new_when_no_current_value() -> None:
    assert _candidate(current_value=None).diff_marker == "new"


def test_diff_marker_says_new_when_current_value_blank() -> None:
    assert _candidate(current_value="   ").diff_marker == "new"


def test_diff_marker_says_same_when_values_match() -> None:
    candidate = _candidate(proposed_value="Rain Heavy", current_value="Rain Heavy")
    assert candidate.diff_marker == "same"


def test_diff_marker_says_change_when_values_differ() -> None:
    candidate = _candidate(proposed_value="Rain", current_value="Drizzle")
    assert candidate.diff_marker == "change"


# -- build_review_queue -----------------------------------------------------


_NEXT_ENTRY_ID = [0]


def _entry(**overrides) -> dict:
    """Build a plan-entry dict for tests, auto-assigning sequential entry_ids."""
    _NEXT_ENTRY_ID[0] += 1
    defaults = {
        "entry_id": _NEXT_ENTRY_ID[0],
        "path": "/lib/AMB_RAIN_01.wav",
        "filename": "AMB_RAIN_01.wav",
        "field": "description",
        "proposed_value": "Rain",
        "review_status": "pending",
        "source": "filename",
        "action": "add",
        "existing_values": [],
        "confidence": 0.6,
    }
    defaults.update(overrides)
    return defaults


def _write_plan(plan_path: Path, entries: list[dict]) -> None:
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({"schema_version": 1, "entries": entries}, indent=2))


def test_build_review_queue_groups_entries_by_file(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = tmp_path / "plan.json"
    _write_plan(
        plan_path,
        [
            _entry(
                path="/lib/AMB_RAIN_01.wav",
                filename="AMB_RAIN_01.wav",
                field="description",
                proposed_value="Rain Heavy",
            ),
            _entry(
                path="/lib/AMB_RAIN_01.wav",
                filename="AMB_RAIN_01.wav",
                field="keyword",
                proposed_value="downpour",
                source="synonym",
            ),
            _entry(
                path="/lib/SFX_BOOM_01.wav",
                filename="SFX_BOOM_01.wav",
                field="description",
                proposed_value="Boom",
                review_status="approved",
            ),
        ],
    )

    items = build_review_queue(plan_path, db_path=tmp_db)
    by_path = {item.path: item for item in items}

    assert set(by_path) == {"/lib/AMB_RAIN_01.wav", "/lib/SFX_BOOM_01.wav"}
    rain = by_path["/lib/AMB_RAIN_01.wav"]
    assert isinstance(rain, FileReviewItem)
    assert rain.filename == "AMB_RAIN_01.wav"
    assert {c.field for c in rain.candidates} == {"description", "keyword"}


def test_build_review_queue_carries_entry_ids_for_persistence(tmp_path: Path, tmp_db: Path) -> None:
    """The entry_id round-trips so persistence can later call review_tag_plan with it."""
    plan_path = tmp_path / "plan.json"
    _write_plan(
        plan_path,
        [
            _entry(path="/lib/a.wav", filename="a.wav", field="keyword", proposed_value="rain"),
            _entry(path="/lib/a.wav", filename="a.wav", field="keyword", proposed_value="storm"),
        ],
    )

    items = build_review_queue(plan_path, db_path=tmp_db)
    assert len(items) == 1
    # Both keyword candidates carry distinct entry_ids (regression for the P2 multivalue bug).
    entry_ids = sorted(c.entry_id for c in items[0].candidates)
    assert len(set(entry_ids)) == 2
    assert all(eid > 0 for eid in entry_ids)


def test_build_review_queue_empty_for_missing_plan(tmp_path: Path, tmp_db: Path) -> None:
    """The TUI never errors when there's no active plan — it just shows an empty queue."""
    items = build_review_queue(tmp_path / "does_not_exist.json", db_path=tmp_db)
    assert items == []


def test_build_review_queue_preserves_status_from_plan(tmp_path: Path, tmp_db: Path) -> None:
    plan_path = tmp_path / "plan.json"
    _write_plan(
        plan_path,
        [
            _entry(
                path="/lib/a.wav", filename="a.wav", field="description", proposed_value="X", review_status="approved"
            ),
            _entry(path="/lib/a.wav", filename="a.wav", field="keyword", proposed_value="Y", review_status="rejected"),
        ],
    )

    items = build_review_queue(plan_path, db_path=tmp_db)
    statuses = {c.field: c.status for c in items[0].candidates}
    assert statuses == {"description": "approved", "keyword": "rejected"}


# -- Build the actual Textual Screen (smoke test — requires the `tui` extra) -


def test_build_metadata_review_screen_is_constructible(tmp_path: Path, tmp_db: Path) -> None:
    """If Textual is installed, the screen class assembles without error.

    Without the ``tui`` extra this test is a no-op (import error → skip).
    """
    import importlib.util

    if importlib.util.find_spec("textual") is None:
        import pytest

        pytest.skip("Textual is not installed; install the `tui` extra to exercise this test.")

    from sfxworkbench.tui_screens.metadata_review import build_metadata_review_screen

    screen = build_metadata_review_screen(tmp_path / "missing_plan.json", db_path=tmp_db)
    assert hasattr(screen, "review_state")
    # Bindings include the documented keys.
    binding_keys = {b.key for b in screen.BINDINGS}
    assert {"a", "r", "s", "n", "q"} <= binding_keys
