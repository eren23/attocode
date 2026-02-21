"""Debug and diagnostic panels for the TUI.

Provides DebugPanel for live agent state inspection and
DiagnosticsPanel for system health overview.
"""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


# ─── DebugPanel ──────────────────────────────────────────────────────────────

class DebugPanel(VerticalScroll):
    """Live debug information panel.

    Shows agent state, current iteration, budget usage,
    recent trace events, and context window metrics.
    """

    DEFAULT_CSS = """
    DebugPanel {
        height: auto;
        max-height: 20;
        border: round $surface;
        padding: 0 1;
    }
    DebugPanel .debug-header {
        color: $warning;
        text-style: bold;
    }
    DebugPanel .debug-section {
        margin: 1 0 0 0;
    }
    DebugPanel .debug-value {
        color: $text;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Debug", classes="debug-header")
        yield Static("", id="debug-state", classes="debug-section")
        yield Static("", id="debug-budget", classes="debug-section")
        yield Static("", id="debug-context", classes="debug-section")
        yield Static("", id="debug-events", classes="debug-section")

    def update_state(
        self,
        *,
        iteration: int = 0,
        state: str = "",
        phase: str = "",
        tools_called: int = 0,
        llm_calls: int = 0,
    ) -> None:
        """Update the agent state section."""
        section = self.query_one("#debug-state", Static)
        lines = [
            f"State: {state}",
            f"Phase: {phase}",
            f"Iteration: {iteration}",
            f"Tools: {tools_called}  LLM: {llm_calls}",
        ]
        section.update("\n".join(lines))

    def update_budget(
        self,
        *,
        tokens_used: int = 0,
        tokens_budget: int = 0,
        cost: float = 0.0,
        enforcement: str = "",
    ) -> None:
        """Update the budget section."""
        section = self.query_one("#debug-budget", Static)
        fraction = tokens_used / tokens_budget if tokens_budget > 0 else 0.0
        lines = [
            f"Budget: {tokens_used:,}/{tokens_budget:,} ({fraction:.0%})",
            f"Cost: ${cost:.4f}",
            f"Enforcement: {enforcement}",
        ]
        section.update("\n".join(lines))

    def update_context(
        self,
        *,
        context_tokens: int = 0,
        context_max: int = 200_000,
        messages: int = 0,
        cache_hit_rate: float = 0.0,
    ) -> None:
        """Update the context window section."""
        section = self.query_one("#debug-context", Static)
        fraction = context_tokens / context_max if context_max > 0 else 0.0
        lines = [
            f"Context: {context_tokens:,}/{context_max:,} ({fraction:.0%})",
            f"Messages: {messages}",
            f"Cache hit: {cache_hit_rate:.0%}",
        ]
        section.update("\n".join(lines))

    def update_events(self, events: list[str]) -> None:
        """Update the recent events section."""
        section = self.query_one("#debug-events", Static)
        if not events:
            section.update("(no recent events)")
        else:
            section.update("\n".join(events[-5:]))


# ─── DiagnosticsPanel ────────────────────────────────────────────────────────

class DiagnosticsPanel(VerticalScroll):
    """System diagnostics and health panel.

    Shows provider health, error rates, loop detection status,
    compaction stats, and performance metrics.
    """

    DEFAULT_CSS = """
    DiagnosticsPanel {
        height: auto;
        max-height: 20;
        border: round $surface;
        padding: 0 1;
    }
    DiagnosticsPanel .diag-header {
        color: #89b4fa;
        text-style: bold;
    }
    DiagnosticsPanel .diag-ok {
        color: green;
    }
    DiagnosticsPanel .diag-warn {
        color: yellow;
    }
    DiagnosticsPanel .diag-error {
        color: red;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Diagnostics", classes="diag-header")
        yield Static("", id="diag-health")
        yield Static("", id="diag-errors")
        yield Static("", id="diag-loops")
        yield Static("", id="diag-compaction")

    def update_health(
        self,
        *,
        provider_status: str = "ok",
        avg_latency_ms: float = 0.0,
        error_rate: float = 0.0,
    ) -> None:
        """Update provider health status."""
        section = self.query_one("#diag-health", Static)
        status_cls = (
            "diag-ok" if provider_status == "ok"
            else "diag-warn" if provider_status == "degraded"
            else "diag-error"
        )
        lines = [
            f"Provider: {provider_status}",
            f"Latency: {avg_latency_ms:.0f}ms",
            f"Error rate: {error_rate:.1%}",
        ]
        section.update("\n".join(lines))

    def update_errors(
        self,
        *,
        total_errors: int = 0,
        recent_errors: list[str] | None = None,
    ) -> None:
        """Update error tracking."""
        section = self.query_one("#diag-errors", Static)
        lines = [f"Total errors: {total_errors}"]
        if recent_errors:
            for err in recent_errors[-3:]:
                lines.append(f"  - {err[:60]}")
        section.update("\n".join(lines))

    def update_loops(
        self,
        *,
        loop_detected: bool = False,
        repeated_tool: str = "",
        repeat_count: int = 0,
    ) -> None:
        """Update loop detection status."""
        section = self.query_one("#diag-loops", Static)
        if loop_detected:
            section.update(
                f"LOOP DETECTED: {repeated_tool} x{repeat_count}"
            )
        else:
            section.update("No loops detected")

    def update_compaction(
        self,
        *,
        total_compactions: int = 0,
        tokens_saved: int = 0,
        last_compaction_age: float = 0.0,
    ) -> None:
        """Update compaction stats."""
        section = self.query_one("#diag-compaction", Static)
        age_str = (
            f"{last_compaction_age:.0f}s ago" if last_compaction_age > 0
            else "never"
        )
        lines = [
            f"Compactions: {total_compactions}",
            f"Tokens saved: {tokens_saved:,}",
            f"Last: {age_str}",
        ]
        section.update("\n".join(lines))
