"""Two-pane metadata-review screen inspired by MusicBrainz Picard.

Left pane: list of files awaiting tag review (loaded from the active tag plan).
Right pane: per-field candidate values plus read-only metadata context for the
currently-selected file, with confidence + source + whether the value differs
from what's already on disk.

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

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sfxworkbench.db import DEFAULT_DB_PATH, get_connection

if TYPE_CHECKING:
    # Only imported at type-check time so the module loads without the `tui` extra.
    from textual.screen import Screen


# ---------------------------------------------------------------------------
# Pure data layer — testable without Textual installed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileReviewItem:
    """One file's worth of pending tag candidates for the review queue.

    The triage counts (``embedded_count`` / ``accepted_count`` /
    ``source_summary``) are populated once when the queue is built, so the
    left pane can render them without re-querying the DB on every row.
    """

    path: str
    filename: str
    candidates: tuple[TagCandidate, ...]
    embedded_count: int = 0
    accepted_count: int = 0
    source_summary: str = ""


@dataclass(frozen=True)
class MetadataContextRow:
    """One non-editable metadata value shown beside planned review candidates."""

    origin: str
    field: str
    value: str
    source: str = ""
    status: str = ""
    confidence: float | None = None


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


_SEARCH_FIELD_RANKS = {
    "description": 0,
    "icmt": 1,
    "keywords": 2,
    "ikey": 3,
    "title": 4,
    "inam": 5,
    "category": 6,
    "ignr": 7,
    "subcategory": 8,
    "isbj": 9,
    "ucs_category": 10,
    "ucs_subcategory": 11,
}


def _clean_review_value(value: object) -> str:
    text = str(value or "")
    return " ".join(text.replace("\r", " ").replace("\n", " ").replace("\t", " ").split()).strip()


def _field_rank(field: str) -> tuple[int, str]:
    return (_SEARCH_FIELD_RANKS.get(field.casefold(), 50), field.casefold())


def _metadata_context_rows_from_db(
    path: str, db_path: Path, *, conn: object | None = None
) -> tuple[MetadataContextRow, ...]:
    """Return embedded, accepted, and technical metadata rows for one file."""
    owns_conn = conn is None
    if conn is None:
        conn = get_connection(db_path)
    try:
        file_row = conn.execute(
            """
            SELECT id, sample_rate, bit_depth, channels, duration_s, subtype,
                   has_bext, has_ixml, has_riff_info, has_adm, has_cue_markers,
                   has_sampler, md5, scan_error
            FROM files
            WHERE path = ?
            """,
            (path,),
        ).fetchone()
        if file_row is None:
            return ()
        file_id = int(file_row["id"])
        embedded_rows = conn.execute(
            """
            SELECT namespace, key, value, source
            FROM metadata_fields
            WHERE file_id = ?
              AND value IS NOT NULL
              AND TRIM(value) != ''
            ORDER BY namespace, key, value, source
            """,
            (file_id,),
        ).fetchall()
        accepted_rows = conn.execute(
            """
            SELECT field, value, source, confidence
            FROM accepted_tags
            WHERE file_id = ?
              AND value IS NOT NULL
              AND TRIM(value) != ''
            ORDER BY field, value, source
            """,
            (file_id,),
        ).fetchall()
    finally:
        if owns_conn:
            conn.close()

    rows: list[MetadataContextRow] = []
    for row in embedded_rows:
        key = str(row["key"])
        namespace = str(row["namespace"] or "")
        rows.append(
            MetadataContextRow(
                origin="embedded",
                field=f"{namespace}:{key}" if namespace else key,
                value=_clean_review_value(row["value"]),
                source=str(row["source"] or ""),
                status="current",
            )
        )
    for row in accepted_rows:
        confidence = row["confidence"]
        rows.append(
            MetadataContextRow(
                origin="accepted",
                field=str(row["field"]),
                value=_clean_review_value(row["value"]),
                source=str(row["source"] or ""),
                status="applied",
                confidence=float(confidence) if isinstance(confidence, int | float) else None,
            )
        )

    technical_values = (
        ("sample_rate", file_row["sample_rate"]),
        ("bit_depth", file_row["bit_depth"]),
        ("channels", file_row["channels"]),
        ("duration_s", f"{float(file_row['duration_s']):.2f}" if file_row["duration_s"] is not None else None),
        ("subtype", file_row["subtype"]),
        ("has_bext", bool(file_row["has_bext"])),
        ("has_ixml", bool(file_row["has_ixml"])),
        ("has_riff_info", bool(file_row["has_riff_info"])),
        ("has_adm", bool(file_row["has_adm"])),
        ("has_cue_markers", bool(file_row["has_cue_markers"])),
        ("has_sampler", bool(file_row["has_sampler"])),
        ("md5", file_row["md5"]),
        ("scan_error", file_row["scan_error"]),
    )
    for field, value in technical_values:
        if value is None or value == "":
            continue
        rows.append(
            MetadataContextRow(
                origin="technical",
                field=field,
                value="yes" if value is True else "no" if value is False else str(value),
                source="index",
                status="indexed",
            )
        )

    return tuple(
        sorted(
            rows,
            key=lambda row: (
                {"embedded": 0, "accepted": 1, "technical": 2}.get(row.origin, 9),
                _field_rank(row.field.split(":", 1)[-1]),
                row.value.casefold(),
            ),
        )
    )


def build_metadata_context(
    path: str, db_path: Path = DEFAULT_DB_PATH, *, conn: object | None = None
) -> tuple[MetadataContextRow, ...]:
    """Return non-editable context rows for the metadata review right pane."""
    try:
        return _metadata_context_rows_from_db(path, db_path, conn=conn)
    except Exception:
        return ()


def _existing_tag_items_by_path(paths: tuple[str, ...], db_path: Path) -> dict[str, tuple]:
    from sfxworkbench.tui_data import TagDisplayItem, _clean_tag_value

    if not paths:
        return {}
    conn = get_connection(db_path)
    try:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _review_paths (path TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM _review_paths")
        conn.executemany("INSERT OR IGNORE INTO _review_paths (path) VALUES (?)", ((path,) for path in paths))
        file_rows = conn.execute(
            """
            SELECT f.id, f.path
            FROM files f
            JOIN _review_paths rp ON rp.path = f.path
            """
        ).fetchall()
        path_by_id = {int(row["id"]): str(row["path"]) for row in file_rows}
        existing_lists: dict[str, list[TagDisplayItem]] = {path: [] for path in path_by_id.values()}
        file_ids = tuple(path_by_id)
        if not file_ids:
            return {path: tuple(items) for path, items in existing_lists.items()}
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _review_file_ids (file_id INTEGER PRIMARY KEY)")
        conn.execute("DELETE FROM _review_file_ids")
        conn.executemany("INSERT OR IGNORE INTO _review_file_ids (file_id) VALUES (?)", ((fid,) for fid in file_ids))
        for item in conn.execute(
            """
            SELECT mf.file_id, mf.namespace, mf.key, mf.value
            FROM metadata_fields mf
            JOIN _review_file_ids rf ON rf.file_id = mf.file_id
            WHERE mf.value IS NOT NULL AND TRIM(mf.value) != ''
              AND (
                  lower(mf.key) IN ('description', 'comment', 'keywords', 'title', 'category', 'subcategory')
                  OR mf.key IN ('ICMT', 'IKEY', 'INAM', 'IGNR', 'ISBJ')
              )
            """
        ):
            existing_lists.setdefault(path_by_id[int(item["file_id"])], []).append(
                TagDisplayItem(
                    source="file",
                    field=str(item["key"]),
                    value=_clean_tag_value(item["value"]),
                )
            )
        for item in conn.execute(
            """
            SELECT t.file_id, t.field, t.value, t.source
            FROM accepted_tags t
            JOIN _review_file_ids rf ON rf.file_id = t.file_id
            WHERE t.value IS NOT NULL AND TRIM(t.value) != ''
            """
        ):
            existing_lists.setdefault(path_by_id[int(item["file_id"])], []).append(
                TagDisplayItem(
                    source="db",
                    field=str(item["field"]),
                    value=_clean_tag_value(item["value"]),
                    evidence_source=str(item["source"] or ""),
                )
            )
        return {path: tuple(items) for path, items in existing_lists.items()}
    finally:
        conn.close()


def build_review_queue(
    plan_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    query: str = "",
    limit: int | None = None,
    offset: int = 0,
    pending_only: bool = False,
    random_pending: bool = False,
) -> list[FileReviewItem]:
    """Group the active plan's add-action entries into per-file review items.

    Uses the same cached SQLite plan-entry adapter as the Metadata values pane
    so large plans can be paged and old plans without explicit ``entry_id``
    values still produce reviewable entries. Missing or malformed plan files
    produce an empty queue rather than raising, matching the TUI's other "no
    plan loaded" code paths.
    """
    from sfxworkbench.tui_data import (
        TagDisplayItem,
        _clean_tag_value,
        _is_duplicate_tag_item,
        _like_filter_clause,
        _metadata_plan_index,
        _tag_field_rank,
    )

    index = _metadata_plan_index(plan_path)
    if index is None:
        return []

    like_sql, params = _like_filter_clause(("filename", "path"), query)
    path_params: tuple = params
    if limit is not None:
        order_sql = "RANDOM()" if random_pending else "path"
        having_sql = "HAVING SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) > 0" if pending_only else ""
        page_rows = index.execute(
            f"""
            SELECT path
            FROM plan_entries
            WHERE action = 'add' {like_sql}
            GROUP BY path
            {having_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            params + (max(0, limit), max(0, offset)),
        ).fetchall()
        paths = tuple(str(row["path"]) for row in page_rows)
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        rows = index.execute(
            f"""
            SELECT *
            FROM plan_entries
            WHERE action = 'add'
              AND path IN ({placeholders})
            ORDER BY path, entry_id
            """,
            paths,
        ).fetchall()
    else:
        rows = index.execute(
            f"""
            SELECT *
            FROM plan_entries
            WHERE action = 'add' {like_sql}
            ORDER BY path, entry_id
            """,
            path_params,
        ).fetchall()
        paths = tuple(sorted({str(row["path"]) for row in rows}))

    existing_by_path = _existing_tag_items_by_path(paths, db_path)
    by_path: dict[str, list[TagCandidate]] = {}
    filenames: dict[str, str] = {}
    for raw in rows:
        path = str(raw["path"]).strip()
        field = str(raw["field"] or "").strip()
        proposed_value = _clean_tag_value(raw["proposed_value"])
        if not path or not field or not proposed_value:
            continue
        status = str(raw["status"] or "pending")
        source = str(raw["source"] or "").strip()
        if _is_duplicate_tag_item(
            TagDisplayItem(source="plan", field=field, value=proposed_value, status=status, evidence_source=source),
            existing_by_path.get(path, ()),
        ):
            continue
        filenames[path] = str(raw["filename"] or Path(path).name)
        confidence = raw["confidence"]
        by_path.setdefault(path, []).append(
            TagCandidate(
                entry_id=int(raw["entry_id"]),
                field=field,
                proposed_value=proposed_value,
                current_value=_clean_tag_value(raw["existing_value"]) or None,
                source=source,
                confidence=float(confidence) if isinstance(confidence, int | float) else 0.0,
                status=status,
            )
        )
    items: list[FileReviewItem] = []
    for path, candidates in by_path.items():
        sorted_candidates = tuple(
            sorted(candidates, key=lambda candidate: (candidate.status != "pending", _tag_field_rank(candidate.field)))
        )
        existing_items = existing_by_path.get(path, ())
        embedded_count = sum(1 for item in existing_items if item.source == "file")
        accepted_count = sum(1 for item in existing_items if item.source == "db")
        unique_sources = {candidate.source for candidate in candidates if candidate.source}
        source_summary = ", ".join(sorted(unique_sources))
        items.append(
            FileReviewItem(
                path=path,
                filename=filenames.get(path, Path(path).name),
                candidates=sorted_candidates,
                embedded_count=embedded_count,
                accepted_count=accepted_count,
                source_summary=source_summary,
            )
        )
    return sorted(
        items,
        key=lambda item: (
            not any(candidate.status == "pending" for candidate in item.candidates),
            item.filename.casefold(),
            item.path.casefold(),
        ),
    )


def skip_status_transition(previous_status: str) -> tuple[str, str] | None:
    """Return the counter transition for skipping one candidate, if any.

    Skip is intentionally a no-op for candidates that were already approved,
    rejected, or skipped. That keeps the left-pane counters aligned with the
    effective in-memory review state.
    """
    return ("pending", "skipped") if previous_status == "pending" else None


# ---------------------------------------------------------------------------
# Textual Screen — only constructed when the TUI is actually running
# ---------------------------------------------------------------------------


def build_metadata_review_screen(plan_path: Path, *, db_path: Path = DEFAULT_DB_PATH) -> Screen:
    """Construct and return a ``MetadataReviewScreen`` instance.

    Defined as a factory rather than a module-level class so that importing
    this module does not require Textual to be installed (the helper data
    types above stay usable in unit tests with no ``tui`` extra).
    """
    from rich.text import Text
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import Screen
    from textual.widgets import Button, DataTable, Footer, Header, Input, Static

    from sfxworkbench.tui_app import _state_token
    from sfxworkbench.tui_text import _tag_text

    class MetadataReviewScreen(Screen):
        POPUP_KEY = "metadata-review"

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
        MetadataReviewScreen .note { color: #9fb0c1; margin-bottom: 1; }
        """
        if sys.platform == "win32":
            DEFAULT_CSS += """
        MetadataReviewScreen VerticalScroll,
        MetadataReviewScreen DataTable {
            scrollbar-visibility: hidden;
        }
        """

        def __init__(self) -> None:
            super().__init__()
            self.items: list[FileReviewItem] = []
            self.file_cursor: int = 0
            self.candidate_cursor: int = 0
            self._page_size = 100
            self._offset = 0
            self._random_pending = False
            # Keyed by ``(path, field, value)`` so multivalue candidates on the
            # same field are reviewed independently. Fixes the P2 bug where
            # two ``keyword`` candidates on one file would flip together.
            self._approvals: dict[tuple[str, str, str], str] = {}
            self._decision_entry_ids: dict[int, str] = {}
            # Cache of (pending, approved, rejected) per path. On a real-world
            # plan with tens of thousands of files, the previous behavior
            # recomputed all counts and rebuilt the whole left table on every
            # approve/reject keystroke — multi-second lag per press. With the
            # cache + ``_refresh_file_row`` we only touch the changed row.
            self._counts_by_path: dict[str, list[int]] = {}
            # Path → row index in the files DataTable. Same purpose: surgical
            # cell updates instead of a full ``table.clear(); add_row x N``.
            self._row_index_by_path: dict[str, int] = {}
            # Filter state shared between the filter bar inputs and
            # ``_item_passes_filters``. Empty string means "no filter".
            self._filter_status = ""
            self._filter_field = ""
            self._filter_source = ""
            # Ordinals of ``self.items`` that survive the active filters.
            # Used by header-click sorting to keep the visible/items mapping
            # straight when a row is approved/rejected.
            self._visible_row_indices: list[int] = []
            # ``(column_index, reverse)``; column_index < 0 means unsorted.
            self._files_sort: tuple[int, bool] = (-1, False)
            self._candidates_sort: tuple[int, bool] = (-1, False)
            # Read-only context is DB-backed and does not change while this
            # screen is open, so cache it per file to keep approve/reject
            # keystrokes local to the table state.
            self._context_by_path: dict[str, tuple[MetadataContextRow, ...]] = {}
            # Single shared debounce timer for the three filter inputs so a
            # burst of keystrokes triggers one ``_refresh_files`` rebuild
            # instead of one per character.
            self._filter_debounce_timer = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with Horizontal():
                with Vertical(id="review-files-pane"):
                    yield Static("Metadata Values - Pending Files", classes="pane-title")
                    with Horizontal():
                        yield Button("Previous 100", id="review-page-prev")
                        yield Button("Next 100", id="review-page-next")
                        yield Button("Random Pending", id="review-page-random")
                    with Horizontal(id="review-filter-bar"):
                        yield Input(
                            placeholder="Status: pending / approved / rejected",
                            id="review-filter-status",
                        )
                        yield Input(
                            placeholder="Field (substring match)",
                            id="review-filter-field",
                        )
                        yield Input(
                            placeholder="Source (substring match)",
                            id="review-filter-source",
                        )
                    yield Static(
                        "Source symbols: # filename  / path  ~ group  ^ UCS catalog/stem  * synonym",
                        classes="note",
                    )
                    yield DataTable(id="review-files-table", cursor_type="row")
                with VerticalScroll(id="review-candidates-pane"):
                    yield Static("Selected Metadata Values", classes="pane-title")
                    yield DataTable(id="review-candidates-table", cursor_type="row")
            yield Footer()

        def on_mount(self) -> None:
            self._load_page()
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

        def _load_page(self) -> None:
            self.items = build_review_queue(
                plan_path,
                db_path=db_path,
                limit=self._page_size,
                offset=self._offset,
                pending_only=True,
                random_pending=self._random_pending,
            )
            self.file_cursor = 0
            self.candidate_cursor = 0
            self._counts_by_path.clear()
            self._row_index_by_path.clear()
            # Pre-warm the context cache for every file in the page using one
            # shared connection. Arrow-key navigation hits ``_refresh_candidates``
            # which used to call ``build_metadata_context`` on first selection
            # — that opened a fresh connection and ran 3 queries per file.
            self._context_by_path = {}
            if self.items:
                conn = get_connection(db_path)
                try:
                    for item in self.items:
                        self._context_by_path[item.path] = build_metadata_context(item.path, db_path=db_path, conn=conn)
                finally:
                    conn.close()

        def _candidate_text(self, candidate: TagCandidate, status: str) -> Text:
            return _tag_text(candidate.proposed_value, candidate.field, status=status, source=candidate.source)

        def _item_state(self, item: FileReviewItem) -> Text:
            pending = approved = rejected = 0
            for candidate in item.candidates:
                status = self._effective_status(item.path, candidate)
                if status == "pending":
                    pending += 1
                elif status == "approved":
                    approved += 1
                elif status == "rejected":
                    rejected += 1
            if pending:
                return _state_token("pending")
            if approved:
                return _state_token("accepted")
            if rejected:
                return _state_token("rejected")
            return _state_token("info")

        def _item_tags(self, item: FileReviewItem) -> Text:
            text = Text()
            for index, candidate in enumerate(item.candidates[:8]):
                if index:
                    text.append("  |  ", style="dim")
                text.append_text(self._candidate_text(candidate, self._effective_status(item.path, candidate)))
            return text or Text("No reviewable tags", style="dim")

        def _item_passes_filters(self, item: FileReviewItem) -> bool:
            """Apply the filter-bar inputs against one file's candidates.

            A file passes when *any* of its candidates matches every active
            filter. Empty filters are always satisfied. Match is case-folded
            substring on the candidate field/value/source.
            """
            status_filter = self._filter_status.strip().casefold()
            field_filter = self._filter_field.strip().casefold()
            source_filter = self._filter_source.strip().casefold()
            if not (status_filter or field_filter or source_filter):
                return True
            for candidate in item.candidates:
                if status_filter and self._effective_status(item.path, candidate).casefold() != status_filter:
                    continue
                if field_filter and field_filter not in candidate.field.casefold():
                    continue
                if source_filter and source_filter not in candidate.source.casefold():
                    continue
                return True
            return False

        # Column layout for the left files pane. Order matches the doc's
        # recommended triage layout (state → filename → counts → context).
        FILES_COLUMNS = (
            "State",
            "Filename",
            "Pending",
            "Approved",
            "Rejected",
            "Embedded",
            "Accepted",
            "Sources",
            "Path",
        )

        def _file_row_cells(self, item: FileReviewItem, counts: list[int]) -> tuple:
            pending, approved, rejected = counts
            return (
                self._item_state(item),
                item.filename,
                str(pending),
                str(approved),
                str(rejected),
                str(item.embedded_count),
                str(item.accepted_count),
                item.source_summary or "—",
                item.path,
            )

        def _sorted_items_for_display(self) -> list[FileReviewItem]:
            """Apply the active files-table sort to a copy of ``self.items``."""
            column_index, reverse = self._files_sort
            if column_index < 0:
                return list(self.items)

            def pending_count(item: FileReviewItem) -> int:
                return sum(1 for c in item.candidates if self._effective_status(item.path, c) == "pending")

            def approved_count(item: FileReviewItem) -> int:
                return sum(1 for c in item.candidates if self._effective_status(item.path, c) == "approved")

            def rejected_count(item: FileReviewItem) -> int:
                return sum(1 for c in item.candidates if self._effective_status(item.path, c) == "rejected")

            def state_rank(item: FileReviewItem) -> int:
                statuses = {self._effective_status(item.path, c) for c in item.candidates}
                if "pending" in statuses:
                    return 0
                if "approved" in statuses:
                    return 1
                if "rejected" in statuses:
                    return 2
                return 3

            keyfuncs = {
                0: state_rank,
                1: lambda i: i.filename.casefold(),
                2: pending_count,
                3: approved_count,
                4: rejected_count,
                5: lambda i: i.embedded_count,
                6: lambda i: i.accepted_count,
                7: lambda i: i.source_summary.casefold(),
                8: lambda i: i.path.casefold(),
            }
            keyfunc = keyfuncs.get(column_index)
            if keyfunc is None:
                return list(self.items)
            return sorted(self.items, key=keyfunc, reverse=reverse)

        def _sorted_candidates_for_display(self, item: FileReviewItem) -> list[TagCandidate]:
            column_index, reverse = self._candidates_sort
            if column_index < 0:
                return list(item.candidates)
            from sfxworkbench.tui_data import _tag_field_rank as _rank

            keyfuncs = {
                0: lambda c: self._effective_status(item.path, c),
                1: lambda c: _rank(c.field),
                2: lambda c: c.proposed_value.casefold(),
                3: lambda c: (c.current_value or "").casefold(),
                4: lambda c: c.diff_marker,
                5: lambda c: c.confidence,
            }
            keyfunc = keyfuncs.get(column_index)
            if keyfunc is None:
                return list(item.candidates)
            return sorted(item.candidates, key=keyfunc, reverse=reverse)

        def _refresh_files(self) -> None:
            """Build the left files table from scratch.

            Populates ``_counts_by_path`` and ``_row_index_by_path`` so
            subsequent approve/reject can update a single row via
            ``_refresh_file_row`` rather than rebuilding everything.
            """
            table = self.query_one("#review-files-table", DataTable)
            table.clear(columns=True)
            table.add_columns(*self.FILES_COLUMNS)
            self._counts_by_path.clear()
            self._row_index_by_path.clear()
            self._visible_row_indices = []
            if not self.items:
                table.add_row(_state_token("info"), f"No pending tag suggestions in {plan_path.name}", *(["—"] * 7))
                return
            built: list[tuple] = []
            for item in self._sorted_items_for_display():
                if not self._item_passes_filters(item):
                    continue
                pending = approved = rejected = 0
                for candidate in item.candidates:
                    status = self._effective_status(item.path, candidate)
                    if status == "pending":
                        pending += 1
                    elif status == "approved":
                        approved += 1
                    elif status == "rejected":
                        rejected += 1
                counts = [pending, approved, rejected]
                visible_index = len(built)
                self._counts_by_path[item.path] = counts
                self._row_index_by_path[item.path] = visible_index
                self._visible_row_indices.append(self.items.index(item))
                built.append(self._file_row_cells(item, counts))
            if built:
                # One reactive update for the whole batch beats N row mutations
                # at 100+ row scale.
                table.add_rows(built)
            else:
                table.add_row(_state_token("info"), "No rows match the active filters.", *(["—"] * 7))

        def _refresh_file_row(self, path: str, previous_status: str, new_status: str) -> None:
            """Update a single file row's count cells in place.

            Replaces the previous "rebuild every row on every keystroke"
            approach that took multi-second hits on 30k+-file plans.
            """
            counts = self._counts_by_path.get(path)
            row_index = self._row_index_by_path.get(path)
            if counts is None or row_index is None:
                # Fallback: a row we don't have cached — full rebuild.
                self._refresh_files()
                return
            # Adjust the counter buckets by the status transition.
            _status_index = {"pending": 0, "approved": 1, "rejected": 2}
            if previous_status in _status_index:
                counts[_status_index[previous_status]] = max(0, counts[_status_index[previous_status]] - 1)
            if new_status in _status_index:
                counts[_status_index[new_status]] += 1
            from textual.coordinate import Coordinate

            table = self.query_one("#review-files-table", DataTable)
            try:
                item = next((candidate_item for candidate_item in self.items if candidate_item.path == path), None)
                if item is None:
                    self._refresh_files()
                    return
                cells = self._file_row_cells(item, counts)
                # state / pending / approved / rejected can flip after a vote;
                # filename / embedded / accepted / sources / path don't.
                table.update_cell_at(Coordinate(row_index, 0), cells[0])
                table.update_cell_at(Coordinate(row_index, 2), cells[2])
                table.update_cell_at(Coordinate(row_index, 3), cells[3])
                table.update_cell_at(Coordinate(row_index, 4), cells[4])
            except Exception:
                # If Textual's coordinate addressing fails for any reason,
                # fall back to the full rebuild — slow but correct.
                self._refresh_files()

        def _refresh_candidates(self) -> None:
            table = self.query_one("#review-candidates-table", DataTable)
            table.clear(columns=True)
            table.add_columns("State", "Field", "Value", "Current", "Diff", "Conf")
            current = self._current_file()
            if current is None:
                table.add_row(_state_token("info"), "", "No pending tag suggestions", "", "", "")
                return
            built: list[tuple] = []
            for candidate in self._sorted_candidates_for_display(current):
                status = self._effective_status(current.path, candidate)
                built.append(
                    (
                        _state_token(status),
                        candidate.field,
                        self._candidate_text(candidate, status),
                        candidate.current_value or "",
                        candidate.diff_marker,
                        f"{candidate.confidence:.2f}",
                    )
                )
            # Contexts are pre-warmed by ``_load_page``; fall back to a fresh
            # build only if the file isn't in the page (defensive).
            context_rows = self._context_by_path.get(current.path)
            if context_rows is None:
                context_rows = build_metadata_context(current.path, db_path=db_path)
                self._context_by_path[current.path] = context_rows
            for row in context_rows:
                built.append(
                    (
                        _state_token("accepted" if row.origin == "accepted" else "info"),
                        row.field,
                        row.value,
                        "",
                        "",
                        "" if row.confidence is None else f"{row.confidence:.2f}",
                    )
                )
            if built:
                # One reactive update for the whole batch beats ~60 mutations
                # on every arrow-key navigation.
                table.add_rows(built)

        def _approval_key(self, path: str, candidate: TagCandidate) -> tuple[str, str, str]:
            return (path, candidate.field, candidate.proposed_value)

        def _effective_status(self, path: str, candidate: TagCandidate) -> str:
            return self._decision_entry_ids.get(
                candidate.entry_id,
                self._approvals.get(self._approval_key(path, candidate), candidate.status),
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "review-page-prev":
                self.action_previous_page()
            elif event.button.id == "review-page-next":
                self.action_next_page()
            elif event.button.id == "review-page-random":
                self.action_random_page()

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "review-files-table":
                self._select_file(event.cursor_row)
            elif event.data_table.id == "review-candidates-table":
                self._select_candidate(event.cursor_row)

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            if event.data_table.id == "review-files-table":
                self._select_file(event.cursor_row)
            elif event.data_table.id == "review-candidates-table":
                self._select_candidate(event.cursor_row)

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "review-filter-status":
                self._filter_status = event.value
            elif event.input.id == "review-filter-field":
                self._filter_field = event.value
            elif event.input.id == "review-filter-source":
                self._filter_source = event.value
            else:
                return
            if self._filter_debounce_timer is not None:
                self._filter_debounce_timer.stop()
            # 150ms is short enough that the rebuild feels live but long
            # enough that a typing burst collapses to one rebuild.
            self._filter_debounce_timer = self.set_timer(0.15, self._refresh_files)

        def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
            column_index = int(getattr(event, "column_index", -1))
            if column_index < 0:
                return
            if event.data_table.id == "review-files-table":
                prev_column, prev_reverse = self._files_sort
                reverse = (not prev_reverse) if prev_column == column_index else False
                self._files_sort = (column_index, reverse)
                self._refresh_files()
            elif event.data_table.id == "review-candidates-table":
                prev_column, prev_reverse = self._candidates_sort
                reverse = (not prev_reverse) if prev_column == column_index else False
                self._candidates_sort = (column_index, reverse)
                self._refresh_candidates()

        def _select_file(self, row_index: int) -> None:
            if row_index < 0 or row_index >= len(self.items):
                return
            self.file_cursor = row_index
            self.candidate_cursor = 0
            self._refresh_candidates()

        def _select_candidate(self, row_index: int) -> None:
            current = self._current_file()
            if current is None or row_index < 0 or row_index >= len(current.candidates):
                return
            self.candidate_cursor = row_index

        # -- actions ----------------------------------------------------------

        def action_approve(self) -> None:
            current = self._current_file()
            candidate = self._current_candidate()
            if current is None or candidate is None:
                return
            previous_status = self._effective_status(current.path, candidate)
            self._approvals[self._approval_key(current.path, candidate)] = "approved"
            self._decision_entry_ids[candidate.entry_id] = "approved"
            self._refresh_file_row(current.path, previous_status, "approved")
            self._refresh_candidates()

        def action_reject(self) -> None:
            current = self._current_file()
            candidate = self._current_candidate()
            if current is None or candidate is None:
                return
            previous_status = self._effective_status(current.path, candidate)
            self._approvals[self._approval_key(current.path, candidate)] = "rejected"
            self._decision_entry_ids[candidate.entry_id] = "rejected"
            self._refresh_file_row(current.path, previous_status, "rejected")
            self._refresh_candidates()

        def action_skip(self) -> None:
            current = self._current_file()
            if current is None:
                return
            # Track only candidates whose status actually transitions to
            # "skipped" so the counter delta is accurate.
            transitions: list[tuple[str, str]] = []
            for candidate in current.candidates:
                key = self._approval_key(current.path, candidate)
                previous = self._approvals.get(key, candidate.status)
                transition = skip_status_transition(previous)
                if transition is None:
                    continue
                self._approvals[key] = "skipped"
                self._decision_entry_ids[candidate.entry_id] = "skipped"
                transitions.append(transition)
            for previous_status, new_status in transitions:
                self._refresh_file_row(current.path, previous_status, new_status)
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

        def action_previous_page(self) -> None:
            self._random_pending = False
            self._offset = max(0, self._offset - self._page_size)
            self._load_page()
            self._refresh_files()
            self._refresh_candidates()

        def action_next_page(self) -> None:
            self._random_pending = False
            self._offset += self._page_size
            self._load_page()
            self._refresh_files()
            self._refresh_candidates()

        def action_random_page(self) -> None:
            self._random_pending = True
            self._offset = 0
            self._load_page()
            self._refresh_files()
            self._refresh_candidates()

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
            for entry_id, status in self._decision_entry_ids.items():
                if status == "approved":
                    approved.append(entry_id)
                elif status == "rejected":
                    rejected.append(entry_id)
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
