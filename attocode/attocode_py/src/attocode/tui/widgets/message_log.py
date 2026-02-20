"""Message log widget using RichLog."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import RichLog


class MessageLog(RichLog):
    """Displays conversation messages in a scrollable log.

    Uses Textual's RichLog for efficient append-only rendering
    with built-in scrolling.
    """

    DEFAULT_CSS = """
    MessageLog {
        height: 1fr;
        min-height: 5;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self._max_messages = 500

    def add_user_message(self, text: str) -> None:
        """Add a user message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" You ", style="bold on #45475a")
        styled.append(" ")
        styled.append(text)
        self.write(styled)

    def add_assistant_message(self, text: str) -> None:
        """Add an assistant message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" Agent ", style="bold #1e1e2e on #89b4fa")
        styled.append(" ")
        styled.append(text)
        self.write(styled)

    def add_system_message(self, text: str) -> None:
        """Add a system/info message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" sys ", style="italic #6c7086 on #313244")
        styled.append(" ")
        styled.append(text, style="dim italic")
        self.write(styled)

    def add_error_message(self, text: str) -> None:
        """Add an error message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        styled.append(" ERR ", style="bold #1e1e2e on #f38ba8")
        styled.append(" ")
        styled.append(text, style="red")
        self.write(styled)

    def add_tool_message(self, name: str, status: str = "started") -> None:
        """Add a tool status message."""
        ts = datetime.now().strftime("%H:%M:%S")
        styled = Text()
        styled.append(f"[{ts}] ", style="dim")
        if status == "started":
            icon, color = "\u26a1", "yellow"
        elif status == "completed":
            icon, color = "\u2713", "green"
        else:
            icon, color = "\u2717", "red"
        styled.append(f"{icon} {name}", style=color)
        self.write(styled)
