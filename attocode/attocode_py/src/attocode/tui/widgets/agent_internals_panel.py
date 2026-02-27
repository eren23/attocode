"""Agent internals panel -- economics, context, budget breakdown.

Collapsible side panel (toggle Ctrl+I) showing:
- Economics phase with history
- Context window usage bar with compaction markers
- Budget breakdown (input/output/cache tokens)
- Loop detector status
- Active tool call stack
"""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget


class AgentInternalsPanel(Widget):
    """Side panel showing agent internal state for debugging and monitoring."""

    DEFAULT_CSS = """
    AgentInternalsPanel {
        width: 40;
        height: 100%;
        dock: right;
        display: none;
        border-left: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    AgentInternalsPanel.visible {
        display: block;
    }
    """

    # Reactive properties
    phase: reactive[str] = reactive("exploration")
    context_pct: reactive[float] = reactive(0.0)
    budget_pct: reactive[float] = reactive(0.0)
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    cache_read: reactive[int] = reactive(0)
    cache_write: reactive[int] = reactive(0)
    compaction_count: reactive[int] = reactive(0)
    compaction_tokens_saved: reactive[int] = reactive(0)
    loop_detector_status: reactive[str] = reactive("ok")
    loop_tool_name: reactive[str] = reactive("")
    loop_count: reactive[int] = reactive(0)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._phase_history: list[tuple[float, str]] = []
        self._active_tools: list[str] = []

    def render(self) -> Text:
        text = Text()

        # Header
        text.append("Agent Internals\n", style="bold underline")
        text.append("\n")

        # Phase section
        text.append("Phase: ", style="dim")
        phase_style = {
            "exploration": "cyan",
            "planning": "yellow",
            "acting": "green",
            "verifying": "magenta",
        }.get(self.phase, "white")
        text.append(f"{self.phase}\n", style=f"bold {phase_style}")

        if self._phase_history:
            text.append("  History: ", style="dim")
            recent = self._phase_history[-5:]
            for _, p in recent:
                marker = {
                    "exploration": "E",
                    "planning": "P",
                    "acting": "A",
                    "verifying": "V",
                }.get(p, "?")
                text.append(f"{marker} ", style=phase_style)
            text.append("\n")

        text.append("\n")

        # Context window
        text.append("Context Window\n", style="bold")
        ctx_bar = _render_bar(self.context_pct, 30)
        text.append(f"  {ctx_bar} {self.context_pct:.0%}\n")
        if self.compaction_count > 0:
            text.append(f"  Compactions: {self.compaction_count}", style="dim")
            text.append(
                f" ({self.compaction_tokens_saved:,} saved)\n", style="dim"
            )

        text.append("\n")

        # Budget
        text.append("Budget\n", style="bold")
        bud_bar = _render_bar(self.budget_pct, 30)
        text.append(f"  {bud_bar} {self.budget_pct:.0%}\n")

        text.append("\n")

        # Token breakdown
        text.append("Token Breakdown\n", style="bold")
        text.append(f"  Input:  {self.input_tokens:>10,}\n", style="dim")
        text.append(f"  Output: {self.output_tokens:>10,}\n", style="dim")
        text.append(f"  Cache R:{self.cache_read:>10,}\n", style="dim")
        text.append(f"  Cache W:{self.cache_write:>10,}\n", style="dim")

        total_input = self.input_tokens + self.cache_read
        if total_input > 0:
            hit_rate = self.cache_read / total_input
            text.append(
                f"  Hit Rate: {hit_rate:.1%}\n",
                style="cyan" if hit_rate > 0.5 else "dim",
            )

        text.append("\n")

        # Loop detector
        text.append("Loop Detector\n", style="bold")
        if self.loop_detector_status == "ok":
            text.append("  Status: OK\n", style="green dim")
        else:
            text.append(
                f"  WARNING: {self.loop_tool_name} x{self.loop_count}\n",
                style="bold red",
            )

        text.append("\n")

        # Active tools
        if self._active_tools:
            text.append("Active Tools\n", style="bold")
            for tool in self._active_tools[-5:]:
                text.append(f"  > {tool}\n", style="yellow dim")

        return text

    def update_phase(self, new_phase: str) -> None:
        """Update the economics phase."""
        if new_phase != self.phase:
            self._phase_history.append((time.time(), new_phase))
            if len(self._phase_history) > 20:
                self._phase_history = self._phase_history[-20:]
            self.phase = new_phase

    def record_compaction(self, tokens_saved: int) -> None:
        """Record a compaction event."""
        self.compaction_count += 1
        self.compaction_tokens_saved += tokens_saved

    def update_cache_stats(
        self,
        cache_read: int,
        cache_write: int,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Update cumulative cache statistics."""
        self.cache_read += cache_read
        self.cache_write += cache_write
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def set_doom_loop(self, tool_name: str, count: int) -> None:
        """Set doom loop warning state."""
        self.loop_detector_status = "warning"
        self.loop_tool_name = tool_name
        self.loop_count = count

    def clear_doom_loop(self) -> None:
        """Clear doom loop warning."""
        self.loop_detector_status = "ok"
        self.loop_tool_name = ""
        self.loop_count = 0

    def set_active_tools(self, tools: list[str]) -> None:
        """Update the active tool call stack."""
        self._active_tools = tools
        self.refresh()


def _render_bar(fraction: float, width: int = 30) -> str:
    """Render a simple progress bar string."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(fraction * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"
