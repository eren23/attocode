"""Timeline Screen — full-screen event timeline with filtering and summary."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Static

from attocode.tui.widgets.swarm.event_timeline import EventTimeline


_FILTER_TYPES = [
    "", "spawn", "complete", "fail", "write", "conflict",
    "budget", "decision", "dispatch", "skip",
]


class TimelineScreen(Screen):
    """Full-screen scrollable event timeline with live polling and enhanced filtering."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=True),
        Binding("f", "toggle_filter", "Filter", show=True),
    ]

    DEFAULT_CSS = """
    TimelineScreen {
        background: $surface;
    }
    #timeline-summary {
        height: 2;
        padding: 0 2;
        background: $boost;
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
        yield Static("", id="timeline-summary")
        yield EventTimeline(id="timeline-full")
        yield Footer()

    def on_mount(self) -> None:
        timeline = self.query_one("#timeline-full", EventTimeline)
        # Show initial events immediately
        if self._events:
            timeline.update_events(self._events)
            self._update_summary()
        # Start polling if we have a state_fn
        if self._state_fn:
            self._poll_timer = self.set_interval(1.0, self._poll)

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

        # Try timeline key first (event bridge), then events (old format)
        events = state.get("timeline", state.get("events", []))
        if events:
            self._events = events
            try:
                self.query_one("#timeline-full", EventTimeline).update_events(events)
            except Exception:
                pass
            self._update_summary()

    def _update_summary(self) -> None:
        """Update the event count summary header."""
        try:
            summary_widget = self.query_one("#timeline-summary", Static)
        except Exception:
            return

        total = len(self._events)
        if total == 0:
            summary_widget.update(Text("No events", style="dim"))
            return

        # Count by type keyword
        counts: Counter[str] = Counter()
        for e in self._events:
            etype = e.get("type", "unknown")
            # Extract the key action word from the event type
            for keyword in _FILTER_TYPES[1:]:
                if keyword in etype.lower():
                    counts[keyword] += 1
                    break
            else:
                counts["other"] += 1

        text = Text()
        text.append(f"Events: {total} total", style="bold")
        text.append(" — ", style="dim")

        parts = []
        for keyword in _FILTER_TYPES[1:]:
            c = counts.get(keyword, 0)
            if c > 0:
                parts.append(f"{c} {keyword}")
        other = counts.get("other", 0)
        if other > 0:
            parts.append(f"{other} other")

        text.append(", ".join(parts), style="dim")

        # Show current filter
        try:
            timeline = self.query_one("#timeline-full", EventTimeline)
            if timeline.filter_type:
                text.append(f"  [filter: {timeline.filter_type}]", style="yellow bold")
        except Exception:
            pass

        summary_widget.update(text)

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_toggle_filter(self) -> None:
        timeline = self.query_one("#timeline-full", EventTimeline)
        current = timeline.filter_type
        try:
            idx = _FILTER_TYPES.index(current)
        except ValueError:
            idx = -1
        timeline.filter_type = _FILTER_TYPES[(idx + 1) % len(_FILTER_TYPES)]
        self._update_summary()
