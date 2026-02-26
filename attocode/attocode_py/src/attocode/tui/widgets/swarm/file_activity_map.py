"""File Activity Map — tree view showing which agents touched which files."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class FileActivityMap(Static):
    """Tree view of file activity: which agents read/wrote which files."""

    DEFAULT_CSS = """
    FileActivityMap {
        height: auto;
        min-height: 4;
        max-height: 14;
        overflow-y: auto;
        padding: 0 1;
        border: solid $surface-lighten-1;
    }
    """

    activity: reactive[dict[str, list[dict[str, Any]]]] = reactive(dict)

    def watch_activity(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self._rebuild(data)

    def update_activity(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """External API.

        Args:
            data: mapping of ``file_path -> [{"agent_id": ..., "action": "read"|"write", ...}]``
        """
        self.activity = data

    def _rebuild(self, data: dict[str, list[dict[str, Any]]]) -> None:
        if not data:
            self.update(Text("(no file activity)", style="dim"))
            return

        text = Text()
        text.append("File Activity\n", style="bold underline")

        # Group by directory for a tree-like view
        by_dir: dict[str, list[tuple[str, list[dict[str, Any]]]]] = {}
        for file_path, actions in sorted(data.items()):
            parts = file_path.rsplit("/", 1)
            if len(parts) == 2:
                d, name = parts
            else:
                d, name = ".", parts[0]
            by_dir.setdefault(d, []).append((name, actions))

        for dir_path, files in by_dir.items():
            text.append(f"\n  {dir_path}/\n", style="bold")
            for name, actions in files:
                # Determine aggregate status
                writes = [a for a in actions if a.get("action") == "write"]
                reads = [a for a in actions if a.get("action") == "read"]
                agents = sorted({a.get("agent_id", "?") for a in actions})

                if writes:
                    icon = "\u270e"  # ✎
                    style = "green"
                else:
                    icon = "\u25cb"  # ○
                    style = "dim"

                text.append(f"    {icon} ", style=style)
                text.append(name, style=style)
                text.append(f"  [{', '.join(agents)}]", style="dim")

                if writes:
                    text.append(f"  ({len(writes)} writes)", style="green dim")
                text.append("\n")

        self.update(text)
