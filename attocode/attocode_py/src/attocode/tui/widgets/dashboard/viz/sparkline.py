"""Sparkline widget -- render a data series as a single row of Unicode blocks.

Usage::

    spark = SparkLine(data=[1, 3, 7, 2, 5], max_width=20)
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget

from rich.text import Text

# Eight Unicode block-element characters ordered by ascending height.
_BLOCKS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


class SparkLine(Widget):
    """Renders a numeric data series as a compact sparkline.

    Each value is mapped to one of eight block characters (``\u2581`` through ``\u2588``)
    proportional to the series min/max.  The widget always occupies a single
    line of height and up to *max_width* columns.
    """

    DEFAULT_CSS = """
    SparkLine {
        height: 1;
    }
    """

    data: reactive[list[float]] = reactive(list, layout=True)
    max_width: reactive[int] = reactive(40)

    def __init__(
        self,
        data: list[float] | None = None,
        max_width: int = 40,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.data = list(data) if data else []
        self.max_width = max_width

    def render(self) -> Text:
        if not self.data:
            return Text("")

        values = self.data
        # If we have more data points than max_width, take the tail.
        if len(values) > self.max_width:
            values = values[-self.max_width :]

        lo = min(values)
        hi = max(values)
        span = hi - lo if hi != lo else 1.0

        chars: list[str] = []
        for v in values:
            # Map value to index 0..7 within _BLOCKS (skip the space at idx 0
            # so the minimum still gets a visible bar).
            idx = int(((v - lo) / span) * 7)
            idx = max(1, min(8, idx + 1))  # clamp to 1..8
            chars.append(_BLOCKS[idx])

        return Text("".join(chars), style="green")
