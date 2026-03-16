"""Conflict visualization panel for swarm TUI.

Shows file conflicts with involved tasks, symbols, resolution strategy,
and blast radius information.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static


_RESOLUTION_STYLES: dict[str, str] = {
    "auto_merged": "green",
    "advisor_resolved": "cyan",
    "judge_needed": "yellow bold",
    "failed": "red bold",
}


class ConflictPanel(Static):
    """Displays file conflicts with resolution status."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._conflicts: list[dict[str, Any]] = []

    def update_conflicts(self, conflicts: list[dict[str, Any]]) -> None:
        self._conflicts = conflicts
        self.refresh()

    def render(self) -> Text:
        text = Text()
        if not self._conflicts:
            text.append("No conflicts detected", style="green dim")
            return text

        text.append("File Conflicts\n", style="bold underline")
        text.append(
            f"{'File':<30} {'Tasks':<20} {'Symbol':<15} {'Resolution':<15} {'Strategy':<12}\n",
            style="bold dim",
        )
        text.append("\u2500" * 92 + "\n", style="dim")

        for c in self._conflicts[-30:]:  # Show last 30
            file_path = str(c.get("file_path", ""))
            if len(file_path) > 28:
                file_path = "..." + file_path[-25:]

            task_a = str(c.get("task_a", ""))[:8]
            task_b = str(c.get("task_b", ""))[:8]
            tasks = f"{task_a} vs {task_b}"

            symbol = str(c.get("symbol_name", ""))[:13]
            resolution = str(c.get("resolution", "pending"))
            strategy = str(c.get("strategy", ""))[:10]

            res_style = _RESOLUTION_STYLES.get(resolution, "white")

            text.append(f"{file_path:<30} ", style="white")
            text.append(f"{tasks:<20} ", style="dim")
            text.append(f"{symbol:<15} ", style="cyan")
            text.append(f"{resolution:<15} ", style=res_style)
            text.append(f"{strategy:<12}\n", style="dim")

            # Show blast radius if available
            blast = c.get("blast_radius_files", [])
            if blast:
                files_str = ", ".join(str(f).rsplit("/", 1)[-1] for f in blast[:3])
                extra = f" +{len(blast) - 3}" if len(blast) > 3 else ""
                text.append(f"  Blast radius: {files_str}{extra}\n", style="dim italic")

        return text
