"""Event Timeline — scrollable feed of swarm events."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


_EVENT_STYLES = {
    "spawn": "cyan",
    "claim": "yellow",
    "write": "green",
    "conflict": "red bold",
    "complete": "green bold",
    "fail": "red",
    "skip": "yellow dim",
    "budget": "magenta",
    "info": "dim",
}

_EVENT_ICONS = {
    "spawn": "\u25b6",     # ▶
    "claim": "\U0001f512",  # 🔒 (fallback to text in non-emoji terminals)
    "write": "\u270e",     # ✎
    "conflict": "\u26a0",  # ⚠
    "complete": "\u2713",  # ✓
    "fail": "\u2717",      # ✗
    "skip": "\u2212",      # −
    "budget": "$",
    "info": "\u2022",      # •
}


class EventTimeline(Static):
    """Scrollable timeline of swarm orchestration events."""

    DEFAULT_CSS = """
    EventTimeline {
        height: auto;
        min-height: 4;
        max-height: 10;
        overflow-y: auto;
        padding: 0 1;
        border: solid $surface-lighten-1;
    }
    """

    events: reactive[list[dict[str, Any]]] = reactive(list)
    filter_type: reactive[str] = reactive("")  # "" = show all

    def watch_events(self, events: list[dict[str, Any]]) -> None:
        self._rebuild(events)

    def watch_filter_type(self, _: str) -> None:
        self._rebuild(self.events)

    def add_event(self, event: dict[str, Any]) -> None:
        """Append a single event and re-render."""
        current = list(self.events)
        current.append(event)
        # Keep last 100
        if len(current) > 100:
            current = current[-100:]
        self.events = current

    def update_events(self, events: list[dict[str, Any]]) -> None:
        """Replace all events."""
        self.events = events

    def _rebuild(self, events: list[dict[str, Any]]) -> None:
        if not events:
            self.update(Text("(no events yet)", style="dim"))
            return

        filtered = events
        if self.filter_type:
            filtered = [e for e in events if e.get("type") == self.filter_type]

        text = Text()
        for event in filtered[-30:]:  # Show last 30
            ts = event.get("timestamp", 0)
            if ts:
                time_str = time.strftime("%H:%M:%S", time.localtime(ts))
            else:
                time_str = "??:??:??"

            etype = event.get("type", "info")
            icon = _EVENT_ICONS.get(etype, "\u2022")
            style = _EVENT_STYLES.get(etype, "dim")
            message = event.get("message", "")

            text.append(f"{time_str} ", style="dim")
            text.append(f"[{etype.upper():8s}] ", style=style)
            text.append(f"{icon} ", style=style)
            text.append(f"{message}\n")

        self.update(text)
