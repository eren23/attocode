"""Impact graph widget — blast radius grouped by BFS hop distance."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widget import Widget


class ImpactGraphWidget(Widget):
    """Shows blast radius of file changes grouped by BFS hop distance.

    Color: red for hop 1 (direct), yellow for hop 2, dim for hop 3+.
    Renders > >> >>> arrows to indicate distance.
    """

    DEFAULT_CSS = """
    ImpactGraphWidget {
        height: auto;
        max-height: 30;
        overflow-y: auto;
        padding: 0 1;
        display: none;
    }
    ImpactGraphWidget.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._file: str = ""
        self._impact: dict[int, list[str]] = {}

    def set_impact(self, file: str, impact: dict[int, list[str]]) -> None:
        """Update the displayed impact analysis.

        Args:
            file: The changed file.
            impact: {hop_distance: [affected_file_paths]}.
        """
        self._file = file
        self._impact = impact
        self.add_class("visible")
        self.refresh()

    def render(self) -> Text:
        if not self._file:
            return Text("(no impact data)", style="dim")

        text = Text()
        text.append("Impact Analysis: ", style="bold")
        text.append(self._file, style="cyan")

        total = sum(len(v) for v in self._impact.values())
        text.append(f"  ({total} files affected)\n\n", style="dim")

        if not self._impact:
            text.append("  No downstream impact detected.\n", style="green")
            return text

        _HOP_STYLES = {  # noqa: N806
            1: "bold red",
            2: "yellow",
        }

        for d in sorted(self._impact):
            files = self._impact[d]
            style = _HOP_STYLES.get(d, "dim")
            arrow = ">" * min(d, 4)
            text.append(f"  Hop {d} ({len(files)} files):\n", style=style)
            for f in files[:20]:
                text.append(f"    {arrow} {f}\n", style=style)
            if len(files) > 20:
                text.append(f"    ... and {len(files) - 20} more\n", style="dim")
            text.append("\n")

        return text
