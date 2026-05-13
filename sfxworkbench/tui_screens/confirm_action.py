"""Modal confirm/cancel screen for destructive actions.

Extracted from ``tui_app.run_tui`` so the screen class lives in the
``tui_screens/`` collection alongside the other named screens. Textual is
imported lazily inside :func:`build_confirm_action_screen` so this module
loads even when the optional ``tui`` extra is not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.screen import ModalScreen


def build_confirm_action_screen(title: str, message: str) -> ModalScreen[bool]:
    """Construct a ``ConfirmActionScreen`` instance.

    Factory pattern matches ``build_metadata_review_screen`` etc. so the
    Textual import stays inside the function and module-level import remains
    cheap.
    """
    from textual.app import ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, Static

    class ConfirmActionScreen(ModalScreen[bool]):
        CSS = """
        ConfirmActionScreen {
            align: center middle;
        }
        #confirm-dialog {
            width: 72;
            max-width: 90%;
            height: auto;
            border: heavy #d29922;
            background: #101923;
            padding: 1 2;
        }
        #confirm-title {
            text-style: bold;
            color: #f8fafc;
            margin-bottom: 1;
        }
        #confirm-message {
            color: #d7dee7;
            margin-bottom: 1;
        }
        #confirm-actions {
            height: auto;
            margin-top: 1;
        }
        """

        def __init__(self, title: str, message: str) -> None:
            super().__init__()
            self._title = title
            self._message = message

        def compose(self) -> ComposeResult:
            with Vertical(id="confirm-dialog"):
                yield Static(self._title, id="confirm-title")
                yield Static(self._message, id="confirm-message")
                with Horizontal(id="confirm-actions"):
                    yield Button("Cancel", id="confirm-cancel")
                    yield Button("Continue", id="confirm-continue", variant="warning")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            self.dismiss(event.button.id == "confirm-continue")

    return ConfirmActionScreen(title, message)
