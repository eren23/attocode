"""Tool call display panel using Textual Collapsible widgets."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Collapsible, Static


_SPINNER_FRAMES = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f")


@dataclass
class ToolCallInfo:
    """Information about a running/completed tool call."""

    tool_id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    status: str = "running"  # running, completed, error
    result: str | None = None
    error: str | None = None
    start_time: float = field(default_factory=time.monotonic)
    duration_ms: float = 0.0


class ToolCallsPanel(Widget):
    """Panel showing recent tool calls as individual Collapsible sections."""

    DEFAULT_CSS = """
    ToolCallsPanel {
        height: auto;
        max-height: 20;
    }
    ToolCallsPanel #tool-scroll {
        height: auto;
        max-height: 18;
    }
    ToolCallsPanel Collapsible {
        padding: 0;
        margin: 0;
    }
    """

    expanded: reactive[bool] = reactive(False)
    filter_mode: reactive[str] = reactive("all")  # all, errors, running

    def __init__(self, max_display: int = 20, **kwargs) -> None:
        super().__init__(**kwargs)
        self._calls: dict[str, ToolCallInfo] = {}  # widget_id -> info
        self._call_order: list[str] = []  # ordered widget_ids
        self._tool_id_to_widget_id: dict[str, str] = {}  # tool_id -> latest widget_id
        self._call_counter: int = 0
        self._max_display = max_display
        self._spinner_index = 0
        self._spinner_timer: Timer | None = None
        # Summary stats
        self._total_completed: int = 0
        self._total_errors: int = 0
        self._total_duration_ms: float = 0.0

    def compose(self) -> ComposeResult:
        # Header label — hidden when no tools
        yield Static("", id="tool-calls-header")
        yield VerticalScroll(id="tool-scroll")

    def add_call(self, info: ToolCallInfo) -> None:
        """Add a tool call as a new Collapsible."""
        widget_id = f"tc-{self._call_counter}"
        self._call_counter += 1

        self._calls[widget_id] = info
        self._call_order.append(widget_id)
        self._tool_id_to_widget_id[info.tool_id] = widget_id

        # Trim old calls
        while len(self._call_order) > self._max_display:
            old_wid = self._call_order.pop(0)
            self._calls.pop(old_wid, None)
            try:
                old_widget = self.query_one(f"#{old_wid}", Collapsible)
                old_widget.remove()
            except Exception:
                pass

        # Build collapsible content
        body_text = self._render_body(info)
        title = self._make_title(info)

        collapsible = Collapsible(
            Static(body_text, classes="tool-call-body"),
            title=title,
            collapsed=False,
            id=widget_id,
        )
        scroll = self.query_one("#tool-scroll", VerticalScroll)
        scroll.mount(collapsible)
        scroll.scroll_end(animate=False)
        self._ensure_spinner()
        self.add_class("has-tools")
        self._update_header()

    def update_call(
        self,
        tool_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update an existing tool call's status."""
        widget_id = self._tool_id_to_widget_id.get(tool_id)
        if not widget_id:
            return
        info = self._calls.get(widget_id)
        if not info:
            return

        info.status = status
        if result is not None:
            info.result = result
        if error is not None:
            info.error = error

        # Track duration on completion
        if status in ("completed", "error"):
            info.duration_ms = (time.monotonic() - info.start_time) * 1000
            self._total_duration_ms += info.duration_ms
            if status == "completed":
                self._total_completed += 1
            else:
                self._total_errors += 1

        try:
            collapsible = self.query_one(f"#{widget_id}", Collapsible)
            # Update title
            collapsible.title = self._make_title(info)
            # Update body
            body = collapsible.query_one(".tool-call-body", Static)
            body.update(self._render_body(info))
            # Auto-collapse completed calls
            if status in ("completed", "error"):
                collapsible.collapsed = True
        except Exception:
            pass

        self._ensure_spinner()
        self._update_header()

    def clear_calls(self) -> None:
        """Clear all tool calls."""
        self._calls.clear()
        self._call_order.clear()
        self._tool_id_to_widget_id.clear()
        self._call_counter = 0
        self._total_completed = 0
        self._total_errors = 0
        self._total_duration_ms = 0.0
        self.filter_mode = "all"
        try:
            scroll = self.query_one("#tool-scroll", VerticalScroll)
            for collapsible in scroll.query(Collapsible):
                collapsible.remove()
        except Exception:
            pass
        self._ensure_spinner()
        self.remove_class("has-tools")
        self._update_header()

    def toggle_expanded(self) -> None:
        """Toggle all collapsibles open/closed."""
        self.expanded = not self.expanded
        for collapsible in self.query(Collapsible):
            collapsible.collapsed = not self.expanded

    def watch_expanded(self) -> None:
        """React to expanded changes."""
        pass

    def _make_title(self, call: ToolCallInfo) -> str:
        """Build the collapsible title string."""
        if call.status == "running":
            frame = _SPINNER_FRAMES[self._spinner_index]
            args_brief = ", ".join(
                f"{k}={_truncate(str(v), 30)}"
                for k, v in list(call.args.items())[:2]
            )
            suffix = f" ({args_brief})" if args_brief else ""
            return f"{frame} {call.name}{suffix}"
        elif call.status == "completed":
            elapsed = time.monotonic() - call.start_time
            return f"\u2713 {call.name} ({elapsed:.1f}s)"
        else:
            return f"\u2717 {call.name}"

    def _render_body(self, call: ToolCallInfo) -> Text:
        """Render tool call body (args + result/error)."""
        text = Text()

        # Args
        if call.args:
            for key, val in call.args.items():
                text.append(f"  {key}: ", style="dim bold")
                text.append(f"{_truncate(str(val), 120)}\n", style="dim")

        # Result
        if call.result:
            text.append(
                f"  \u2192 {_truncate(call.result, 300)}\n", style="dim green"
            )

        # Error
        if call.error:
            text.append(
                f"  \u2717 {_truncate(call.error, 300)}\n", style="dim red"
            )

        return text

    def _update_header(self) -> None:
        """Update the header label with summary stats."""
        try:
            header = self.query_one("#tool-calls-header", Static)
            running_count = sum(1 for c in self._calls.values() if c.status == "running")
            if not self._calls:
                header.update("")
                return

            text = Text()
            text.append("Tools: ", style="bold cyan")

            parts: list[str] = []
            if running_count > 0:
                parts.append(f"{running_count} running")
            if self._total_completed > 0:
                parts.append(f"{self._total_completed} completed")
            if self._total_errors > 0:
                parts.append(f"{self._total_errors} errors")
            text.append(", ".join(parts), style="dim")

            # Average duration
            finished = self._total_completed + self._total_errors
            if finished > 0:
                avg_ms = self._total_duration_ms / finished
                if avg_ms >= 1000:
                    text.append(f" — Avg: {avg_ms / 1000:.1f}s", style="dim")
                else:
                    text.append(f" — Avg: {avg_ms:.0f}ms", style="dim")

            # Filter mode indicator
            if self.filter_mode != "all":
                text.append(f" [{self.filter_mode}]", style="yellow")

            header.update(text)
        except Exception:
            pass

    def cycle_filter(self) -> None:
        """Cycle through filter modes: all -> errors -> running -> all."""
        modes = ["all", "errors", "running"]
        current_idx = modes.index(self.filter_mode) if self.filter_mode in modes else 0
        self.filter_mode = modes[(current_idx + 1) % len(modes)]
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Show/hide collapsibles based on filter mode."""
        for widget_id, info in self._calls.items():
            try:
                collapsible = self.query_one(f"#{widget_id}", Collapsible)
                if self.filter_mode == "all":
                    collapsible.display = True
                elif self.filter_mode == "errors":
                    collapsible.display = info.status == "error"
                elif self.filter_mode == "running":
                    collapsible.display = info.status == "running"
            except Exception:
                pass
        self._update_header()

    def _ensure_spinner(self) -> None:
        """Start or stop spinner based on running tools."""
        has_running = any(c.status == "running" for c in self._calls.values())
        if has_running and self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.08, self._spin)
        elif not has_running and self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _spin(self) -> None:
        """Advance spinner frame and update running call titles."""
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        for widget_id, call in self._calls.items():
            if call.status == "running":
                try:
                    collapsible = self.query_one(f"#{widget_id}", Collapsible)
                    collapsible.title = self._make_title(call)
                except Exception:
                    pass


def _truncate(s: str, max_len: int) -> str:
    """Truncate string with ellipsis."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "\u2026"
