"""Two-pane metadata-review screen inspired by MusicBrainz Picard.

Left pane: list of files awaiting tag review (loaded from the active tag plan).
Right pane: per-field candidate values for the currently-selected file, with
confidence + the source the candidate came from + an indication of whether
the value differs from what's already on disk.

Key bindings (screen-level so each screen owns its bindings, not the app):

    a  approve the current candidate
    r  reject the current candidate
    s  skip the current file
    n  move to the next file in the queue
    j  cursor down (vim convention)
    k  cursor up
    q  pop the screen back to wherever it was pushed from

Textual is loaded lazily inside the importer ``build_metadata_review_screen``
so this module imports cleanly even when the ``tui`` optional extra is not
installed — handy for unit tests that exercise the pure helpers below.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sfxworkbench.db import DEFAULT_DB_PATH

if TYPE_CHECKING:
    # Only imported at type-check time so the module loads without the `tui` extra.
    from textual.screen import Screen


# ---------------------------------------------------------------------------
# Pure data layer — testable without Textual installed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileReviewItem:
    """One file's worth of pending tag candidates for the review queue."""

    path: str
    filename: str
    candidates: tuple[TagCandidate, ...]


@dataclass(frozen=True)
class TagCandidate:
    """One per-field candidate value the reviewer can accept / reject / skip.

    The ``entry_id`` ties the in-memory candidate back to its row in the source
    plan JSON so decisions can be persisted via :func:`review_tag_plan`. For
    multivalue fields like ``keyword``, multiple candidates can share the same
    ``field`` but never the same ``(field, value)``, which is why the
    decision key in :class:`MetadataReviewScreen` is the full triple.
    """

    entry_id: int
    field: str
    proposed_value: str
    current_value: str | None
    source: str
    confidence: float
    status: str = "pending"  # "pending" | "approved" | "rejected" | "skipped"

    @property
    def diff_marker(self) -> str:
        """A short label describing how *proposed_value* relates to *current_value*."""
        if self.current_value is None or not str(self.current_value).strip():
            return "new"
        if self.current_value.strip() == self.proposed_value.strip():
            return "same"
        return "change"


def build_review_queue(plan_path: Path, db_path: Path = DEFAULT_DB_PATH) -> list[FileReviewItem]:
    """Group the active plan's add-action entries into per-file review items.

    Reads ``plan_path`` directly (rather than going through
    ``metadata_tag_change_rows``) so each candidate can carry its ``entry_id``
    — required for persisting approve/reject decisions back to the plan via
    :func:`sfxworkbench.tag_plan.review_tag_plan`. Missing or malformed plan
    files produce an empty queue rather than raising, matching the TUI's
    other "no plan loaded" code paths.
    """
    if not plan_path.exists():
        return []
    try:
        payload = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    by_path: dict[str, list[TagCandidate]] = {}
    filenames: dict[str, str] = {}
    for raw in payload.get("entries", []):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("action", "add")).strip() != "add":
            continue
        path = str(raw.get("path", "")).strip()
        if not path:
            continue
        entry_id = raw.get("entry_id")
        if not isinstance(entry_id, int):
            continue
        filenames[path] = str(raw.get("filename", "") or Path(path).name)
        existing_values = raw.get("existing_values") or []
        current_value = str(existing_values[0]) if existing_values else None
        confidence = raw.get("confidence")
        confidence_float = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        by_path.setdefault(path, []).append(
            TagCandidate(
                entry_id=entry_id,
                field=str(raw.get("field", "")).strip(),
                proposed_value=str(raw.get("proposed_value", "")).strip(),
                current_value=current_value,
                source=str(raw.get("source", "")).strip(),
                confidence=confidence_float,
                status=str(raw.get("review_status", "pending")).strip() or "pending",
            )
        )
    items: list[FileReviewItem] = []
    for path, candidates in by_path.items():
        items.append(
            FileReviewItem(path=path, filename=filenames.get(path, Path(path).name), candidates=tuple(candidates))
        )
    return items


# ---------------------------------------------------------------------------
# Textual Screen — only constructed when the TUI is actually running
# ---------------------------------------------------------------------------


def build_metadata_review_screen(plan_path: Path, *, db_path: Path = DEFAULT_DB_PATH) -> Screen:
    """Construct and return a ``MetadataReviewScreen`` instance.

    Defined as a factory rather than a module-level class so that importing
    this module does not require Textual to be installed (the helper data
    types above stay usable in unit tests with no ``tui`` extra).
    """
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import Screen
    from textual.widgets import DataTable, Footer, Header, Static

    class MetadataReviewScreen(Screen):
        # NOTE: the type is intentionally not re-annotated; we inherit Textual's
        # broader ``list[Binding | tuple[str, str] | tuple[str, str, str]]``
        # so mypy's invariance check on ``list`` is satisfied.
        BINDINGS = [
            Binding("a", "approve", "Approve"),
            Binding("r", "reject", "Reject"),
            Binding("s", "skip", "Skip file"),
            Binding("n", "next_file", "Next file"),
            Binding("j", "cursor_down", "Cursor down", show=False),
            Binding("k", "cursor_up", "Cursor up", show=False),
            # `q` persists decisions back to the source plan before popping.
            # Skipped entries are intentionally left unchanged.
            Binding("q", "persist_and_back", "Save & back"),
        ]

        DEFAULT_CSS = """
        MetadataReviewScreen Horizontal { height: 1fr; }
        MetadataReviewScreen #review-files-pane { width: 40%; }
        MetadataReviewScreen #review-candidates-pane { width: 60%; }
        MetadataReviewScreen .pane-title { background: $primary; color: $background; padding: 0 1; }
        """

        def __init__(self) -> None:
            super().__init__()
            self.items: list[FileReviewItem] = []
            self.file_cursor: int = 0
            self.candidate_cursor: int = 0
            # Keyed by ``(path, field, value)`` so multivalue candidates on the
            # same field are reviewed independently. Fixes the P2 bug where
            # two ``keyword`` candidates on one file would flip together.
            self._approvals: dict[tuple[str, str, str], str] = {}

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with Horizontal():
                with Vertical(id="review-files-pane"):
                    yield Static("Files awaiting review", classes="pane-title")
                    yield DataTable(id="review-files-table", cursor_type="row")
                with VerticalScroll(id="review-candidates-pane"):
                    yield Static("Candidates", classes="pane-title")
                    yield DataTable(id="review-candidates-table", cursor_type="row")
            yield Footer()

        def on_mount(self) -> None:
            self.items = build_review_queue(plan_path, db_path=db_path)
            self._refresh_files()
            self._refresh_candidates()

        # -- internal helpers -------------------------------------------------

        def _current_file(self) -> FileReviewItem | None:
            if not self.items or self.file_cursor >= len(self.items):
                return None
            return self.items[self.file_cursor]

        def _current_candidate(self) -> TagCandidate | None:
            current = self._current_file()
            if current is None:
                return None
            if self.candidate_cursor >= len(current.candidates):
                return None
            return current.candidates[self.candidate_cursor]

        def _refresh_files(self) -> None:
            table = self.query_one("#review-files-table", DataTable)
            table.clear(columns=True)
            table.add_columns("File", "Pending", "Approved", "Rejected")
            for item in self.items:
                pending = sum(1 for c in item.candidates if self._effective_status(item.path, c) == "pending")
                approved = sum(1 for c in item.candidates if self._effective_status(item.path, c) == "approved")
                rejected = sum(1 for c in item.candidates if self._effective_status(item.path, c) == "rejected")
                table.add_row(item.filename, str(pending), str(approved), str(rejected))

        def _refresh_candidates(self) -> None:
            table = self.query_one("#review-candidates-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Field", "Proposed", "Current", "Source", "Conf", "Diff", "Status")
            current = self._current_file()
            if current is None:
                return
            for candidate in current.candidates:
                status = self._effective_status(current.path, candidate)
                table.add_row(
                    candidate.field,
                    candidate.proposed_value,
                    candidate.current_value or "",
                    candidate.source,
                    f"{candidate.confidence:.2f}",
                    candidate.diff_marker,
                    status,
                )

        def _approval_key(self, path: str, candidate: TagCandidate) -> tuple[str, str, str]:
            return (path, candidate.field, candidate.proposed_value)

        def _effective_status(self, path: str, candidate: TagCandidate) -> str:
            return self._approvals.get(self._approval_key(path, candidate), candidate.status)

        # -- actions ----------------------------------------------------------

        def action_approve(self) -> None:
            current = self._current_file()
            candidate = self._current_candidate()
            if current is None or candidate is None:
                return
            self._approvals[self._approval_key(current.path, candidate)] = "approved"
            self._refresh_files()
            self._refresh_candidates()

        def action_reject(self) -> None:
            current = self._current_file()
            candidate = self._current_candidate()
            if current is None or candidate is None:
                return
            self._approvals[self._approval_key(current.path, candidate)] = "rejected"
            self._refresh_files()
            self._refresh_candidates()

        def action_skip(self) -> None:
            current = self._current_file()
            if current is None:
                return
            for candidate in current.candidates:
                self._approvals.setdefault(self._approval_key(current.path, candidate), "skipped")
            self.action_next_file()

        def action_next_file(self) -> None:
            if self.file_cursor + 1 < len(self.items):
                self.file_cursor += 1
                self.candidate_cursor = 0
                self._refresh_candidates()
                # Move the visible cursor on the left table too.
                files_table = self.query_one("#review-files-table", DataTable)
                from textual.coordinate import Coordinate

                files_table.cursor_coordinate = Coordinate(self.file_cursor, 0)

        def action_cursor_down(self) -> None:
            current = self._current_file()
            if current is None:
                return
            if self.candidate_cursor + 1 < len(current.candidates):
                self.candidate_cursor += 1
                candidates_table = self.query_one("#review-candidates-table", DataTable)
                from textual.coordinate import Coordinate

                candidates_table.cursor_coordinate = Coordinate(self.candidate_cursor, 0)

        def action_cursor_up(self) -> None:
            if self.candidate_cursor > 0:
                self.candidate_cursor -= 1
                candidates_table = self.query_one("#review-candidates-table", DataTable)
                from textual.coordinate import Coordinate

                candidates_table.cursor_coordinate = Coordinate(self.candidate_cursor, 0)

        def action_persist_and_back(self) -> None:
            """Write approvals/rejections back to the source plan, then pop the screen.

            Persistence reuses :func:`sfxworkbench.tag_plan.review_tag_plan`,
            which mutates the plan in place by entry_id. This means a reviewed
            session survives ``sfx tui`` exit and the decisions are visible to
            ``sfx tag apply`` on the next run.
            """
            self._persist_decisions()
            self.app.pop_screen()

        def _persist_decisions(self) -> None:
            approved: list[int] = []
            rejected: list[int] = []
            for item in self.items:
                for candidate in item.candidates:
                    status = self._approvals.get(self._approval_key(item.path, candidate))
                    if status == "approved":
                        approved.append(candidate.entry_id)
                    elif status == "rejected":
                        rejected.append(candidate.entry_id)
                    # "skipped" and unset are no-ops — leave the plan untouched.
            if not approved and not rejected:
                return
            try:
                from sfxworkbench.tag_plan import review_tag_plan

                review_tag_plan(
                    plan_path,
                    entries=approved or None,
                    reject_entries=rejected or None,
                    quiet=True,
                )
            except Exception:  # pragma: no cover - defensive; surfaces via the app log
                # Persistence is best-effort: a bad plan path or a permission
                # failure shouldn't lock the user inside the screen. The TUI's
                # general action-result strip will still show stale state on
                # next refresh; future work can surface a notification here.
                pass

        # -- public introspection (used by tests) -----------------------------

        @property
        def review_state(self) -> dict[tuple[str, str, str], str]:
            """A snapshot of pending approvals/rejections, keyed by ``(path, field, value)``."""
            return dict(self._approvals)

    return MetadataReviewScreen()
