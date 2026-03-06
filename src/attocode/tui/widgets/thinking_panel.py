"""Thinking panel widget — shows model thinking state."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class ThinkingPanel(Static):
    """Displays the model's extended thinking content.

    Shows a preview of thinking text while the model is reasoning,
    and hides when thinking is complete.
    """

    DEFAULT_CSS = """
    ThinkingPanel {
        height: auto;
        max-height: 5;
        display: none;
    }
    """

    _MAX_PREVIEW_CHARS = 200

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._thinking_parts: list[str] = []
        self._active = False

    def start_thinking(self) -> None:
        """Begin a thinking session."""
        self._thinking_parts = []
        self._active = True
        self.add_class("active")
        self._render_content()

    def append_thinking(self, text: str) -> None:
        """Append thinking text."""
        if not self._active:
            return
        self._thinking_parts.append(text)
        self._render_content()

    def stop_thinking(self) -> None:
        """Stop thinking display."""
        self._active = False
        self.remove_class("active")
        self.update("")

    def _render_content(self) -> None:
        """Render thinking preview."""
        text = Text()
        text.append("\u283f ", style="blue")  # braille spinner char
        text.append("Thinking", style="bold blue")

        accumulated = "".join(self._thinking_parts)
        if accumulated:
            preview = accumulated[:self._MAX_PREVIEW_CHARS]
            if len(accumulated) > self._MAX_PREVIEW_CHARS:
                preview += "\u2026"
            text.append(" \u2014 ", style="dim")
            text.append(preview, style="dim italic")
        else:
            text.append("\u2026", style="dim")

        self.update(text)
