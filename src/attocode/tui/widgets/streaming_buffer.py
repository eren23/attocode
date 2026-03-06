"""Streaming buffer widget for live LLM response display."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import Static


class StreamingBuffer(Static):
    """Accumulates streaming text and renders with a blinking cursor.

    Used as a sibling to MessageLog — shows live streaming text
    while the LLM is generating, then hides when done.
    """

    DEFAULT_CSS = """
    StreamingBuffer {
        height: auto;
        max-height: 15;
        display: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_parts: list[str] = []
        self._thinking_parts: list[str] = []
        self._active = False
        self._start_time: str = ""

    def start(self) -> None:
        """Begin accumulating a new streamed response."""
        self._text_parts = []
        self._thinking_parts = []
        self._active = True
        self._start_time = datetime.now().strftime("%H:%M:%S")
        self.add_class("active")
        self._render_content()

    def append_chunk(self, text: str, chunk_type: str = "text") -> None:
        """Append a chunk of streamed content."""
        if not self._active:
            return
        if chunk_type == "thinking":
            self._thinking_parts.append(text)
        else:
            self._text_parts.append(text)
        self._render_content()

    def get_final_text(self) -> str:
        """Get the accumulated text content."""
        return "".join(self._text_parts)

    def get_final_thinking(self) -> str:
        """Get the accumulated thinking content."""
        return "".join(self._thinking_parts)

    def stop(self) -> None:
        """Stop streaming and hide."""
        self._active = False
        self.remove_class("active")
        self.update("")

    def _render_content(self) -> None:
        """Re-render the streaming content."""
        text = Text()
        text.append(f"[{self._start_time}] ", style="dim")
        text.append(" Agent ", style="bold #1e1e2e on #89b4fa")
        text.append(" ")

        accumulated = "".join(self._text_parts)
        if accumulated:
            text.append(accumulated)
            text.append("\u258c", style="blink bold blue")  # block cursor
        else:
            text.append("\u2026", style="dim italic")  # ellipsis while waiting

        self.update(text)
