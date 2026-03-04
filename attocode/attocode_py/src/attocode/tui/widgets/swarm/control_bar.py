"""Swarm control bar — Pause/Resume/Cancel buttons for swarm execution."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button


class SwarmPauseRequested(Message):
    """User requested to pause swarm dispatch."""


class SwarmResumeRequested(Message):
    """User requested to resume swarm dispatch."""


class SwarmCancelRequested(Message):
    """User requested to cancel the swarm."""


class SkipTaskRequested(Message):
    """User requested to skip a task."""

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id


class RetryTaskRequested(Message):
    """User requested to retry a failed task."""

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id


class SwarmControlBar(Widget):
    """Horizontal bar with Pause/Resume and Cancel buttons."""

    DEFAULT_CSS = """
    SwarmControlBar {
        height: 3;
        dock: bottom;
        padding: 0 1;
    }
    SwarmControlBar > Horizontal {
        height: auto;
        align: center middle;
    }
    SwarmControlBar Button {
        margin: 0 1;
        min-width: 12;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._paused = False
        self._cancel_confirm = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Button("\u23f8 Pause", id="swarm-pause-btn", variant="warning")
            yield Button("\u2715 Cancel", id="swarm-cancel-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "swarm-pause-btn":
            if self._paused:
                self._paused = False
                event.button.label = "\u23f8 Pause"
                event.button.variant = "warning"
                self.post_message(SwarmResumeRequested())
            else:
                self._paused = True
                event.button.label = "\u25b6 Resume"
                event.button.variant = "success"
                self.post_message(SwarmPauseRequested())
        elif event.button.id == "swarm-cancel-btn":
            if self._cancel_confirm:
                self._cancel_confirm = False
                event.button.label = "\u2715 Cancel"
                self.post_message(SwarmCancelRequested())
            else:
                self._cancel_confirm = True
                event.button.label = "\u2715 Confirm Cancel?"
                # Reset after 3 seconds if not confirmed
                self.set_timer(3.0, self._reset_cancel_confirm)

    def _reset_cancel_confirm(self) -> None:
        """Reset the cancel confirmation state."""
        if self._cancel_confirm:
            self._cancel_confirm = False
            try:
                btn = self.query_one("#swarm-cancel-btn", Button)
                btn.label = "\u2715 Cancel"
            except Exception:
                pass
