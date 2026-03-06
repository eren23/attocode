"""Hotspot heatmap widget — bar chart of top files by complexity score."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widget import Widget


class HotspotHeatmap(Widget):
    """Bar chart of top files by composite complexity score.

    Uses block characters, color by severity (red/yellow/cyan).
    """

    DEFAULT_CSS = """
    HotspotHeatmap {
        height: auto;
        max-height: 30;
        overflow-y: auto;
        padding: 0 1;
        display: none;
    }
    HotspotHeatmap.visible {
        display: block;
    }
    """

    BAR_WIDTH = 25

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._hotspots: list[dict[str, Any]] = []

    def set_hotspots(self, hotspots: list[dict[str, Any]]) -> None:
        """Update the displayed hotspot data.

        Args:
            hotspots: List of dicts with keys: file, score, lines, fan_in, fan_out, category.
        """
        self._hotspots = hotspots
        self.add_class("visible")
        self.refresh()

    def render(self) -> Text:
        if not self._hotspots:
            return Text("(no hotspot data)", style="dim")

        text = Text()
        text.append("Hotspot Heatmap", style="bold underline")
        text.append(f"  (top {len(self._hotspots)} files)\n\n", style="dim")

        max_score = max((h.get("score", 0) for h in self._hotspots), default=1)
        if max_score == 0:
            max_score = 1

        # Determine label width
        label_width = max(
            (len(_short_path(h.get("file", ""))) for h in self._hotspots),
            default=20,
        )
        label_width = min(label_width, 40)

        for h in self._hotspots:
            file_path = _short_path(h.get("file", "?"))
            score = h.get("score", 0)
            category = h.get("category", "")

            ratio = score / max_score
            filled = int(ratio * self.BAR_WIDTH)
            empty = self.BAR_WIDTH - filled

            if ratio >= 0.75:
                bar_style = "red"
            elif ratio >= 0.40:
                bar_style = "yellow"
            else:
                bar_style = "cyan"

            label = file_path[:label_width].ljust(label_width)
            text.append(f"  {label} ", style="bold")
            text.append("\u2588" * filled, style=bar_style)
            text.append("\u2591" * empty, style="dim")
            text.append(f" {score:.0f}", style="dim")
            if category:
                text.append(f"  [{category}]", style="dim italic")
            text.append("\n")

        return text


def _short_path(path: str, max_len: int = 45) -> str:
    """Shorten a file path for display, preserving start and end."""
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    if len(parts) <= 3:
        return path
    # Show first dir + ... + last 2 components
    short = "/".join(parts[:1]) + "/\u2026/" + "/".join(parts[-2:])
    if len(short) <= max_len:
        return short
    # Still too long — just truncate with ellipsis
    return path[:max_len - 1] + "\u2026"
