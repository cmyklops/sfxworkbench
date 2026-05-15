"""Fuzzy command-palette screen for `sfx tui`.

Press ``p`` in the main TUI to open a modal listing every button handler in
the dispatch dict. Type to filter; ``Enter`` runs the selected command. This
collapses dozens of buttons across six tabs into a single keyboard-driven
launcher, mirroring patterns from Linear / VS Code / Slack.

The screen takes the button-handler dict from the parent app (``Mapping[str,
Callable[[], None]]``) and renders the keys as filterable rows. No DB or
filesystem state is required, so the palette is testable in isolation: build
it with a fake handler dict and exercise the filter logic.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.screen import Screen


# Pretty labels for known button ids. Anything not listed falls back to a
# title-cased version of the id with dashes replaced by spaces. Keeping the
# map terse — these are visible only inside the palette, not on the buttons.
_LABELS: dict[str, str] = {
    "use-indexed-root": "Use last-indexed root as library path",
    "cancel-action": "Cancel running action",
    "refresh-all": "Refresh all views",
    "scan-run": "Quick index",
    "scan-full-audit": "Full audit",
    "files-clear-search": "Clear file search",
    "files-open-file": "Open selected file",
    "files-reveal-file": "Reveal selected file",
    "clean-preview": "Preview junk cleanup",
    "clean-apply": "Apply junk cleanup",
    "dedupe-build": "Build dedupe plan",
    "dedupe-apply": "Apply dedupe (quarantine)",
    "pack-audit": "Audit packs",
    "pack-plan": "Build pack plan",
    "pack-apply": "Apply pack plan",
    "organize-rename-preview": "Preview name cleanup",
    "organize-rename-apply": "Apply name cleanup",
    "organize-rename-undo": "Undo name cleanup",
    "organize-audit": "Preview folder cleanup",
    "organize-apply": "Apply folder cleanup",
    "organize-undo": "Undo folder cleanup",
    "organize-nesting-audit": "Find nested folders",
    "organize-nesting-plan": "Build nesting plan",
    "organize-nesting-apply": "Apply nesting plan",
    "organize-nesting-undo": "Undo nesting",
    "metadata-audit": "Metadata audit",
    "metadata-plan": "Find tags",
    "metadata-review-open": "Review metadata tags",
    "metadata-apply": "Accept tags & prepare write",
    "metadata-sidecar": "Save tags file",
    "metadata-write-apply": "Write metadata to files",
    "metadata-write-undo": "Undo metadata file writes",
    "quarantine-reveal": "Reveal quarantine folder",
    "delete-plan": "Plan permanent delete",
    "delete-apply": "Apply permanent delete",
    # Tier post-feedback: theme switching via the palette. Each handler
    # assigns to ``App.theme`` (a reactive attribute) so Textual restyles
    # the whole UI immediately. Names match Textual's built-in theme list.
    "theme-textual-dark": "Theme: Textual Dark",
    "theme-textual-light": "Theme: Textual Light",
    "theme-monokai": "Theme: Monokai",
    "theme-dracula": "Theme: Dracula",
    "theme-nord": "Theme: Nord",
    "theme-tokyo-night": "Theme: Tokyo Night",
    "theme-solarized-light": "Theme: Solarized Light",
    "theme-gruvbox": "Theme: Gruvbox",
    "theme-catppuccin-mocha": "Theme: Catppuccin Mocha",
}


# Theme button ids exposed via the palette. The TUI registers a handler for
# each that flips ``App.theme`` to the matching Textual built-in.
THEME_BUTTON_IDS: tuple[str, ...] = (
    "theme-textual-dark",
    "theme-textual-light",
    "theme-monokai",
    "theme-dracula",
    "theme-nord",
    "theme-tokyo-night",
    "theme-solarized-light",
    "theme-gruvbox",
    "theme-catppuccin-mocha",
)


def label_for(button_id: str) -> str:
    """Return a human-friendly label for *button_id*."""
    if button_id in _LABELS:
        return _LABELS[button_id]
    return button_id.replace("-", " ").title()


def filter_commands(query: str, button_ids: list[str]) -> list[tuple[str, str]]:
    """Return ``(button_id, label)`` pairs matching *query* — case-insensitive substring.

    Pure function for testability. Sorting is stable on label, putting more
    descriptive entries first. Empty query returns every entry.
    """
    needle = query.strip().casefold()
    candidates = [(bid, label_for(bid)) for bid in button_ids]
    if not needle:
        return sorted(candidates, key=lambda pair: pair[1].casefold())
    matches = [(bid, lbl) for bid, lbl in candidates if needle in lbl.casefold() or needle in bid.casefold()]
    return sorted(matches, key=lambda pair: pair[1].casefold())


def build_command_palette(handlers: Mapping[str, Callable[[], None]]) -> Screen:
    """Construct the modal palette bound to *handlers*.

    *handlers* is the dispatch dict from the main TUI app (`self._button_handlers`).
    The palette never imports or directly manipulates app state — it just
    invokes the chosen handler when the user hits ``Enter``.
    """
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Input, ListItem, ListView, Static

    button_ids = sorted(handlers)

    class CommandPalette(ModalScreen[None]):
        POPUP_KEY = "command-palette"

        DEFAULT_CSS = """
        CommandPalette { align: center middle; }
        #palette-dialog { width: 64; max-width: 90%; height: 24; max-height: 70%;
            border: heavy #1f6feb; background: #0d1117; padding: 1 1; }
        #palette-title { text-style: bold; margin-bottom: 1; }
        #palette-input { margin-bottom: 1; }
        #palette-list { height: 1fr; }
        """

        BINDINGS = [
            Binding("escape", "app.pop_screen", "Cancel"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._filter = ""
            # Map from position-in-list (after filtering) to button_id, refreshed on
            # every filter change. Avoids relying on widget IDs (which would
            # conflict on re-render because ``ListView.clear()`` is async and
            # returns an AwaitRemove the sync caller can't easily await).
            self._visible_button_ids: list[str] = []

        def compose(self) -> ComposeResult:
            with Vertical(id="palette-dialog"):
                yield Static("Run a command — type to filter, Enter to run", id="palette-title")
                yield Input(placeholder="search commands…", id="palette-input")
                yield ListView(id="palette-list")

        def on_mount(self) -> None:
            self._refresh_list()
            self.query_one("#palette-input", Input).focus()

        def _refresh_list(self) -> None:
            list_view = self.query_one("#palette-list", ListView)
            list_view.clear()
            matches = filter_commands(self._filter, button_ids)
            self._visible_button_ids = [pair[0] for pair in matches]
            for _, label in matches:
                # No widget id — see __init__ comment. ListItem position tracks
                # against _visible_button_ids[i] for lookups.
                list_view.append(ListItem(Static(label)))

        def _selected_button_id(self) -> str | None:
            list_view = self.query_one("#palette-list", ListView)
            index = list_view.index
            if index is None or index < 0 or index >= len(self._visible_button_ids):
                # Default to the first filtered entry if nothing is highlighted.
                if self._visible_button_ids:
                    return self._visible_button_ids[0]
                return None
            return self._visible_button_ids[index]

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "palette-input":
                self._filter = event.value
                self._refresh_list()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id != "palette-input":
                return
            self._fire_selected()

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            self._fire_selected()

        def _fire_selected(self) -> None:
            button_id = self._selected_button_id()
            self.app.pop_screen()
            if button_id is None:
                return
            handler = handlers.get(button_id)
            if handler is not None:
                handler()

    return CommandPalette()
