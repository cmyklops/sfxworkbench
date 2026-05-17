"""Modal screen for action results that completed with reviewable issues."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.screen import ModalScreen


def build_action_issues_screen(
    *,
    action: str,
    status: str,
    message: str,
    errors: tuple[str, ...],
    output_path: str | None = None,
) -> ModalScreen[str]:
    """Construct a modal summary for warnings/errors recorded by an action."""
    from textual.app import ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import Button, Static

    class ActionIssuesScreen(ModalScreen[str]):
        POPUP_KEY = "action-issues"

        CSS = """
        ActionIssuesScreen {
            align: center middle;
        }
        #action-issues-dialog {
            width: 78;
            max-width: 92%;
            height: auto;
            max-height: 80%;
            border: heavy #d29922;
            background: #101923;
            padding: 1 2;
        }
        #action-issues-title {
            text-style: bold;
            color: #f8fafc;
            margin-bottom: 1;
        }
        #action-issues-message {
            color: #d7dee7;
            margin-bottom: 1;
        }
        .issue-warning {
            color: #d29922;
        }
        .issue-error {
            color: #ff7b72;
        }
        .issue-muted {
            color: #9fb0c1;
        }
        #action-issues-list {
            height: auto;
            max-height: 12;
            margin-top: 1;
            margin-bottom: 1;
        }
        #action-issues-actions {
            height: auto;
            margin-top: 1;
        }
        """

        def __init__(
            self,
            *,
            action: str,
            status: str,
            message: str,
            errors: tuple[str, ...],
            output_path: str | None,
        ) -> None:
            super().__init__()
            self._action = action
            self._status = status
            self._message = message
            self._errors = errors
            self._output_path = output_path

        def compose(self) -> ComposeResult:
            issue_count = len(self._errors)
            issue_class = "issue-error" if self._status == "error" else "issue-warning"
            title = f"{self._action.replace('_', ' ').title()} finished with {issue_count:,} issue(s)"
            with Vertical(id="action-issues-dialog"):
                yield Static(title, id="action-issues-title", classes=issue_class)
                yield Static(
                    f"State: {self._status}. {self._message}",
                    id="action-issues-message",
                    classes=issue_class,
                )
                if self._output_path:
                    yield Static(f"Output: {self._output_path}", classes="issue-muted")
                with VerticalScroll(id="action-issues-list"):
                    for error in self._errors[:8]:
                        yield Static(f"! {error}", classes=issue_class)
                    remaining = issue_count - min(issue_count, 8)
                    if remaining > 0:
                        yield Static(f"... {remaining:,} more issue(s) in History.", classes="issue-muted")
                with Horizontal(id="action-issues-actions"):
                    yield Button("Review History", id="action-issues-review")
                    yield Button("Dismiss", id="action-issues-dismiss", variant="warning")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            self.dismiss("history" if event.button.id == "action-issues-review" else "dismiss")

    return ActionIssuesScreen(
        action=action,
        status=status,
        message=message,
        errors=errors,
        output_path=output_path,
    )
