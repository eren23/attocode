"""Token burn trend sparkline widget."""

from __future__ import annotations

from textual.widgets import Sparkline


class TokenSparkline(Sparkline):
    """1-line Sparkline showing token usage over the last ~20 LLM calls.

    Docked above the status bar. Hidden by default; shown during processing
    when there is data to display.
    """

    DEFAULT_CSS = """
    TokenSparkline {
        height: 1;
        dock: bottom;
        display: none;
        background: $surface-darken-1;
    }
    TokenSparkline.visible {
        display: block;
    }
    """
