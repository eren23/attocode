"""Percentage progress bar widget.

Usage::

    bar = PercentBar(value=0.42, label="Budget")
    # Renders:  Budget [████████░░░░░░░░░░░░] 42%
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget

from rich.text import Text

_BAR_WIDTH = 20


class PercentBar(Widget):
    """Single-line progress bar with threshold-based coloring.

    Color thresholds:

    * 0--60 %: green
    * 60--85 %: yellow
    * 85--100 %: red
    """

    DEFAULT_CSS = """
    PercentBar {
        height: 1;
    }
    """

    value: reactive[float] = reactive(0.0)
    label: reactive[str] = reactive("")
    bar_width: reactive[int] = reactive(_BAR_WIDTH)

    def __init__(
        self,
        value: float = 0.0,
        label: str = "",
        bar_width: int = _BAR_WIDTH,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.value = value
        self.label = label
        self.bar_width = bar_width

    def render(self) -> Text:
        clamped = max(0.0, min(1.0, self.value))
        filled = int(clamped * self.bar_width)
        empty = self.bar_width - filled

        bar_char = "\u2588"
        empty_char = "\u2591"

        style = _threshold_style(clamped)

        text = Text()
        if self.label:
            text.append(f"{self.label} ", style="bold")
        text.append("[", style="dim")
        text.append(bar_char * filled, style=style)
        text.append(empty_char * empty, style="dim")
        text.append("]", style="dim")
        text.append(f" {clamped:.0%}", style=style)

        return text


def _threshold_style(fraction: float) -> str:
    """Return a Rich style string based on the fraction."""
    if fraction >= 0.85:
        return "red bold"
    if fraction >= 0.60:
        return "yellow"
    return "green"
