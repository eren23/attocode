"""Error detail panel for displaying rich error information.

Shows detailed error information including stack traces, context,
and suggested fixes in a structured format.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass(slots=True)
class ErrorDetail:
    """Structured error information."""

    title: str
    message: str
    error_type: str = "error"  # "error", "warning", "info"
    tool_name: str = ""
    stack_trace: str = ""
    context: str = ""
    suggestion: str = ""
    timestamp: float = 0.0
    recoverable: bool = True


class ErrorDetailPanel(VerticalScroll):
    """Displays detailed error information.

    Features:
    - Categorized error display (error/warning/info)
    - Stack trace with syntax highlighting
    - Contextual information
    - Suggested fixes
    - Error history
    """

    DEFAULT_CSS = """
    ErrorDetailPanel {
        height: auto;
        max-height: 20;
        border: round $error;
        padding: 0 1;
    }
    ErrorDetailPanel .edp-header {
        color: $error;
        text-style: bold;
    }
    ErrorDetailPanel .edp-error {
        color: $error;
        margin: 1 0 0 0;
    }
    ErrorDetailPanel .edp-warning {
        color: $warning;
        margin: 1 0 0 0;
    }
    ErrorDetailPanel .edp-suggestion {
        color: $success;
    }
    ErrorDetailPanel .edp-context {
        color: $text-muted;
    }
    """

    errors: reactive[list[ErrorDetail]] = reactive(list, layout=True)

    def compose(self) -> ComposeResult:
        yield Static("Errors", classes="edp-header")
        yield Static("", id="edp-content")

    def add_error(self, error: ErrorDetail) -> None:
        """Add an error to the panel."""
        if error.timestamp == 0.0:
            error.timestamp = time.monotonic()

        current = list(self.errors)
        current.append(error)
        if len(current) > 20:
            current = current[-20:]
        self.errors = current
        self._render()

    def add_simple_error(
        self,
        title: str,
        message: str,
        *,
        tool_name: str = "",
        suggestion: str = "",
    ) -> None:
        """Convenience method for simple errors."""
        self.add_error(ErrorDetail(
            title=title,
            message=message,
            tool_name=tool_name,
            suggestion=suggestion,
        ))

    def _render(self) -> None:
        """Render all errors."""
        widget = self.query_one("#edp-content", Static)
        if not self.errors:
            widget.update("No errors")
            return

        lines: list[str] = []
        for error in reversed(self.errors[-5:]):
            icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}.get(error.error_type, "?")
            lines.append(f"{icon} {error.title}")

            if error.tool_name:
                lines.append(f"  Tool: {error.tool_name}")
            lines.append(f"  {error.message[:200]}")

            if error.stack_trace:
                trace_lines = error.stack_trace.strip().split("\n")[-3:]
                for tl in trace_lines:
                    lines.append(f"    {tl.strip()}")

            if error.suggestion:
                lines.append(f"  Fix: {error.suggestion}")

            if not error.recoverable:
                lines.append("  [Non-recoverable]")

            lines.append("")

        widget.update("\n".join(lines))

    def clear(self) -> None:
        """Clear all errors."""
        self.errors = []
        self.query_one("#edp-content", Static).update("No errors")

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.errors if e.error_type == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.errors if e.error_type == "warning")
