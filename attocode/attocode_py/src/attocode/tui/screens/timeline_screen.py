"""Timeline Screen — full-screen event timeline with filtering."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header

from attocode.tui.widgets.swarm.event_timeline import EventTimeline


class TimelineScreen(Screen):
    """Full-screen scrollable event timeline."""

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

    def __init__(self, events: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._events = events or []

    def compose(self) -> ComposeResult:
        yield Header()
        yield EventTimeline(id="timeline-full")
        yield Footer()

    def on_mount(self) -> None:
        timeline = self.query_one("#timeline-full", EventTimeline)
        timeline.update_events(self._events)

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
