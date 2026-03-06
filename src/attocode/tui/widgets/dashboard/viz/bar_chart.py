"""Horizontal bar chart widget.

Usage::

    chart = BarChart(items=[("Python", 45), ("JS", 30), ("Go", 10)])
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget

from rich.text import Text


class BarChart(Widget):
    """Horizontal bar chart rendered with Unicode full-block characters.

    Each item is rendered as a labelled row::

        Python \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588  45
        JS     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588        30
        Go     \u2588\u2588\u2588               10

    Bar widths are proportional to the maximum value.
    """

    DEFAULT_CSS = """
    BarChart {
        height: auto;
    }
    """

    items: reactive[list[tuple[str, float]]] = reactive(list, layout=True)
    bar_width: reactive[int] = reactive(30)

    def __init__(
        self,
        items: list[tuple[str, float]] | None = None,
        bar_width: int = 30,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.items = list(items) if items else []
        self.bar_width = bar_width

    def render(self) -> Text:
        if not self.items:
            return Text("(no data)")

        max_val = max(v for _, v in self.items) if self.items else 1
        if max_val == 0:
            max_val = 1

        # Determine label column width for alignment.
        label_width = max(len(label) for label, _ in self.items)

        text = Text()
        for i, (label, value) in enumerate(self.items):
            padded_label = label.ljust(label_width)
            filled = int((value / max_val) * self.bar_width)
            empty = self.bar_width - filled
            bar = "\u2588" * filled + "\u2591" * empty

            # Pick a color based on the relative magnitude.
            ratio = value / max_val
            if ratio >= 0.75:
                bar_style = "green"
            elif ratio >= 0.40:
                bar_style = "yellow"
            else:
                bar_style = "cyan"

            text.append(f"{padded_label} ", style="bold")
            text.append(bar, style=bar_style)
            text.append(f" {_format_value(value)}", style="dim")
            if i < len(self.items) - 1:
                text.append("\n")

        return text

    def get_content_height(self, container, viewport, width: int) -> int:  # noqa: ANN001
        """Report the number of rows needed."""
        return max(len(self.items), 1)


def _format_value(v: float) -> str:
    """Format a numeric value for display beside the bar."""
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.1f}"
