"""Event Timeline — scrollable feed of swarm events."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog, Static


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


# ── Color map for EventsLog ──────────────────────────────────────────

_LOG_COLORS: dict[str, str] = {
    "spawn": "cyan",
    "claim": "yellow",
    "write": "green",
    "conflict": "red bold",
    "complete": "green bold",
    "fail": "red",
    "skip": "yellow dim",
    "budget": "magenta",
    "transition": "blue",
    "info": "dim",
}


class EventsLog(Widget):
    """RichLog-based event viewer with delta-append and auto-scroll.

    Unlike EventTimeline (which re-renders all content on every update),
    this widget only appends new events, avoiding flicker and supporting
    auto-scroll in long sessions.
    """

    DEFAULT_CSS = """
    EventsLog {
        height: 1fr;
    }
    EventsLog > RichLog {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._seen_count: int = 0

    def compose(self):
        yield RichLog(id="events-log", auto_scroll=True, markup=True)

    def update_events(self, events: list[dict[str, Any]]) -> None:
        """Append only new events since last call."""
        if not events:
            return
        new_events = events[self._seen_count:]
        if not new_events:
            return
        self._seen_count = len(events)

        try:
            log = self.query_one("#events-log", RichLog)
        except Exception:
            return

        for event in new_events:
            ts = event.get("timestamp", 0)
            if ts:
                time_str = time.strftime("%H:%M:%S", time.localtime(ts))
            else:
                time_str = "??:??:??"

            etype = event.get("type", "info")
            color = _LOG_COLORS.get(etype, "dim")
            agent_id = event.get("agent_id", "")
            task_id = event.get("task_id", "")
            message = event.get("message", "")

            line = Text()
            line.append(f"{time_str} ", style="dim")
            line.append(f"[{etype.upper():12s}] ", style=color)
            if agent_id:
                line.append(f"{agent_id} ", style="cyan dim")
            if task_id:
                line.append(f"{task_id} ", style="green dim")
            line.append(message)

            log.write(line)
