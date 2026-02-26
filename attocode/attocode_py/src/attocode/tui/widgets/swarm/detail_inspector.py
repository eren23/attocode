"""Detail Inspector — full info panel for a selected agent or task."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class DetailInspector(Static):
    """Shows detailed information for a selected agent or task.

    Set ``inspect_data`` to a dict with keys like:
    - kind: "agent" | "task"
    - agent_id / task_id
    - status
    - ... any other metadata
    """

    DEFAULT_CSS = """
    DetailInspector {
        height: auto;
        min-height: 6;
        max-height: 20;
        border: solid $surface-lighten-1;
        padding: 1;
        overflow-y: auto;
    }
    """

    inspect_data: reactive[dict[str, Any]] = reactive(dict)

    def watch_inspect_data(self, data: dict[str, Any]) -> None:
        self._rebuild(data)

    def inspect(self, data: dict[str, Any]) -> None:
        """External API to set inspection target."""
        self.inspect_data = data

    def _rebuild(self, data: dict[str, Any]) -> None:
        if not data:
            self.update(Text("Select an agent or task to inspect", style="dim italic"))
            return

        text = Text()
        kind = data.get("kind", "unknown")

        if kind == "agent":
            text.append("Agent: ", style="bold")
            text.append(data.get("agent_id", "?"), style="cyan bold")
            text.append("\n")
            text.append(f"  Status: {data.get('status', '?')}\n")
            text.append(f"  Task: {data.get('task_id', 'none')}\n")
            text.append(f"  Model: {data.get('model', '?')}\n")
            text.append(f"  Tokens: {data.get('tokens_used', 0):,}\n")
            text.append(f"  Elapsed: {data.get('elapsed', '?')}\n")

            files = data.get("files_modified", [])
            if files:
                text.append("\n  Files modified:\n")
                for f in files[:10]:
                    text.append(f"    \u2022 {f}\n", style="dim")

        elif kind == "task":
            text.append("Task: ", style="bold")
            text.append(data.get("task_id", "?"), style="green bold")
            text.append("\n")
            text.append(f"  Title: {data.get('title', '?')}\n")
            text.append(f"  Status: {data.get('status', '?')}\n")
            text.append(f"  Kind: {data.get('task_kind', '?')}\n")

            deps = data.get("deps", [])
            if deps:
                text.append(f"  Depends on: {', '.join(deps)}\n")

            targets = data.get("target_files", [])
            if targets:
                text.append("\n  Target files:\n")
                for f in targets[:10]:
                    text.append(f"    \u2022 {f}\n", style="dim")

            desc = data.get("description", "")
            if desc:
                text.append(f"\n  Description:\n  {desc[:200]}\n", style="dim italic")

        else:
            # Generic key-value display
            for key, value in data.items():
                if key == "kind":
                    continue
                text.append(f"  {key}: ", style="bold")
                text.append(f"{value}\n")

        self.update(text)
