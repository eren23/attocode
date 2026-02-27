"""Timeline Screen — full-screen event timeline with filtering."""

from __future__ import annotations

from typing import Any, Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header

from attocode.tui.widgets.swarm.event_timeline import EventTimeline


class TimelineScreen(Screen):
    """Full-screen scrollable event timeline with live polling."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=True),
        Binding("f", "toggle_filter", "Filter", show=True),
    ]

    DEFAULT_CSS = """
    TimelineScreen {
        background: $surface;
    }
    #timeline-full {
        height: 1fr;
        max-height: 100%;
        min-height: 10;
    }
    """

    def __init__(
        self,
        state_fn: Callable[[], dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._state_fn = state_fn
        self._events = events or []
        self._poll_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield EventTimeline(id="timeline-full")
        yield Footer()

    def on_mount(self) -> None:
        timeline = self.query_one("#timeline-full", EventTimeline)
        # Show initial events immediately
        if self._events:
            timeline.update_events(self._events)
        # Start polling if we have a state_fn
        if self._state_fn:
            self._poll_timer = self.set_interval(0.5, self._poll)

    def on_unmount(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()

    def _poll(self) -> None:
        if not self._state_fn:
            return
        try:
            state = self._state_fn()
        except Exception:
            return
        events = state.get("events", [])
        if events:
            self._events = events
            self.query_one("#timeline-full", EventTimeline).update_events(events)

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_toggle_filter(self) -> None:
        timeline = self.query_one("#timeline-full", EventTimeline)
        # Cycle through filter types
        filters = ["", "spawn", "write", "conflict", "complete", "fail"]
        current = timeline.filter_type
        try:
            idx = filters.index(current)
        except ValueError:
            idx = -1
        timeline.filter_type = filters[(idx + 1) % len(filters)]
