"""Tool call display panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static


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


class ToolCallsPanel(Widget):
    """Panel showing recent tool calls."""

    DEFAULT_CSS = """
    ToolCallsPanel {
        height: auto;
        max-height: 15;
    }
    """

    expanded: reactive[bool] = reactive(False)

    def __init__(self, max_display: int = 5, **kwargs) -> None:
        super().__init__(**kwargs)
        self._calls: list[ToolCallInfo] = []
        self._max_display = max_display
        self._spinner_index = 0
        self._spinner_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="tool-calls-container")

    def add_call(self, info: ToolCallInfo) -> None:
        """Add or update a tool call."""
        for i, existing in enumerate(self._calls):
            if existing.tool_id == info.tool_id:
                self._calls[i] = info
                self._refresh_display()
                self._ensure_spinner()
                self.add_class("has-tools")
                return
        self._calls.append(info)
        if len(self._calls) > self._max_display:
            self._calls = self._calls[-self._max_display :]
        self._refresh_display()
        self._ensure_spinner()
        self.add_class("has-tools")

    def update_call(
        self,
        tool_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update an existing tool call's status."""
        for call in self._calls:
            if call.tool_id == tool_id:
                call.status = status
                if result is not None:
                    call.result = result
                if error is not None:
                    call.error = error
                break
        self._refresh_display()
        self._ensure_spinner()

    def clear_calls(self) -> None:
        """Clear all tool calls."""
        self._calls.clear()
        self._refresh_display()
        self._ensure_spinner()
        self.remove_class("has-tools")

    def toggle_expanded(self) -> None:
        """Toggle expanded view."""
        self.expanded = not self.expanded

    def watch_expanded(self) -> None:
        """React to expanded changes."""
        self._refresh_display()

    def _ensure_spinner(self) -> None:
        """Start or stop spinner based on running tools."""
        has_running = any(c.status == "running" for c in self._calls)
        if has_running and self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.08, self._spin)
        elif not has_running and self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _spin(self) -> None:
        """Advance spinner frame."""
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Re-render the tool calls display."""
        try:
            container = self.query_one("#tool-calls-container", Static)
        except Exception:
            return

        if not self._calls:
            container.update("")
            return

        running_count = sum(1 for c in self._calls if c.status == "running")
        text = Text()

        # Header
        if running_count > 0:
            text.append(f"Tools ({running_count} running)", style="bold cyan")
        else:
            text.append("Tools", style="bold cyan")
        text.append("\n")

        for i, call in enumerate(self._calls):
            if i > 0:
                text.append("    \u2500\u2500\u2500\u2500\u2500\n", style="dim")
            text.append_text(self._render_call(call))
            if i < len(self._calls) - 1:
                text.append("\n")
        container.update(text)

    def _render_call(self, call: ToolCallInfo) -> Text:
        """Render a single tool call."""
        text = Text()

        # Status icon
        if call.status == "running":
            frame = _SPINNER_FRAMES[self._spinner_index]
            text.append(f"    {frame} ", style="yellow")
        elif call.status == "completed":
            text.append("    \u2713 ", style="green")
        else:
            text.append("    \u2717 ", style="red")

        # Tool name
        text.append(call.name, style="bold cyan")

        # Brief args (collapsed view)
        if call.args and not self.expanded:
            brief = ", ".join(
                f"{k}={_truncate(str(v), 40)}"
                for k, v in list(call.args.items())[:3]
            )
            text.append(f" ({brief})", style="dim")

        # Expanded details
        if self.expanded:
            text.append("\n")
            for key, val in call.args.items():
                text.append(f"        {key}: ", style="dim bold")
                text.append(f"{_truncate(str(val), 120)}\n", style="dim")
            if call.result:
                text.append(
                    f"        \u2192 {_truncate(call.result, 200)}\n", style="dim green"
                )
            if call.error:
                text.append(
                    f"        \u2717 {_truncate(call.error, 200)}\n", style="dim red"
                )

        return text


def _truncate(s: str, max_len: int) -> str:
    """Truncate string with ellipsis."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "\u2026"
