"""Budget projection widget for swarm TUI.

Shows budget usage with EWMA-based projection overlay, colored by warning level.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static


_LEVEL_STYLES: dict[str, str] = {
    "ok": "green",
    "caution": "yellow",
    "warning": "dark_orange",
    "critical": "red",
    "shutdown": "red bold reverse",
}


class BudgetProjectionWidget(Static):
    """Displays budget projection with warning level coloring."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._projection: dict[str, Any] = {}

    def update_projection(self, projection: dict[str, Any]) -> None:
        self._projection = projection
        self.refresh()

    def render(self) -> Text:
        text = Text()
        p = self._projection
        if not p:
            text.append("No budget data", style="dim")
            return text

        level = p.get("warning_level", "ok")
        style = _LEVEL_STYLES.get(level, "white")

        # Header
        fraction = p.get("usage_fraction", 0.0)
        pct = int(fraction * 100)
        text.append(f"Budget: {pct}% ", style=style)

        # Bar visualization (20 chars wide)
        bar_width = 20
        filled = min(int(fraction * bar_width), bar_width)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        text.append(f"[{bar}] ", style=style)

        # Level badge
        text.append(f" {level.upper()} ", style=f"on {style.split()[0]}" if style != "white" else "bold")
        text.append("\n")

        # Details
        avg = p.get("avg_cost_per_task", 0.0)
        projected = p.get("projected_total_cost", 0.0)
        completable = p.get("estimated_completable", 0)
        will_exceed = p.get("will_exceed", False)

        if avg > 0:
            text.append(f"  Avg/task: ${avg:.3f}", style="dim")
            text.append(f"  Projected: ${projected:.2f}", style="red" if will_exceed else "dim")
            text.append(f"  Can complete: ~{completable} more", style="dim")

        msg = p.get("message", "")
        if msg:
            text.append(f"\n  {msg}", style=style)

        return text
