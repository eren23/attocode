"""Column-aligned ASCII table widget.

Usage::

    table = ASCIITable(
        headers=["Metric", "Value"],
        rows=[("Tokens", "12,450"), ("Cost", "$0.03")],
    )
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget

from rich.text import Text


class ASCIITable(Widget):
    """Renders a simple column-aligned table with header and separator.

    Output example::

        Metric   | Value
        ---------+--------
        Tokens   | 12,450
        Cost     | $0.03
    """

    DEFAULT_CSS = """
    ASCIITable {
        height: auto;
    }
    """

    headers: reactive[list[str]] = reactive(list, layout=True)
    rows: reactive[list[tuple[str, ...]]] = reactive(list, layout=True)

    def __init__(
        self,
        headers: list[str] | None = None,
        rows: list[tuple[str, ...]] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.headers = list(headers) if headers else []
        self.rows = list(rows) if rows else []

    def render(self) -> Text:
        if not self.headers:
            return Text("(no data)")

        num_cols = len(self.headers)

        # Compute the maximum width for each column.
        col_widths = [len(h) for h in self.headers]
        for row in self.rows:
            for i in range(min(num_cols, len(row))):
                col_widths[i] = max(col_widths[i], len(row[i]))

        text = Text()

        # Header row.
        header_parts: list[str] = []
        for i, h in enumerate(self.headers):
            header_parts.append(h.ljust(col_widths[i]))
        text.append(" | ".join(header_parts), style="bold")
        text.append("\n")

        # Separator row.
        sep_parts: list[str] = []
        for w in col_widths:
            sep_parts.append("-" * w)
        text.append("-+-".join(sep_parts), style="dim")

        # Data rows.
        for row in self.rows:
            text.append("\n")
            parts: list[str] = []
            for i in range(num_cols):
                cell = row[i] if i < len(row) else ""
                parts.append(cell.ljust(col_widths[i]))
            text.append(" | ".join(parts))

        return text

    def get_content_height(self, container, viewport, width: int) -> int:  # noqa: ANN001
        """Report the number of rows needed (header + separator + data rows)."""
        return max(2 + len(self.rows), 1)
