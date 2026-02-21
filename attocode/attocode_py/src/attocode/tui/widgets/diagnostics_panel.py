"""Diagnostics panel for system health overview.

Provides a comprehensive view of system health including provider
status, budget usage, context window, and detected issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass(slots=True)
class DiagnosticItem:
    """A single diagnostic check result."""

    name: str
    status: str  # "ok", "warning", "error"
    value: str
    details: str = ""


class DiagnosticsPanel(VerticalScroll):
    """System diagnostics overview panel.

    Shows:
    - Provider connection status
    - Budget usage breakdown
    - Context window utilization
    - Loop detection status
    - Resource usage
    - Active issues/warnings
    """

    DEFAULT_CSS = """
    DiagnosticsPanel {
        height: auto;
        max-height: 20;
        border: round $surface;
        padding: 0 1;
    }
    DiagnosticsPanel .diag-header {
        color: $primary;
        text-style: bold;
    }
    DiagnosticsPanel .diag-ok {
        color: $success;
    }
    DiagnosticsPanel .diag-warning {
        color: $warning;
    }
    DiagnosticsPanel .diag-error {
        color: $error;
    }
    """

    diagnostics: reactive[list[DiagnosticItem]] = reactive(list, layout=True)

    def compose(self) -> ComposeResult:
        yield Static("Diagnostics", classes="diag-header")
        yield Static("", id="diag-items")
        yield Static("", id="diag-issues")

    def update_diagnostics(
        self,
        *,
        provider_status: str = "ok",
        provider_name: str = "",
        budget_usage: float = 0.0,
        context_usage: float = 0.0,
        iteration: int = 0,
        max_iterations: int = 0,
        doom_loop: bool = False,
        memory_mb: float = 0.0,
        active_subagents: int = 0,
    ) -> None:
        """Update all diagnostic values."""
        items: list[DiagnosticItem] = []

        # Provider
        items.append(DiagnosticItem(
            name="Provider",
            status=provider_status,
            value=provider_name or "unknown",
        ))

        # Budget
        budget_status = "ok" if budget_usage < 0.7 else ("warning" if budget_usage < 0.9 else "error")
        items.append(DiagnosticItem(
            name="Budget",
            status=budget_status,
            value=f"{budget_usage:.0%}",
        ))

        # Context
        ctx_status = "ok" if context_usage < 0.7 else ("warning" if context_usage < 0.9 else "error")
        items.append(DiagnosticItem(
            name="Context",
            status=ctx_status,
            value=f"{context_usage:.0%}",
        ))

        # Iterations
        iter_str = f"{iteration}"
        if max_iterations > 0:
            iter_str += f"/{max_iterations}"
        items.append(DiagnosticItem(
            name="Iterations",
            status="ok" if not max_iterations or iteration < max_iterations * 0.8 else "warning",
            value=iter_str,
        ))

        # Doom loop
        items.append(DiagnosticItem(
            name="Loop Detection",
            status="error" if doom_loop else "ok",
            value="DETECTED" if doom_loop else "clear",
        ))

        # Memory
        if memory_mb > 0:
            mem_status = "ok" if memory_mb < 400 else ("warning" if memory_mb < 500 else "error")
            items.append(DiagnosticItem(
                name="Memory",
                status=mem_status,
                value=f"{memory_mb:.0f}MB",
            ))

        # Subagents
        if active_subagents > 0:
            items.append(DiagnosticItem(
                name="Subagents",
                status="ok",
                value=str(active_subagents),
            ))

        self.diagnostics = items
        self._render()

    def _render(self) -> None:
        """Render diagnostic items."""
        items_widget = self.query_one("#diag-items", Static)
        issues_widget = self.query_one("#diag-issues", Static)

        if not self.diagnostics:
            items_widget.update("No diagnostics")
            issues_widget.update("")
            return

        status_icons = {"ok": "●", "warning": "▲", "error": "✗"}
        lines: list[str] = []
        issues: list[str] = []

        for item in self.diagnostics:
            icon = status_icons.get(item.status, "?")
            lines.append(f"  {icon} {item.name}: {item.value}")
            if item.status == "error":
                issues.append(f"  ! {item.name}: {item.details or item.value}")
            elif item.status == "warning":
                issues.append(f"  ? {item.name}: {item.details or item.value}")

        items_widget.update("\n".join(lines))
        issues_widget.update("\n".join(issues) if issues else "")

    def clear(self) -> None:
        """Clear diagnostics."""
        self.diagnostics = []
        self._render()
