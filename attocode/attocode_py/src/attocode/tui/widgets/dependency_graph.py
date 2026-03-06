"""Dependency graph widget — ASCII tree of imports and importers."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widget import Widget


class DependencyGraphWidget(Widget):
    """Displays imports (outbound) and importers (inbound) as an indented ASCII tree.

    Color-coded: yellow for imports, green for importers, dim for transitive.
    """

    DEFAULT_CSS = """
    DependencyGraphWidget {
        height: auto;
        max-height: 30;
        overflow-y: auto;
        padding: 0 1;
        display: none;
    }
    DependencyGraphWidget.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._file: str = ""
        self._outbound: dict[int, list[str]] = {}
        self._inbound: dict[int, list[str]] = {}
        self._depth: int = 2

    def set_graph(
        self,
        file: str,
        outbound: dict[int, list[str]],
        inbound: dict[int, list[str]],
        depth: int = 2,
    ) -> None:
        """Update the displayed dependency graph.

        Args:
            file: Center file path.
            outbound: {hop_distance: [file_paths]} for imports.
            inbound: {hop_distance: [file_paths]} for importers.
            depth: Maximum depth shown.
        """
        self._file = file
        self._outbound = outbound
        self._inbound = inbound
        self._depth = depth
        self.add_class("visible")
        self.refresh()

    def render(self) -> Text:
        if not self._file:
            return Text("(no dependency data)", style="dim")

        text = Text()
        text.append("Dependencies: ", style="bold")
        text.append(self._file, style="cyan")
        text.append(f"  (depth={self._depth})\n\n", style="dim")

        # Outbound (imports)
        text.append("  Imports\n", style="bold yellow")
        if self._outbound:
            for d in sorted(self._outbound):
                for f in self._outbound[d]:
                    indent = "    " + "  " * (d - 1)
                    arrow = "\u2192 " * min(d, 3)
                    style = "yellow" if d == 1 else "yellow dim"
                    text.append(f"{indent}{arrow}{f}\n", style=style)
        else:
            text.append("    (none)\n", style="dim")

        text.append("\n")

        # Inbound (importers)
        text.append("  Imported by\n", style="bold green")
        if self._inbound:
            for d in sorted(self._inbound):
                for f in self._inbound[d]:
                    indent = "    " + "  " * (d - 1)
                    arrow = "\u2190 " * min(d, 3)
                    style = "green" if d == 1 else "green dim"
                    text.append(f"{indent}{arrow}{f}\n", style=style)
        else:
            text.append("    (none)\n", style="dim")

        return text
