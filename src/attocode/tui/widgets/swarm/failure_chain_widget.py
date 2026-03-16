"""Failure chain visualization for swarm TUI.

Displays failed tasks grouped by root cause with chain visualization.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static


_CAUSE_STYLES: dict[str, str] = {
    "timeout": "yellow",
    "budget": "dark_orange",
    "crash": "red bold",
    "dep_failure": "magenta",
    "coordination": "cyan",
    "agent_error": "red",
}

_CAUSE_ICONS: dict[str, str] = {
    "timeout": "\u23f1",  # stopwatch
    "budget": "\U0001f4b0",  # money bag
    "crash": "\U0001f4a5",  # collision
    "dep_failure": "\U0001f517",  # link
    "coordination": "\U0001f500",  # shuffle
    "agent_error": "\u26a0",  # warning
}


class FailureChainWidget(Static):
    """Displays failed tasks grouped by root cause with chain visualization."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._failures: list[dict[str, Any]] = []

    def update_failures(self, failures: list[dict[str, Any]]) -> None:
        self._failures = failures
        self.refresh()

    def render(self) -> Text:
        text = Text()
        if not self._failures:
            text.append("No failures", style="green dim")
            return text

        text.append("Failure Analysis\n", style="bold underline")

        # Group by cause
        by_cause: dict[str, list[dict[str, Any]]] = {}
        for f in self._failures:
            cause = f.get("cause", "unknown")
            by_cause.setdefault(cause, []).append(f)

        for cause, items in sorted(by_cause.items(), key=lambda x: -len(x[1])):
            style = _CAUSE_STYLES.get(cause, "white")
            icon = _CAUSE_ICONS.get(cause, "\u2022")
            text.append(f"\n{icon} {cause.upper()} ", style=style)
            text.append(f"({len(items)})\n", style="dim")

            for item in items[:10]:
                task_id = item.get("task_id", "")
                evidence = item.get("evidence", "")[:60]
                confidence = item.get("confidence", 0.0)
                chain = item.get("chain", [])

                text.append(f"  \u251c\u2500 {task_id}", style="bold")
                text.append(f" ({confidence:.0%})", style="dim")
                if evidence:
                    text.append(f"\n  \u2502  {evidence}", style="dim italic")
                if chain and len(chain) > 1:
                    chain_str = " \u2192 ".join(chain)
                    text.append(f"\n  \u2502  Chain: {chain_str}", style="dim")

                suggestion = item.get("suggestion", "")
                if suggestion:
                    text.append(f"\n  \u2502  Fix: {suggestion}", style="green dim")
                text.append("\n")

        return text
